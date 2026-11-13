"""Topogram, planning, non-contrast scan and its review: steps 19 to 25 of the exam.

The topogram and centring steps are in workflow_topogram.py, the two planning steps in planning.py and the
acquisition in acquisition.py. This file lists the seven steps and holds the scan and review routines.
"""
from typing import Generator

from scansim.core.fields import Field
from scansim.core.steps import Step, StepError
from scansim.ct.acquisition import acquire_series
from scansim.ct.context import CTContext
from scansim.ct.planning import ScanPlanner
from scansim.ct.repeat_rules import before_injection
from scansim.ct.workflow_prescan import sample_step
from scansim.ct.workflow_topogram import topogram_steps
from scansim.snapshot import SeriesView

NOT_ANSWERED, YES, NO = "not_answered", "yes", "no"
ANSWERS = ((NOT_ANSWERED, "Not answered"), (YES, "Yes"), (NO, "No"))
NONCONTRAST = "noncontrast"


def _scan_noncontrast(planner: ScanPlanner):
    def routine(ctx: CTContext, step: Step) -> Generator:
        earlier = ctx.console.find_series(NONCONTRAST)
        repeat = earlier.status == "done"
        if repeat:                       # scan the range as it is planned now; the earlier images stay until then
            planner.replan(ctx, NONCONTRAST)
        try:
            yield from acquire_series(ctx, NONCONTRAST, step=step)
        finally:
            if repeat and ctx.console.find_series(NONCONTRAST).status != "done":
                ctx.console.replace_series(earlier)          # the repeat did not happen: the earlier scan stands
            elif repeat:                                     # also when stopped while the new images are rebuilt
                _keep_on_the_dose_record(ctx, earlier)
        series = ctx.console.find_series(NONCONTRAST)
        step.add_result("DLP", f"{series.plan.dlp_mgycm:.0f} mGy·cm")
        step.add_result("Scan time", f"{series.plan.scan_time_s:.1f} s")
    return routine


def _keep_on_the_dose_record(ctx: CTContext, earlier: SeriesView) -> None:
    """A scan that was done again has lost its row to the new one, but it exposed the patient: its dose is
    already in the total, so it is listed and logged."""
    dlp = earlier.plan.dlp_mgycm
    ctx.console.list_exposure(earlier.label, "earlier scan, scanned again", dlp)
    ctx.log.add("event", f"{earlier.label}: scanned again; the earlier scan's {dlp:.0f} mGy·cm stays in the dose total")


def _liver_margins_mm(ctx: CTContext, start_mm: float, end_mm: float) -> tuple[float, float]:
    """(margin above the liver top, margin below the liver bottom); a negative margin means it sticks out."""
    top = ctx.pack.landmarks["liver_top"] - ctx.landmark_z_body_mm
    bottom = ctx.pack.landmarks["liver_bottom"] - ctx.landmark_z_body_mm
    return top - start_mm, end_mm - bottom


def _describe_margins(above: float, below: float) -> str:
    top = (f"{above:.0f} mm of margin above the top of the liver" if above >= 0
           else f"the liver extends {-above:.0f} mm above the start of the range")
    bottom = (f"{below:.0f} mm of margin below the bottom of the liver" if below >= 0
              else f"the liver extends {-below:.0f} mm below the end of the range")
    return f"{top}; {bottom}"


def _review(ctx: CTContext, step: Step) -> None:
    answer = step.value("liver_included")
    if answer == NOT_ANSWERED:
        raise StepError("Say whether the whole liver is in the scan before you accept it")
    plan = ctx.console.find_series(NONCONTRAST).plan
    above, below = _liver_margins_mm(ctx, plan.start_mm, plan.end_mm)
    covered = above >= 0 and below >= 0
    step.add_result("Liver covered", "Yes" if covered else "No")
    step.add_result("Truth", _describe_margins(above, below))
    if answer == YES and not covered:
        step.add_result("Check", "You accepted a scan that cuts off the liver: the range must be planned again "
                                 "and the scan repeated", alert=True)
    elif answer == NO and covered:
        step.add_result("Check", "The liver is fully covered: no new scan was needed")


def _step(step_id: str, info: str, routine, fields=(), **kwargs) -> Step:
    stage_id, title, actor, place, _ = sample_step(step_id)
    return Step(step_id, stage_id, title, actor=actor, place=place, info=info, fields=fields, routine=routine,
                **kwargs)


def scan_steps(ctx: CTContext) -> list[Step]:
    planner = ScanPlanner(ctx)
    answer = Field("liver_included", "Whole liver included", "choice", NOT_ANSWERED, source="assumption",
                   options=ANSWERS, help="Judge from the images, then answer.")
    return [
        *topogram_steps(ctx),
        _step("plan_ranges", "Each series gets its own frame on the topogram; the whole range must lie inside the "
              "topogram, or the dose control has no data there (note 01, A6). Drag the dashed box on the AP "
              "topogram or type the numbers, then accept them here. A series already scanned keeps its images "
              "until it is scanned again.", planner.plan_ranges,
              list(planner.range_fields.values()), repeatable=True, invalidates=("confirm_settings",),
              check=before_injection),
        _step("confirm_settings", "The patient-specific CTDIvol and DLP come from the topogram; the console warns "
              "when they pass the notification value (note 01, A7). Settings apply to every series not yet scanned. "
              "The dose figures are estimates: the scanner's dose calibration is assumed.",
              planner.confirm_settings, list(planner.setting_fields.values()), repeatable=True,
              check=before_injection),
        _step("scan_noncontrast", "The patient is told to hold the breath, the table moves through the spinning "
              "gantry and the images are rebuilt (note 01, A5).", _scan_noncontrast(planner)),
        _step("review_noncontrast", "Scroll through the images and check that the liver is complete at both ends "
              "before any contrast is given.", _review, [answer], repeatable=True, check=before_injection),
    ]
