"""Bolus-tracking set-up: the monitoring slice, the region on the aorta and the armed injector.

Tracking state lives in `console.tracking` (a `TrackingView`). Region coordinates are measured from the
field-of-view centre of the arterial plan; adding the plan's centre gives the image-centre coordinates the
renderer uses.

ASSUMPTIONS (research note 02 section C gives numbers for the monitoring scans, but none for these):
  - the default region (x 10 mm, y 45 mm, radius 8 mm): a plausible but unchecked place, so it may miss the
    aorta; the limits of the three region fields and of the injector fields are wide on purpose, the steps
    refuse what cannot work;
  - MONITORING_KV and MONITORING_MAS: 120 kV and 20 mAs per rotation (research note 01 section C, CARE Bolus,
    Stanford protocol; note 02 section C gives 10 mA for one study);
  - the monitoring level is pre-filled with the midpoint of the arterial range (the brief's computed default)
    and follows the range until the user chooses a level.
"""
from typing import Any, Generator

from scansim.core.fields import Field, FieldError
from scansim.core.steps import Step, StepError
from scansim.ct.acquisition import (require_room_ready, require_table_travel, spin_up, switch_everything_off,
                                    wait_until)
from scansim.ct.context import CTContext
from scansim.ct.prescan_fields import MIN_PHASE_ML
from scansim.ct.repeat_rules import before_injection
from scansim.ct.scan_fields import RANGE_LIMIT_MM, number_field, source_for
from scansim.ct.step_factory import make_step
from scansim.devices.injector import InjectorPhase
from scansim.imaging import render
from scansim.patient.pack import OutsideAnatomy
from scansim.snapshot import TrackingView

MONITORING_KV = 120
MONITORING_MAS = 20.0
ROI_DEFAULTS = {"roi_x_mm": 10.0, "roi_y_mm": 45.0, "roi_r_mm": 8.0}
BLOOD_BASELINE_HU = (20.0, 90.0)     # assumption: unenhanced blood reads roughly 30 to 60 HU
ROI_LIMIT_MM = 250.0
ROI_RADIUS_MAX_MM = 60.0
VOLUME_MAX_ML = 200.0
RATE_MAX_ML_S = 10.0


# ---- geometry shared with the contrast steps ----

def arterial_plan(ctx: CTContext):
    return ctx.console.find_series("arterial").plan


def slice_mm_default(ctx: CTContext) -> float:
    """Midpoint of the arterial range: the planned one once ranges exist, else the protocol's default."""
    try:
        plan = arterial_plan(ctx)
        return (plan.start_mm + plan.end_mm) / 2.0
    except LookupError:
        series = next(s for s in ctx.protocol.series if s.id == "arterial")
        return (series.default_start_mm + series.default_end_mm) / 2.0


def region_centre_mm(ctx: CTContext, tracking: TrackingView) -> tuple[float, float]:
    """The region's centre in image-centre coordinates (the plan's field-of-view centre added)."""
    plan = arterial_plan(ctx)
    return tracking.roi_x_mm + plan.fov_center_x_mm, tracking.roi_y_mm + plan.fov_center_y_mm


def measure_region_hu(ctx: CTContext, tracking: TrackingView, enhancement=None) -> float:
    x, y = region_centre_mm(ctx, tracking)
    return render.roi_mean_hu(ctx.pack, ctx.body_z(tracking.slice_mm), x, y, tracking.roi_r_mm, enhancement)


def _anatomy_problem(ctx: CTContext, level_mm: float) -> str:
    """Why a monitoring level cannot be used ("" when it can, or when no landmark is set to measure from)."""
    if ctx.landmark_z_body_mm is None:
        return ""
    top, bottom = ctx.pack.data_range_mm
    if top <= ctx.body_z(level_mm) <= bottom:
        return ""
    landmark = ctx.landmark_z_body_mm
    return (f"The monitoring level {level_mm:g} mm is outside the patient's CT data, which runs from "
            f"{top - landmark:.0f} to {bottom - landmark:.0f} mm from the landmark")


class SliceField(Field):
    """The monitoring level. Until the user sets one it follows the middle of the arterial range."""

    def __init__(self, ctx: CTContext) -> None:
        super().__init__("slice_mm", "Monitoring level", "number", slice_mm_default(ctx), source="assumption",
                         unit="mm", min=-RANGE_LIMIT_MM, max=RANGE_LIMIT_MM, step=1.0,
                         help="From the landmark. Pre-filled with the middle of the arterial range, which is an "
                              "assumption, not where the vessel is best seen; drag the dashed line on the AP "
                              "topogram or type a level.")
        self._ctx, self._chosen = ctx, False

    def set(self, raw: Any) -> None:
        level = self._parse_number(raw)
        problem = _anatomy_problem(self._ctx, level)
        if problem:
            raise FieldError(problem)
        self.value, self._chosen = level, True

    def level(self) -> float:
        return self.value if self._chosen else slice_mm_default(self._ctx)

    def view(self, editable: bool = True):
        shown = super().view(editable)
        return shown.model_copy(update={"value": self.level(), "default": slice_mm_default(self._ctx)})


