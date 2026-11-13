"""Acquiring a series: the table feeds through the beam while the rotor turns, then the images are rebuilt.

`acquire_series` is used by the non-contrast scan and, later, by every contrast phase. A phase that has
contrast in the images registers a function first: `ctx.console.enhancement_at[series_id] = fn` (or the
`enhancement_at` argument), where `fn(sim_time_s)` gives the added HU per compartment at that time.

Stopping a scan. Before the sweep has finished, a stop puts the series back to "planned"; the part of the
range already exposed is added to the dose total, logged, and listed on the dose record as an exposure of its
own (`console.extra_exposures`), because no series row shows it. Once the sweep has finished the exposure cannot
be undone: the series is done, its reconstructions are completed even if the step is stopped while they are
being rebuilt, and the step is marked `committed` so that the stop completes it.
"""
from typing import Callable, Generator, Mapping, Optional

from scansim.core.process import Sleep, Tick, Until
from scansim.patient.breathing import HOLD_RAMP_S
from scansim.core.steps import Step, StepError
from scansim.ct.context import CTContext
from scansim.imaging import render
from scansim.room.table import OUT_OF_BORE_MM
from scansim.snapshot import ReconView, SeriesView

HOLD_VOICE = {"inspiration": "Breathe in and hold your breath", "expiration": "Breathe out and hold your breath"}
RELEASE_VOICE = "Breathe normally"
HOLD_TIMEOUT_S = 10.0
FULL_TURN_DEG = 360.0
PREP_MARGIN_S = 0.5          # slack added to the estimated preparation time of a scan with a target beam-on time
LATE_REPORT_S = 0.5          # a scan starting later than this after its target time is reported

EnhancementAt = Callable[[float], Optional[Mapping[str, float]]]


# ---- checks and clean-up shared with the topograms ----

def require_room_ready(ctx: CTContext) -> None:
    if ctx.room.door_open:
        raise StepError("The scan room door is open: close it before any X-rays are made")


def require_table_travel(ctx: CTContext, first_mm: float, last_mm: float, what: str) -> tuple[float, float]:
    """Table travel for the two ends of a run, refused (before anything moves) if the table cannot do it."""
    table = ctx.spec.table
    long_first, long_last = ctx.long_for(first_mm), ctx.long_for(last_mm)
    low, high = min(long_first, long_last), max(long_first, long_last)
    if low < 0 or high > table.long_max_mm:
        raise StepError(f"{what} needs table travel from {low:.0f} to {high:.0f} mm; the table moves "
                        f"between 0 and {table.long_max_mm:.0f} mm")
    if high > OUT_OF_BORE_MM and ctx.table.height_mm < table.height_min_in_bore_mm:
        raise StepError(f"Raise the table to at least {table.height_min_in_bore_mm:.0f} mm "
                        "before moving it into the bore")
    return long_first, long_last


def start_breath_hold(ctx: CTContext, phase: str):
    """Give the voice command and start the hold; returns the process (None when no hold is wanted)."""
    if phase == "none":
        return None
    ctx.say(HOLD_VOICE[phase])
    return ctx.scheduler.start(ctx.breathing.hold(phase), name="breath_hold")


def switch_everything_off(ctx: CTContext, hold) -> None:
    """Leave the room safe: beam, warning light, rotor and breath-hold off, tube at rest."""
    ctx.beam_on = False
    ctx.ma = 0.0
    ctx.room.warning_light_on = False
    ctx.rotor_rps = 0.0
    ctx.tube_angle_deg = 0.0
    if hold is not None:
        ctx.scheduler.cancel(hold)
    ctx.breathing.release()


def turn_tube(ctx: CTContext, dt_s: float) -> None:
    ctx.tube_angle_deg = (ctx.tube_angle_deg + ctx.rotor_rps * FULL_TURN_DEG * dt_s) % FULL_TURN_DEG


