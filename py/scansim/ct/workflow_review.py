"""Review of the four phases and sending the images.

`review_phases` may read the true anatomy and the contrast model: it is the review step after the scans,
so it is allowed to show the truth (coverage, motion, and the enhancement at each series' scan time).

ASSUMPTIONS:
  - TIMING_TOLERANCE_S: an arterial scan centred within 5 s of the aortic peak counts as well timed. Research
    note 02 section H gives a three-way grading (early, appropriate, late) from the images but no threshold in
    seconds, and calls a technologist-level checklist with thresholds UNCONFIRMED.
  - NEAR_PEAK_FRACTION: a scan whose aorta is at 90% of the peak or more is acceptable even when it is not
    centred on the peak (the protocol times the late arterial phase from the trigger, not from the peak).
  - SEND_IMAGES_JUMP_S: sending to the archive takes 30 s (the brief's value).
"""
import numpy as np

from scansim.core.steps import Step
from scansim.ct.context import CTContext
from scansim.ct.step_factory import make_step
from scansim.snapshot import SeriesView

SEND_IMAGES_JUMP_S = 30.0
TIMING_TOLERANCE_S = 5.0
NEAR_PEAK_FRACTION = 0.9
PEAK_SEARCH_S = 300.0
PEAK_SEARCH_STEP_S = 0.5


def _covers_liver(ctx: CTContext, series: SeriesView) -> bool:
    top = ctx.pack.landmarks["liver_top"] - ctx.landmark_z_body_mm
    bottom = ctx.pack.landmarks["liver_bottom"] - ctx.landmark_z_body_mm
    return series.plan.start_mm <= top and bottom <= series.plan.end_mm


def _enhancement_at(ctx: CTContext, series: SeriesView, compartment: str) -> float:
    """Added HU in a compartment halfway through the series' scan; zero for a series without contrast."""
    if series.id not in ctx.console.enhancement_at:
        return 0.0
    middle = series.started_at_s + series.plan.scan_time_s / 2.0
    return ctx.console.enhancement_at[series.id](middle)[compartment]


def _aortic_peak(ctx: CTContext) -> tuple[float, float]:
    """(time, added HU) of the aortic peak after the injection start."""
    start = ctx.injector.started_at_s
    grid = np.arange(start, start + PEAK_SEARCH_S, PEAK_SEARCH_STEP_S)
    curve = ctx.contrast.curve("aorta", grid)
    return float(grid[curve.argmax()]), float(curve.max())


def _timing_note(ctx: CTContext, series: SeriesView) -> tuple[str, bool]:
    """Plain-language comment on the arterial timing against the aortic peak, and whether it is a problem."""
    peak_s, peak_hu = _aortic_peak(ctx)
    offset = series.started_at_s + series.plan.scan_time_s / 2.0 - peak_s
    aorta = _enhancement_at(ctx, series, "aorta")
    levels = f"aorta {aorta:.0f} of {peak_hu:.0f} HU at the peak"
    if abs(offset) <= TIMING_TOLERANCE_S:
        return f"Well timed: centred {abs(offset):.0f} s from the aortic peak ({levels})", False
    word, side = ("early", "before") if offset < 0 else ("late", "after")
    if aorta >= NEAR_PEAK_FRACTION * peak_hu:
        return f"Centred {abs(offset):.0f} s {side} the aortic peak, but the aorta is near its peak ({levels}): acceptable", False
    return (f"The scan was {word}: centred {abs(offset):.0f} s {side} the aortic peak ({levels}); "
            "the phase cannot be repeated without new contrast"), True


def _review_phases(ctx: CTContext, step: Step) -> None:
    for series in ctx.console.series:
        if series.status != "done":
            step.add_result(series.label, "Not scanned" + (" (phase missed)" if series.status == "missed" else ""),
                            alert=True)
            continue
        covered = _covers_liver(ctx, series)
        text = (f"Liver {'covered' if covered else 'cut off'}; {'motion seen' if series.motion else 'no motion'}; "
                f"aorta +{_enhancement_at(ctx, series, 'aorta'):.0f} HU, "
                f"liver +{_enhancement_at(ctx, series, 'liver'):.0f} HU")
        step.add_result(series.label, text, alert=series.motion or not covered)
        if series.id == "arterial":
            note, alert = _timing_note(ctx, series)
            step.add_result("Arterial timing", note, alert=alert)


def _send_images(ctx: CTContext, step: Step) -> None:
    ctx.jump(SEND_IMAGES_JUMP_S)
    for series in ctx.console.series:
        if series.status == "done":
            step.add_result(series.label, f"CTDIvol {series.plan.ctdi_vol_mgy:.1f} mGy, "
                                          f"DLP {series.plan.dlp_mgycm:.0f} mGy·cm")
    extra = ctx.console.extra_exposures
    if extra:                 # stopped or repeated scans: in the total, but not among the series above
        step.add_result("Also in the total", "; ".join(f"{e.label}, {e.what}: {e.dlp_mgycm:.0f} mGy·cm" for e in extra))
    step.add_result("Total DLP", f"{ctx.console.total_dlp_mgycm:.0f} mGy·cm")


def review_steps(ctx: CTContext) -> list[Step]:
    return [
        make_step("review_phases", "Check each phase for coverage, motion and enhancement; a phase that was "
                  "missed or mistimed cannot be re-acquired without a new injection (note 02 sections H and J). "
                  "This step shows the truth from the patient model.", _review_phases),
        make_step("send_images", "Images and the dose record go to the archive; the dose report carries CTDIvol "
                  "and DLP per acquisition (note 02 section I).", _send_images),
    ]
