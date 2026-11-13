"""Planning on the topogram: the scan ranges, then the scan settings with the predicted dose.

`ScanPlanner` owns the fields of both steps, because the series plans (`console.series`) depend on both:
`plan_ranges` fixes start, end and field of view; `confirm_settings` adds kV, mAs, pitch, rotation and
collimation and works out feed, time, CTDIvol and DLP for every series that has not been scanned yet.

The tube current for the prediction follows the patient's water-equivalent diameter over the planned range
(`pack.metrics.dw_mm`), as the real scanner derives it from the topogram.

Planning again never discards a series that has been scanned (or missed): it keeps its images and its place.
The newly accepted range of such a series is remembered and used when its scan is repeated (`replan`).
"""
import numpy as np

from scansim.core.fields import Field
from scansim.core.steps import Step, StepError
from scansim.ct.acquisition import recon_views
from scansim.ct.console import SCANNED_STATUSES
from scansim.ct.context import CTContext
from scansim.ct.dose import dose_alerts, series_dose, table_feed_mm_s
from scansim.ct.scan_fields import LinkedRangeField, NumericChoiceField, number_field, source_for
from scansim.ct.workflow_topogram import complete_topogram, span_mm
from scansim.protocols.schema import SeriesSpec
from scansim.snapshot import SeriesPlanView, SeriesView

FOV_RANGE_MM = (100.0, 500.0)
FOV_CENTRE_LIMIT_MM = 250.0
MAS_RANGE = (1.0, 1000.0)
PITCH_RANGE = (0.1, 10.0)      # wide: a pitch the scanner cannot do is refused with its limit
LINK_KEY = "link_ranges"


