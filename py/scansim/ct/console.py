"""What the console shows: topograms, series plans and results, tracking and dose.

It starts empty. The scan and contrast steps fill the plain attributes below; `view` turns them into
the snapshot's console section. The session asks it for images, so it also builds the image URLs.
"""
import math
from typing import TYPE_CHECKING, Callable, Mapping, Optional

from scansim.ct.acquisition import series_image
from scansim.imaging import render
from scansim.patient.pack import OutsideAnatomy
from scansim.snapshot import (ConsoleView, DoseView, ExtraExposure, ReferenceLine, ReferencePoint, SeriesView,
                              TopogramView, TrackingSample, TrackingView)

if TYPE_CHECKING:
    from scansim.ct.context import CTContext

# Landmarks drawn as reference lines when the learner turns the reference on: (pack key, label).
REFERENCE_LANDMARKS = (
    ("liver_top", "Top of liver"),
    ("liver_bottom", "Bottom of liver"),
    ("iliac_crest", "Iliac crest"),
    ("xiphoid", "Xiphoid process"),
    ("sternal_notch", "Sternal notch"),
)


# A series in one of these states has been exposed: re-planning or a new landmark must not discard it.
SCANNED_STATUSES = ("done", "scanning", "missed")

# A series' enhancement: added HU per compartment at a simulation time (None for no contrast).
EnhancementAt = Callable[[float], Optional[Mapping[str, float]]]