# ---- monitoring_slice ----

def _require_anatomy_at(ctx: CTContext, level_mm: float) -> None:
    problem = _anatomy_problem(ctx, level_mm)
    if problem:
        raise StepError(problem)
    try:
        ctx.pack.slice_index(ctx.body_z(level_mm))
    except OutsideAnatomy as err:
        raise StepError(f"The monitoring level {level_mm:g} mm has no anatomy data: {err}") from None


def monitoring_rotation(ctx: CTContext, rotation_s: float) -> Generator:
    ctx.kv, ctx.beam_on = MONITORING_KV, True
    ctx.ma = MONITORING_MAS / rotation_s
    yield from wait_until(ctx, ctx.clock.now_s + rotation_s)
    ctx.beam_on, ctx.ma = False, 0.0


def _monitoring_slice(setup: "TrackingSetup"):
    def routine(ctx: CTContext, step: Step) -> Generator:
        if ctx.console.tracking is not None and ctx.console.tracking.state != "slice_acquired":
            raise StepError("The injection has started: a new monitoring slice can no longer be taken")
        level = setup.slice_field.level()
        plan = arterial_plan(ctx)
        require_room_ready(ctx)
        _require_anatomy_at(ctx, level)
        travel, _ = require_table_travel(ctx, level, level, "The monitoring slice")
        try:
            yield from ctx.table.move_long(travel)
            ctx.room.warning_light_on = True
            yield from spin_up(ctx, plan.rotation_s)
            yield from monitoring_rotation(ctx, plan.rotation_s)
        finally:
            switch_everything_off(ctx, None)
        ctx.console.start_tracking(TrackingView(
            state="slice_acquired", slice_mm=level, roi_x_mm=setup.roi_value("roi_x_mm"),
            roi_y_mm=setup.roi_value("roi_y_mm"), roi_r_mm=setup.roi_value("roi_r_mm"),
            threshold_hu=setup.threshold_field.value))
        step.add_result("Monitoring level", f"{level:g} mm from the landmark")
    return routine


# ---- place_roi ----

def _place_roi(setup: "TrackingSetup"):
    def routine(ctx: CTContext, step: Step) -> None:
        tracking = ctx.console.tracking
        if tracking is None or tracking.state != "slice_acquired":
            raise StepError("Scan the monitoring slice first" if tracking is None
                            else "The injection has started: the region can no longer be moved")
        moved = ctx.console.update_tracking(
            **{key: setup.roi_value(key) for key in ROI_DEFAULTS}, threshold_hu=setup.threshold_field.value)
        baseline = measure_region_hu(ctx, moved)
        moved = ctx.console.update_tracking(baseline_hu=baseline, samples=[])
        step.add_result("Baseline", f"Baseline {baseline:.0f} HU")
        if not BLOOD_BASELINE_HU[0] <= baseline <= BLOOD_BASELINE_HU[1]:
            step.add_result("Check", f"Baseline {baseline:.0f} HU is not blood: the region is probably not on the "
                                     "aorta", alert=True)
        step.add_result("Trigger", f"The scan starts when the region reaches {baseline + moved.threshold_hu:.0f} HU "
                                   f"({moved.threshold_hu:g} HU above baseline)")
    return routine


# ---- arm_injector ----

def _injector_blockers(ctx: CTContext, step: Step) -> list[str]:
    state = ctx.injector.state
    return [] if state == "connected" else [f"The injector must be connected to the patient (it is {state})"]


def _arm_injector(ctx: CTContext, step: Step) -> None:
    contrast = (step.value("volume_ml"), step.value("rate_ml_s"))
    saline = (step.value("saline_ml"), step.value("saline_rate_ml_s"))
    loaded = ctx.injector.view()
    if contrast[0] > loaded.contrast_ml or saline[0] > loaded.saline_ml:
        raise StepError(f"Programmed {contrast[0]:g} mL contrast and {saline[0]:g} mL saline, but only "
                        f"{loaded.contrast_ml:g} mL and {loaded.saline_ml:g} mL are in the injector "
                        "(the test flush used some saline): lower the volumes")
    ctx.injector.program([InjectorPhase("contrast", *contrast), InjectorPhase("saline", *saline)])
    ctx.injector.arm()
    step.add_result("Programmed", f"{contrast[0]:g} mL contrast at {contrast[1]:g} mL/s, then {saline[0]:g} mL "
                                  f"saline at {saline[1]:g} mL/s")
    step.add_result("Pressure limit", f"{ctx.injector.view().pressure_limit_psi:g} psi (assumed, as is the "
                                      "pressure model)")