class ScanPlanner:
    def __init__(self, ctx: CTContext) -> None:
        self.range_fields = self._range_fields(ctx)
        self.setting_fields = self._setting_fields(ctx)
        self.accepted: dict[str, tuple[float, float, dict]] = {}    # per series: start, end, field of view

    # ---- fields ----

    def _range_fields(self, ctx: CTContext) -> dict[str, Field]:
        p = ctx.protocol
        group: dict[str, Field] = {}
        for series in p.series:
            for edge, label, default in (("start_mm", "start", series.default_start_mm),
                                         ("end_mm", "end", series.default_end_mm)):
                key = f"{series.id}.{edge}"
                group[key] = LinkedRangeField(
                    key, f"{series.label} {label}", edge, default,
                    source=source_for(p, f"series.{series.id}.default_{edge}"), group=group, link_key=LINK_KEY,
                    help="From the landmark; negative is toward the head." if edge == "start_mm" else "")
        group[LINK_KEY] = Field(LINK_KEY, "Link ranges", "bool", True, source="assumption",
                                help="While on, changing one series' start or end changes them all.")
        fov_source = source_for(p, "scan_defaults.fov_mm")
        group["fov_mm"] = number_field("fov_mm", "Field of view", p.scan_defaults.fov_mm, fov_source, unit="mm",
                                       lo=FOV_RANGE_MM[0], hi=FOV_RANGE_MM[1])
        for axis in ("x", "y"):
            group[f"fov_center_{axis}_mm"] = number_field(
                f"fov_center_{axis}_mm", f"Field of view centre {axis}", 0.0, "assumption", unit="mm",
                lo=-FOV_CENTRE_LIMIT_MM, hi=FOV_CENTRE_LIMIT_MM, help="0 is the centre of the image.")
        return group

    def _setting_fields(self, ctx: CTContext) -> dict[str, Field]:
        d, spec, p = ctx.protocol.scan_defaults, ctx.spec, ctx.protocol
        fields = [
            NumericChoiceField("kv", "Tube voltage", d.kv, spec.kv_options, source="protocol", unit="kV"),
            number_field("quality_ref_mas", "Quality reference", d.quality_ref_mas, "protocol", unit="mAs",
                         lo=MAS_RANGE[0], hi=MAS_RANGE[1]),
            number_field("pitch", "Pitch", d.pitch, source_for(p, "scan_defaults.pitch"), lo=PITCH_RANGE[0],
                         hi=PITCH_RANGE[1], step=0.1, help=f"The scanner allows up to {spec.max_pitch:g}."),
            NumericChoiceField("rotation_s", "Rotation time", d.rotation_s, spec.rotation_times_s,
                               source=source_for(p, "scan_defaults.rotation_s"), unit="s"),
            NumericChoiceField("collimation_mm", "Collimation", d.collimation_mm, spec.collimations_mm,
                               source=source_for(p, "scan_defaults.collimation_mm"), unit="mm"),
        ]
        return {f.key: f for f in fields}

    # ---- plan_ranges ----

    def plan_ranges(self, ctx: CTContext, step: Step) -> None:
        topo = complete_topogram(ctx, "AP")
        low, high = span_mm(topo)
        ranges = {}
        for series in ctx.protocol.series:
            start, end = (self.range_fields[f"{series.id}.{e}"].value for e in ("start_mm", "end_mm"))
            if end <= start:
                raise StepError(f"{series.label}: the end ({end:g} mm) must be beyond the start ({start:g} mm)")
            if start < low or end > high:
                raise StepError(f"{series.label}: the range {start:g} to {end:g} mm is not inside the AP topogram "
                                f"({low:.0f} to {high:.0f} mm); change the range or take a longer topogram")
            ranges[series.id] = (start, end)
        self._store(ctx, ranges)
        for series in ctx.protocol.series:
            start, end = ranges[series.id]
            step.add_result(series.label, f"{start:g} to {end:g} mm ({end - start:g} mm long)")

    def _store(self, ctx: CTContext, ranges: dict[str, tuple[float, float]]) -> None:
        """Accept the ranges. A series already scanned or missed stays as it is; the others get a fresh plan."""
        fov = {key: self.range_fields[key].value for key in ("fov_mm", "fov_center_x_mm", "fov_center_y_mm")}
        self.accepted = {sid: (start, end, fov) for sid, (start, end) in ranges.items()}
        kept = {s.id: s for s in ctx.console.series if s.status in SCANNED_STATUSES}
        ctx.console.series = [kept.get(spec.id) or self._fresh(ctx, spec) for spec in ctx.protocol.series]

    def _fresh(self, ctx: CTContext, spec: SeriesSpec) -> SeriesView:
        start, end, fov = self.accepted[spec.id]
        return SeriesView(id=spec.id, label=spec.label, status="planned", plan=self._plan(ctx, start, end, fov),
                          recons=recon_views(ctx, spec.id, start, end, fov["fov_mm"]),
                          image_url_template=ctx.console.series_url_template(spec.id), scanned_fraction=0.0)

    def replan(self, ctx: CTContext, series_id: str) -> None:
        """A scan is being repeated: give its series a fresh plan from the range and settings accepted last."""
        spec = next(s for s in ctx.protocol.series if s.id == series_id)
        ctx.console.replace_series(self._fresh(ctx, spec))

    # ---- confirm_settings ----

    def confirm_settings(self, ctx: CTContext, step: Step) -> None:
        values = {key: f.value for key, f in self.setting_fields.items()}
        if values["pitch"] > ctx.spec.max_pitch:
            raise StepError(f"Pitch {values['pitch']:g} is above the scanner maximum of {ctx.spec.max_pitch:g}")
        todo = [s for s in ctx.console.series if s.status == "planned"]
        if not todo:
            raise StepError("There is no planned series to confirm settings for: plan the ranges first")
        alerts: list[str] = []
        for series in todo:
            plan = self._plan(ctx, series.plan.start_mm, series.plan.end_mm, series.plan.model_dump())
            ctx.console.update_series(series.id, plan=plan)
            step.add_result(series.label, f"feed {plan.feed_mm_s:.0f} mm/s, {plan.scan_time_s:.1f} s, "
                            f"CTDIvol {plan.ctdi_vol_mgy:.1f} mGy, DLP {plan.dlp_mgycm:.0f} mGy·cm")
            alerts.extend(a for a in dose_alerts(plan.ctdi_vol_mgy, ctx.spec) if a not in alerts)
        for text in alerts:
            step.add_result("Dose", text, alert=True)
        ctx.console.dose_alerts = alerts

    # ---- the numbers of one series ----

    def _plan(self, ctx: CTContext, start: float, end: float, fov: dict) -> SeriesPlanView:
        v = {key: f.value for key, f in self.setting_fields.items()}
        feed = table_feed_mm_s(v["pitch"], v["collimation_mm"], v["rotation_s"])
        dose = series_dose(self._dw_over(ctx, start, end), int(v["kv"]), v["quality_ref_mas"], end - start, ctx.spec)
        return SeriesPlanView(
            start_mm=start, end_mm=end, fov_mm=fov["fov_mm"], fov_center_x_mm=fov["fov_center_x_mm"],
            fov_center_y_mm=fov["fov_center_y_mm"], kv=int(v["kv"]), quality_ref_mas=v["quality_ref_mas"],
            pitch=v["pitch"], rotation_s=v["rotation_s"], collimation_mm=v["collimation_mm"], feed_mm_s=feed,
            scan_time_s=(end - start) / feed, ctdi_vol_mgy=dose.ctdi_vol_mgy, dlp_mgycm=dose.dlp_mgycm)

    @staticmethod
    def _dw_over(ctx: CTContext, start: float, end: float) -> np.ndarray:
        k0, k1 = ctx.pack.slice_index(ctx.body_z(start)), ctx.pack.slice_index(ctx.body_z(end))
        dw = np.asarray(ctx.pack.metrics.dw_mm[k0:k1 + 1], dtype=float)
        dw = dw[np.isfinite(dw)]
        if dw.size == 0:
            raise StepError(f"No patient lies in the range {start:g} to {end:g} mm")
        return dw