def sweep(ctx: CTContext, long_to_mm: float, speed_mm_s: float,
          on_progress: Callable[[float], None]) -> Generator:
    """Move the table at a constant speed to `long_to_mm`, turning the tube; `on_progress` gets 0..1."""
    origin = ctx.table.long_mm
    total = abs(long_to_mm - origin)
    sign = 1.0 if long_to_mm >= origin else -1.0
    travelled = 0.0
    while travelled < total:
        dt = yield Tick()
        travelled = min(total, travelled + speed_mm_s * dt)
        ctx.table.long_mm = origin + sign * travelled
        turn_tube(ctx, dt)
        on_progress(travelled / total)


def spin_up(ctx: CTContext, rotation_s: float) -> Generator:
    """Bring the rotor to speed; nothing to do when it already turns at that speed."""
    target, elapsed = 1.0 / rotation_s, 0.0
    if abs(ctx.rotor_rps - target) < 1e-9:
        return
    while elapsed < ctx.spec.rotor_spinup_s:
        dt = yield Tick()
        elapsed += dt
        ctx.rotor_rps = target * min(1.0, elapsed / ctx.spec.rotor_spinup_s)
        turn_tube(ctx, dt)
    ctx.rotor_rps = target


def wait_until(ctx: CTContext, time_s: float, stop: Optional[Callable[[], bool]] = None) -> Generator:
    """Wait until simulation time `time_s` (or until `stop()` is true), keeping the tube turning."""
    while ctx.clock.now_s < time_s - 1e-9 and not (stop is not None and stop()):
        turn_tube(ctx, (yield Tick()))


# ---- the acquisition ----

def preflight_series(ctx: CTContext, series_id: str) -> tuple[SeriesView, float, float]:
    """Everything that can refuse a scan, checked before anything moves; returns the series and the table
    travel at its start and end."""
    series = ctx.console.find_series(series_id)
    plan = series.plan
    require_room_ready(ctx)
    long_start, long_end = require_table_travel(ctx, plan.start_mm, plan.end_mm, f"{series.label} scan")
    _require_anatomy(ctx, series)
    return series, long_start, long_end


def prep_lead_s(ctx: CTContext, series_id: str, rotor_stopped: bool = False) -> float:
    """Seconds from starting the preparation (table move, rotor, breath-hold command) to beam-on, from where
    the table is now. `rotor_stopped` asks for the time with the rotor at rest, whatever it is doing now."""
    plan = ctx.console.find_series(series_id).plan
    move_s = abs(ctx.long_for(plan.start_mm) - ctx.table.long_mm) / ctx.spec.table.long_speed_mm_s
    at_speed = not rotor_stopped and abs(ctx.rotor_rps - 1.0 / plan.rotation_s) < 1e-9
    return move_s + (0.0 if at_speed else ctx.spec.rotor_spinup_s) + HOLD_RAMP_S + PREP_MARGIN_S


def acquire_series(ctx: CTContext, series_id: str, enhancement_at: Optional[EnhancementAt] = None, *,
                   beam_on_at_s: Optional[float] = None, step: Optional[Step] = None) -> Generator:
    """Scan one planned series over its range; ends when its reconstructions are ready.

    With `beam_on_at_s` the preparation starts early enough for the beam to come on at that time; when that
    is not possible the scan starts as soon as it is ready and one event says how late it was. `step` is the
    step this scan belongs to: it is marked committed when the sweep has finished.
    """
    series, long_start, long_end = preflight_series(ctx, series_id)
    protocol_series = next(s for s in ctx.protocol.series if s.id == series_id)
    plan = series.plan
    _register_enhancement(ctx, series_id, enhancement_at)
    hold, finished = None, False
    try:
        if beam_on_at_s is not None:
            yield from wait_until(ctx, beam_on_at_s - prep_lead_s(ctx, series_id))
        yield from ctx.table.move_long(long_start)
        ctx.room.warning_light_on = True
        yield from spin_up(ctx, plan.rotation_s)
        if beam_on_at_s is not None and protocol_series.breath_hold != "none":
            yield from wait_until(ctx, beam_on_at_s - HOLD_RAMP_S)
        hold = start_breath_hold(ctx, protocol_series.breath_hold)
        if hold is not None:
            yield Until(lambda: ctx.breathing.holding, HOLD_TIMEOUT_S)
        if beam_on_at_s is not None:
            yield from wait_until(ctx, beam_on_at_s)
            _report_lateness(ctx, series.label, ctx.clock.now_s - beam_on_at_s)
        ctx.kv, ctx.beam_on = plan.kv, True
        ctx.ma = _tube_current_ma(ctx, series)
        ctx.console.update_series(series_id, status="scanning", scanned_fraction=0.0, motion=False,
                                  started_at_s=ctx.clock.now_s)
        yield from sweep(ctx, long_end, plan.feed_mm_s, lambda f: _progress(ctx, series_id, f))
        motion = hold is not None and ctx.breathing.broke_hold
        finished = True
    finally:
        switch_everything_off(ctx, hold)
        if not finished:
            _count_stopped_sweep(ctx, series_id)
            _reset(ctx, series_id)
    if hold is not None:
        ctx.say(RELEASE_VOICE)
    _record(ctx, series_id, motion)
    if step is not None:
        step.committed = True
    try:
        yield from _reconstruct(ctx, series_id)
    finally:
        _finish_reconstructions(ctx, series_id)