# ---- the steps ----

class TrackingSetup:
    """The fields of the level, the region and the threshold, shared by the monitoring slice and the region step."""

    def __init__(self, ctx: CTContext) -> None:
        timing = ctx.protocol.contrast.timing if ctx.protocol.contrast else None
        self.slice_field = SliceField(ctx)
        self.roi_fields = {
            "roi_x_mm": number_field("roi_x_mm", "Region x", ROI_DEFAULTS["roi_x_mm"], "assumption", unit="mm",
                                     lo=-ROI_LIMIT_MM, hi=ROI_LIMIT_MM,
                                     help="Centre of the region, to the patient's left of the field-of-view centre."),
            "roi_y_mm": number_field("roi_y_mm", "Region y", ROI_DEFAULTS["roi_y_mm"], "assumption", unit="mm",
                                     lo=-ROI_LIMIT_MM, hi=ROI_LIMIT_MM,
                                     help="Centre of the region, toward the patient's back from the field-of-view centre."),
            "roi_r_mm": number_field("roi_r_mm", "Region radius", ROI_DEFAULTS["roi_r_mm"], "assumption", unit="mm",
                                     lo=1.0, hi=ROI_RADIUS_MAX_MM, help="Keep the region inside the vessel."),
        }
        self.threshold_field = number_field(
            "threshold_hu", "Trigger threshold", timing.threshold_hu if timing else 0.0,
            source_for(ctx.protocol, "contrast.timing.threshold_hu"), unit="HU", lo=1.0, hi=1000.0,
            help="A rise above the baseline in the region, not an absolute value.")

    def roi_value(self, key: str) -> float:
        return self.roi_fields[key].value


def _injector_fields(ctx: CTContext) -> list[Field]:
    c = ctx.protocol.contrast
    spec = [("volume_ml", "Contrast volume", c.volume_ml if c else 0.0, "mL", VOLUME_MAX_ML),
            ("rate_ml_s", "Contrast rate", c.rate_ml_s if c else 0.0, "mL/s", RATE_MAX_ML_S),
            ("saline_ml", "Saline chaser", c.saline_ml if c else 0.0, "mL", VOLUME_MAX_ML),
            ("saline_rate_ml_s", "Saline rate", c.saline_rate_ml_s if c else 0.0, "mL/s", RATE_MAX_ML_S)]
    return [number_field(key, label, value, source_for(ctx.protocol, f"contrast.{key}"), unit=unit,
                         lo=MIN_PHASE_ML, hi=hi,
                         help="The injector refuses more than is loaded; the pressure limit may lower the rate.")
            for key, label, value, unit, hi in spec]


def tracking_steps(ctx: CTContext) -> list[Step]:
    setup = TrackingSetup(ctx)
    return [
        make_step("monitoring_slice", "One low-dose rotation at the level where the vessel will be watched "
                  "(note 01, CARE Bolus). Monitoring scans are not added to the dose total: note 02 section C "
                  "gives no per-image figure. A new slice needs the region placed again.",
                  _monitoring_slice(setup), [setup.slice_field], repeatable=True, invalidates=("place_roi",),
                  check=before_injection),
        make_step("place_roi", "Draw one circle inside the aorta and accept it; the baseline is its mean HU before "
                  "contrast (note 01, CARE Bolus). Click the aorta on the tracking image in the Contrast tab; "
                  "\"Show reference anatomy\" marks it. The dashed circle is where you clicked; it becomes the "
                  "region when you accept it here. The threshold is relative to that baseline. A baseline "
                  "outside 20 to 90 HU (an assumption) is not blood and raises a warning.",
                  _place_roi(setup), [*setup.roi_fields.values(), setup.threshold_field], repeatable=True,
                  check=before_injection),
        # An armed injector cannot be armed twice: repeating an earlier step never sends this one to "redo".
        make_step("arm_injector", "Program the contrast and saline phases and arm the injector; the injector "
                  "limits the pressure and lowers the rate if needed (note 02 section B). The pressure model and "
                  "its limit are assumed.", _arm_injector,
                  _injector_fields(ctx), check=_injector_blockers, irreversible=True),
    ]