class ConsoleState:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.topograms: list[TopogramView] = []
        self.series: list[SeriesView] = []
        self.tracking: Optional[TrackingView] = None
        self.total_dlp_mgycm: float = 0.0
        self.extra_exposures: list[ExtraExposure] = []      # in the total, but not the row of any series
        self.dose_alerts: list[str] = []
        self.enhancement_at: dict[str, EnhancementAt] = {}      # per series id; absent = no contrast
        self.tracking_enhancement_at: Optional[EnhancementAt] = None   # enhancement of the monitoring images
        self.tracking_image_count: int = 0       # changes with every new monitoring image: the URL's cache key
        self.last_monitoring_s: Optional[float] = None       # when the latest monitoring scan was made

    # ---- image URLs (the server serves these paths) ----

    def topogram_url(self, view: str, edge_row: Optional[int] = None) -> str:
        """`edge_row` (the row now at the moving edge) is a cache key: the client refetches when it changes."""
        query = "" if edge_row is None else f"?r={edge_row}"
        return f"/api/session/{self.session_id}/topogram/{view}.png{query}"

    def series_url_template(self, series_id: str) -> str:
        return f"/api/session/{self.session_id}/series/{series_id}/{{plane}}/{{index}}.png"

    def tracking_url(self, count: Optional[int] = None) -> str:
        """`count` (the number of monitoring images so far) is a cache key: the client refetches when it changes."""
        query = "" if count is None else f"?n={count}"
        return f"/api/session/{self.session_id}/tracking.png{query}"

    # ---- what the steps fill in ----

    def set_topogram(self, topogram: TopogramView) -> None:
        """Store a topogram, replacing the same view; AP is listed before LAT."""
        kept = [t for t in self.topograms if t.view != topogram.view]
        self.topograms = sorted([*kept, topogram], key=lambda t: t.view)

    def find_series(self, series_id: str) -> SeriesView:
        for series in self.series:
            if series.id == series_id:
                return series
        raise LookupError(f"No series {series_id!r} has been planned")

    def update_series(self, series_id: str, **changes) -> SeriesView:
        """Replace a series with a changed copy (snapshots share the views, so they are never edited)."""
        updated = self.find_series(series_id).model_copy(update=changes)
        self.series = [updated if s.id == series_id else s for s in self.series]
        return updated

    def replace_series(self, series: SeriesView) -> None:
        self.series = [series if s.id == series.id else s for s in self.series]

    def list_exposure(self, label: str, what: str, dlp_mgycm: float) -> None:
        """Keep an exposure on the dose record that no series row shows: a sweep stopped part-way, or a scan
        that was done again. The caller sees to the total; the log shows only its last lines, so the list is
        what lets the Dose tab add up."""
        self.extra_exposures = [*self.extra_exposures, ExtraExposure(label=label, what=what, dlp_mgycm=dlp_mgycm)]

    def landmark_moved(self, shift_mm: float) -> None:
        """The landmark was set again: positions measured from the old one are `shift_mm` larger from the new.

        Topograms, plans not yet scanned and the tracking slice were made in the old frame and are dropped;
        they are made again. A scanned series keeps its images: its range is re-expressed from the new landmark,
        so it still shows the same part of the body.
        """
        self.topograms = []
        self.tracking, self.tracking_enhancement_at, self.last_monitoring_s = None, None, None
        self.series = [
            s.model_copy(update={"plan": s.plan.model_copy(update={
                "start_mm": s.plan.start_mm + shift_mm, "end_mm": s.plan.end_mm + shift_mm})})
            for s in self.series if s.status in SCANNED_STATUSES]

    def start_tracking(self, view: TrackingView) -> None:
        """A new monitoring slice: the image shows no contrast until monitoring scans are made."""
        self.tracking_image_count += 1
        self.last_monitoring_s = None
        self.tracking = view.model_copy(update={"image_url": self.tracking_url(self.tracking_image_count)})

    def update_tracking(self, **changes) -> TrackingView:
        self.tracking = self.tracking.model_copy(update=changes)
        return self.tracking

    def add_monitoring_sample(self, sample: TrackingSample, scanned_at_s: float) -> None:
        """Store a monitoring measurement; the image now shows the enhancement at `scanned_at_s`."""
        self.tracking_image_count += 1
        self.last_monitoring_s = scanned_at_s
        self.update_tracking(samples=[*self.tracking.samples, sample],
                             image_url=self.tracking_url(self.tracking_image_count))

    # ---- snapshot ----

    def view(self, ctx: "CTContext") -> ConsoleView:
        return ConsoleView(
            topograms=list(self.topograms), series=list(self.series), tracking=self.tracking,
            dose=DoseView(total_dlp_mgycm=self.total_dlp_mgycm, alerts=list(self.dose_alerts),
                          extra_exposures=list(self.extra_exposures)),
            reference=self._reference_lines(ctx) if ctx.show_reference else [],
            reference_points=self._reference_points(ctx) if ctx.show_reference else [])

    def _reference_lines(self, ctx: "CTContext") -> list[ReferenceLine]:
        if ctx.landmark_z_body_mm is None:
            return []
        return [ReferenceLine(name=name, label=label,
                              from_landmark_mm=ctx.pack.landmarks[name] - ctx.landmark_z_body_mm)
                for name, label in REFERENCE_LANDMARKS if name in ctx.pack.landmarks]

    def _reference_points(self, ctx: "CTContext") -> list[ReferencePoint]:
        """The true aorta on the monitoring slice, measured from the field-of-view centre of the arterial plan."""
        if self.tracking is None or self.tracking.slice_mm is None:
            return []
        try:
            plan = self.find_series("arterial").plan
            k = ctx.pack.slice_index(ctx.body_z(self.tracking.slice_mm))
        except (LookupError, OutsideAnatomy):       # nothing to mark: a snapshot never fails over a reference
            return []
        x, y = ctx.pack.metrics.aorta_x_mm[k], ctx.pack.metrics.aorta_y_mm[k]
        if not (math.isfinite(x) and math.isfinite(y)):
            return []
        return [ReferencePoint(name="aorta", label="Aorta", x_mm=float(x) - plan.fov_center_x_mm,
                               y_mm=float(y) - plan.fov_center_y_mm)]

    # ---- images (rendered on request, never in the snapshot) ----

    def topogram_png(self, ctx: "CTContext", view: str) -> bytes:
        for topo in self.topograms:
            if topo.view == view:
                return render.topogram_png(
                    ctx.pack, topo.view, revealed=(topo.revealed_from_row, topo.revealed_to_row))
        raise LookupError(f"No {view} topogram has been acquired yet")

    def series_png(self, ctx: "CTContext", series_id: str, plane: str, index: int) -> bytes:
        return series_image(ctx, series_id, plane, index)

    def tracking_png(self, ctx: "CTContext") -> bytes:
        """The monitoring slice at the arterial field of view, with the enhancement of the latest monitoring scan."""
        tracking = self.tracking
        if tracking is None or tracking.slice_mm is None:
            raise LookupError("No monitoring slice has been acquired yet")
        series = self.find_series("arterial")
        plan = series.plan
        axial = next(r for r in series.recons if r.plane == "axial")
        fn, when = self.tracking_enhancement_at, self.last_monitoring_s
        return render.axial_png(
            ctx.pack, ctx.body_z(tracking.slice_mm), fov_mm=plan.fov_mm, center_x_mm=plan.fov_center_x_mm,
            center_y_mm=plan.fov_center_y_mm, enhancement=fn(when) if fn and when is not None else None,
            thickness_mm=axial.thickness_mm)