def _report_lateness(ctx: CTContext, label: str, late_s: float) -> None:
    if late_s > LATE_REPORT_S:
        ctx.log.add("event", f"{label}: the scan started {late_s:.1f} s after its planned time "
                             "(table, rotor and breath-hold were not ready sooner)")


def _require_anatomy(ctx: CTContext, series: SeriesView) -> None:
    top, bottom = ctx.pack.data_range_mm
    start, end = ctx.body_z(series.plan.start_mm), ctx.body_z(series.plan.end_mm)
    if start < top or end > bottom:
        raise StepError(f"{series.label}: no anatomy data beyond {top - ctx.landmark_z_body_mm:.0f} mm or "
                        f"{bottom - ctx.landmark_z_body_mm:.0f} mm from the landmark")


def _register_enhancement(ctx: CTContext, series_id: str, fn: Optional[EnhancementAt]) -> None:
    if fn is not None:
        ctx.console.enhancement_at[series_id] = fn


def _tube_current_ma(ctx: CTContext, series: SeriesView) -> float:
    """Shown tube current: the effective mAs of the plan, scaled back by pitch and rotation time."""
    plan = series.plan
    mean_eff_mas = plan.ctdi_vol_mgy / ctx.spec.ctdi_mgy_per_100mas[str(plan.kv)] * 100.0
    return mean_eff_mas * plan.pitch / plan.rotation_s


def _progress(ctx: CTContext, series_id: str, fraction: float) -> None:
    ctx.console.update_series(series_id, scanned_fraction=fraction)


def _count_stopped_sweep(ctx: CTContext, series_id: str) -> None:
    """A sweep stopped part-way has exposed that part of the range: count it and say so."""
    series = ctx.console.find_series(series_id)
    if series.status != "scanning" or series.scanned_fraction <= 0:
        return
    delivered = series.plan.dlp_mgycm * series.scanned_fraction
    ctx.console.total_dlp_mgycm += delivered
    ctx.console.list_exposure(series.label, f"stopped after {series.scanned_fraction:.0%} of its range", delivered)
    ctx.log.add("alert", f"{series.label}: the scan was stopped after {series.scanned_fraction:.0%} of its range; "
                         f"{delivered:.0f} mGy·cm was delivered and is added to the dose total")


def _reset(ctx: CTContext, series_id: str) -> None:
    ctx.console.update_series(series_id, status="planned", scanned_fraction=0.0, started_at_s=None, motion=False)


def _record(ctx: CTContext, series_id: str, motion: bool) -> None:
    series = ctx.console.update_series(series_id, status="done", scanned_fraction=1.0, motion=motion)
    ctx.console.total_dlp_mgycm += series.plan.dlp_mgycm
    if motion:
        ctx.log.add("alert", f"{series.label}: the breath-hold broke during the scan; expect motion artefacts")


def _reconstruct(ctx: CTContext, series_id: str) -> Generator:
    """Wait for each reconstruction; they are rebuilt in parallel at `recon_images_per_s` images each."""
    rate = ctx.spec.recon_images_per_s
    waited = 0.0
    for index, recon in sorted(enumerate(ctx.console.find_series(series_id).recons),
                               key=lambda item: item[1].image_count):
        due = recon.image_count / rate
        yield Sleep(due - waited)
        waited = due
        _mark_ready(ctx, series_id, index)


def _mark_ready(ctx: CTContext, series_id: str, index: int) -> None:
    recons = list(ctx.console.find_series(series_id).recons)
    recons[index] = recons[index].model_copy(update={"ready": True})
    ctx.console.update_series(series_id, recons=recons)


def _finish_reconstructions(ctx: CTContext, series_id: str) -> None:
    """Every reconstruction of a scanned series ends up ready, also when the step was stopped while waiting."""
    recons = [r if r.ready else r.model_copy(update={"ready": True})
              for r in ctx.console.find_series(series_id).recons]
    ctx.console.update_series(series_id, recons=recons)


# ---- reconstruction geometry and images ----

def image_count(plane: str, start_mm: float, end_mm: float, fov_mm: float, increment_mm: float) -> int:
    """Axial images run from `start_mm` to `end_mm`; coronal and sagittal ones across the field of view."""
    extent = end_mm - start_mm if plane == "axial" else fov_mm
    return int(extent / increment_mm + 1e-9) + 1


def recon_views(ctx: CTContext, series_id: str, start_mm: float, end_mm: float, fov_mm: float) -> list[ReconView]:
    spec = next(s for s in ctx.protocol.series if s.id == series_id)
    return [ReconView(plane=r.plane, thickness_mm=r.thickness_mm, increment_mm=r.increment_mm, kernel=r.kernel,
                      image_count=image_count(r.plane, start_mm, end_mm, fov_mm, r.increment_mm), ready=False)
            for r in spec.recons]


def _find_recon(series: SeriesView, plane: str) -> ReconView:
    for recon in series.recons:
        if recon.plane == plane:
            return recon
    raise LookupError(f"{series.label} has no {plane} reconstruction")


def _image_time_s(series: SeriesView, plane: str, index: int, increment_mm: float) -> float:
    """When the image was scanned: along the run for an axial image, the middle of the run otherwise."""
    plan, started = series.plan, series.started_at_s or 0.0
    along = index * increment_mm / (plan.end_mm - plan.start_mm) if plane == "axial" else 0.5
    return started + along * plan.scan_time_s


def series_image(ctx: CTContext, series_id: str, plane: str, index: int) -> bytes:
    """PNG of one reconstructed image. A `StepError` says why an image is not available."""
    console = ctx.console
    series = console.find_series(series_id)
    recon = _find_recon(series, plane)
    if series.status != "done":
        raise StepError(f"{series.label} is not done: there are no images yet")
    if not recon.ready:
        raise StepError(f"The {plane} images of {series.label} are still being reconstructed")
    if not 0 <= index < recon.image_count:
        raise StepError(f"{plane} image {index} is out of range: {series.label} has images 0 to "
                        f"{recon.image_count - 1}")
    plan = series.plan
    fn = console.enhancement_at.get(series_id)
    enhancement = fn(_image_time_s(series, plane, index, recon.increment_mm)) if fn else None
    common = dict(fov_mm=plan.fov_mm, center_x_mm=plan.fov_center_x_mm, center_y_mm=plan.fov_center_y_mm,
                  enhancement=enhancement, thickness_mm=recon.thickness_mm)
    if plane == "axial":
        return render.axial_png(ctx.pack, ctx.body_z(plan.start_mm + index * recon.increment_mm), **common)
    return render.mpr_png(ctx.pack, plane, -plan.fov_mm / 2.0 + index * recon.increment_mm,
                          z_from_mm=ctx.body_z(plan.start_mm), z_to_mm=ctx.body_z(plan.end_mm), **common)
