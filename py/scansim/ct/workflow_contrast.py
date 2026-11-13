"""The contrast phases: injection with bolus monitoring and the arterial scan, then the venous and delayed scans.

`inject_and_arterial` starts the injector as a process of its own, makes a monitoring scan every
`monitoring_interval_s` from `monitoring_delay_s` after the injection start, and starts the arterial scan
`post_trigger_delay_s` after the trigger. The venous and delayed scans follow by themselves (`ctx.auto_next`),
each timed to its own target beam-on time.

ASSUMPTIONS:
  - FALLBACK_VENOUS_S: with no trigger time the venous scan is timed from the injection start, 70 s
    (research note 02 section C: portal venous 60 to 75 s after the injection start).
  - The wait for a trigger or a manual start ends when the venous scan has to be prepared for that time
    (`_no_trigger_deadline_s`), even if `max_monitoring_s` has not run out: otherwise the venous scan, which
    cannot be repeated either, would be late as well. With the default protocol that is about 57 s after the
    injection start, 13 s before monitoring's own limit.
  - MANUAL_WINDOW_S: when monitoring runs out before that moment, the operator has up to 60 s (and no longer
    than that moment) to start the scan by hand before the arterial phase counts as missed; research note 02
    section C says a written fallback rule is UNCONFIRMED.
  - CHAIN_SLACK_S: the next scan of the chain starts on the session's next tick, which the server keeps to at
    most 2 simulated seconds.
  - `max_monitoring_s` is counted from the first monitoring scan.
Monitoring scans are not added to the dose total (research note 02 section C: per-image CTDIvol UNCONFIRMED).
"""
from typing import Generator, Optional

import numpy as np

from scansim.core.process import ProcessHandle
from scansim.core.steps import Step, StepError
from scansim.ct.acquisition import (acquire_series, preflight_series, prep_lead_s, spin_up,
                                    switch_everything_off, wait_until)
from scansim.ct.context import CTContext
from scansim.ct.step_factory import make_step
from scansim.ct.workflow_aftercare import aftercare_steps
from scansim.ct.workflow_review import review_steps
from scansim.ct.workflow_tracking import arterial_plan, measure_region_hu, monitoring_rotation
from scansim.patient.contrast_pk import COMPARTMENTS
from scansim.protocols.schema import ContrastTiming, SeriesSpec
from scansim.snapshot import TrackingSample

MANUAL_WINDOW_S = 60.0
FALLBACK_VENOUS_S = 70.0
CHAIN_SLACK_S = 2.0
STALE_TARGET_S = 1.0
STILL_POSSIBLE = "the venous and delayed scans can still be done: start the venous scan by hand"
INJECT_STEP = "inject_and_arterial"
MONITORING_STATES = ("monitoring", "manual")


# ---- shared helpers ----

def enhancement_function(ctx: CTContext):
    """`fn(sim_time_s)`: added HU in every compartment at that time, from the contrast model."""
    def at(time_s: float) -> dict[str, float]:
        when = np.asarray(time_s)
        return {name: float(ctx.contrast.curve(name, when)[()]) for name in COMPARTMENTS}
    return at


def _timing(ctx: CTContext) -> ContrastTiming:
    contrast = ctx.protocol.contrast
    if contrast is None or contrast.timing.method != "bolus_tracking":
        raise StepError("This protocol does not use bolus tracking")
    return contrast.timing


def stop_injection(ctx: CTContext, handle: Optional[ProcessHandle] = None) -> None:
    """Stop an injection that is still running and end its process."""
    if ctx.injector.state == "injecting":
        ctx.injector.stop()
    if handle is not None and not handle.done:
        ctx.scheduler.cancel(handle)


def request_manual_start(ctx: CTContext, active_step_id: Optional[str]) -> None:
    """The `manual_start` action: start the arterial scan now, while bolus monitoring is waiting or running."""
    tracking = ctx.console.tracking
    if active_step_id != INJECT_STEP or tracking is None or tracking.state not in MONITORING_STATES:
        raise StepError("Nothing to start manually: manual start works while bolus monitoring is running")
    ctx.manual_start_requested = True


# ---- inject_and_arterial ----

def _inject_blockers(ctx: CTContext, step: Step) -> list[str]:
    reasons = []
    if ctx.injector.state != "armed":
        reasons.append(f"The injector must be armed (it is {ctx.injector.state})")
    tracking = ctx.console.tracking
    if tracking is None or tracking.baseline_hu is None:
        reasons.append("Place the region on the vessel first: monitoring needs its baseline")
    return reasons


def _monitoring_scan(ctx: CTContext, rotation_s: float, started_s: float, fn) -> Generator:
    """One rotation; returns the region's mean HU, measured at the middle of the rotation."""
    ctx.room.warning_light_on = True
    started = ctx.clock.now_s
    yield from monitoring_rotation(ctx, rotation_s)
    tracking = ctx.console.tracking
    scanned_at = started + rotation_s / 2.0
    hu = measure_region_hu(ctx, tracking, fn(scanned_at))
    ctx.console.add_monitoring_sample(TrackingSample(t_s=scanned_at - started_s, hu=hu), scanned_at)
    return hu


def _no_trigger_deadline_s(ctx: CTContext, started_s: float) -> float:
    """When waiting for a trigger must end, so that the venous scan can still start at its fallback time.

    Worked out with the table at the monitoring level and the rotor taken as stopped, which is how the
    venous step finds them when the arterial phase is lost."""
    lead = prep_lead_s(ctx, "venous", rotor_stopped=True)
    return started_s + FALLBACK_VENOUS_S - lead - CHAIN_SLACK_S


def _monitor(ctx: CTContext, started_s: float, timing: ContrastTiming, rotation_s: float, fn,
             deadline_s: float) -> Generator:
    """Monitor until the trigger, a manual start, the maximum time or the deadline; returns "triggered",
    "manual" or "timeout"."""
    tracking = ctx.console.tracking
    level = tracking.baseline_hu + tracking.threshold_hu
    first = started_s + timing.monitoring_delay_s
    end = min(first + timing.max_monitoring_s, deadline_s)
    manual = lambda: ctx.manual_start_requested
    count = 0
    while True:
        due = first + count * timing.monitoring_interval_s
        yield from wait_until(ctx, min(due, end), stop=manual)
        if ctx.manual_start_requested:
            return "manual"
        if due >= end - 1e-9:
            return "timeout"
        if (yield from _monitoring_scan(ctx, rotation_s, started_s, fn)) >= level:
            return "triggered"
        count += 1


def _no_trigger(ctx: CTContext, monitored_s: float, deadline_s: float) -> Generator:
    """Monitoring has ended without a trigger: stop it and, if there is still time before the venous scan
    must be prepared, let the operator start the arterial scan by hand; returns whether they did."""
    switch_everything_off(ctx, None)
    window = min(MANUAL_WINDOW_S, deadline_s - ctx.clock.now_s)
    if window <= 0:
        ctx.log.add("alert", f"No trigger after {monitored_s:.0f} s of monitoring: monitoring stopped, because the "
                             f"venous scan must be prepared now to start {FALLBACK_VENOUS_S:g} s after the "
                             "injection start")
        return False
    ctx.console.update_tracking(state="manual")
    ctx.log.add("alert", f"No trigger after {monitored_s:.0f} s of monitoring: monitoring stopped. "
                         f"Start the arterial scan by hand within {window:.0f} s or the phase is lost")
    yield from wait_until(ctx, ctx.clock.now_s + window, stop=lambda: ctx.manual_start_requested)
    return ctx.manual_start_requested


def _lose_arterial_phase(ctx: CTContext, step: Step) -> None:
    ctx.console.update_tracking(state="missed")
    ctx.console.update_series("arterial", status="missed")
    ctx.log.add("alert", "No trigger and no manual start: the arterial phase is missed and cannot be repeated "
                         "without a new injection; the venous scan follows at its time from the injection start")
    step.add_result("Arterial", "Missed: no trigger and no manual start", alert=True)


def _end_tracking_after_abort(ctx: CTContext) -> None:
    """After a stop the contrast is in the patient and cannot be given again, so an arterial scan that has not
    happened is lost: the series and the tracking both say so. A trigger time, if there was one, stays."""
    tracking = ctx.console.tracking
    if tracking is None or ctx.console.find_series("arterial").status == "done":
        return
    if tracking.state in MONITORING_STATES:
        reason = "The injection was stopped before the arterial scan"
    elif tracking.state == "triggered":
        reason = "The arterial scan was aborted after the trigger"
    else:
        return
    ctx.console.update_tracking(state="missed")
    ctx.console.update_series("arterial", status="missed")
    ctx.log.add("alert", f"{reason}: the phase is lost and cannot be repeated without a new injection; "
                         f"{STILL_POSSIBLE}")


def _inject_and_arterial(ctx: CTContext, step: Step) -> Generator:
    timing = _timing(ctx)
    preflight_series(ctx, "arterial")          # refuse before any contrast is given
    plan = arterial_plan(ctx)
    fn = enhancement_function(ctx)
    ctx.console.tracking_enhancement_at = fn
    ctx.manual_start_requested = False
    handle, finished = None, False
    try:
        handle = ctx.scheduler.start(ctx.injector.run(
            lambda seg: ctx.contrast.add_segment(seg), lambda at_s: ctx.contrast.end_delivery_at(at_s)),
            name="injector")
        started_s = ctx.injector.started_at_s
        ctx.console.update_tracking(state="monitoring", samples=[], triggered_at_s=None)
        yield from ctx.table.move_long(ctx.long_for(ctx.console.tracking.slice_mm))
        deadline_s = _no_trigger_deadline_s(ctx, started_s)
        yield from spin_up(ctx, plan.rotation_s)
        outcome = yield from _monitor(ctx, started_s, timing, plan.rotation_s, fn, deadline_s)
        monitored_s = max(0.0, ctx.clock.now_s - (started_s + timing.monitoring_delay_s))
        if outcome == "timeout" and not (yield from _no_trigger(ctx, monitored_s, deadline_s)):
            _lose_arterial_phase(ctx, step)
        else:
            yield from _arterial(ctx, step, timing, started_s, outcome, fn)
        finished = True
    finally:
        ctx.manual_start_requested = False
        if not finished:
            stop_injection(ctx, handle)
            _end_tracking_after_abort(ctx)
        switch_everything_off(ctx, None)
    ctx.auto_next = "scan_venous"


def _arterial(ctx: CTContext, step: Step, timing: ContrastTiming, started_s: float, outcome: str,
              fn) -> Generator:
    now = ctx.clock.now_s
    ctx.console.update_tracking(state="triggered", triggered_at_s=now)
    how = "Manual start" if outcome != "triggered" else "Trigger"
    step.add_result(how, f"{now - started_s:.1f} s after the injection start")
    if outcome != "triggered":
        ctx.log.add("event", "Arterial scan started by hand")
    yield from acquire_series(ctx, "arterial", fn, beam_on_at_s=now + timing.post_trigger_delay_s, step=step)
    scan = ctx.console.find_series("arterial")
    step.add_result("Arterial scan", f"beam on {scan.started_at_s - now:.1f} s after the trigger")


# ---- venous and delayed ----

def scan_target_s(ctx: CTContext, spec: SeriesSpec) -> float:
    """Simulation time at which a series' beam should come on."""
    injection_start = ctx.injector.started_at_s
    if injection_start is None:
        raise StepError("The injection has not started yet")
    tracking = ctx.console.tracking
    if spec.timing.type == "after_injection_start":
        return injection_start + spec.timing.delay_s
    if tracking is not None and tracking.triggered_at_s is not None:
        target = tracking.triggered_at_s + spec.timing.delay_s
        if target < ctx.clock.now_s - STALE_TARGET_S:
            ctx.log.add("alert", f"{spec.label}: the planned time (trigger + {spec.timing.delay_s:g} s) was "
                                 f"{ctx.clock.now_s - target:.0f} s ago; the scan starts as soon as it is ready")
        return target
    ctx.log.add("alert", f"{spec.label}: there was no trigger, so the scan is timed from the injection start "
                         f"instead ({FALLBACK_VENOUS_S:g} s)")
    return injection_start + FALLBACK_VENOUS_S


def _later_scan(series_id: str, next_step: Optional[str]):
    def routine(ctx: CTContext, step: Step) -> Generator:
        spec = next(s for s in ctx.protocol.series if s.id == series_id)
        target = scan_target_s(ctx, spec)
        finished = False
        try:
            yield from acquire_series(ctx, series_id, enhancement_function(ctx), beam_on_at_s=target, step=step)
            finished = True
        finally:
            if not finished:
                stop_injection(ctx)
        scan = ctx.console.find_series(series_id)
        step.add_result("Beam on", f"{scan.started_at_s - ctx.injector.started_at_s:.0f} s after the injection start")
        ctx.auto_next = next_step
    return routine


def _injection_started(ctx: CTContext, step: Step) -> list[str]:
    return [] if ctx.injector.started_at_s is not None else ["The injection has not started yet"]


def contrast_steps(ctx: CTContext) -> list[Step]:
    """Contrast phases, then the review and aftercare stages. None of them can be done twice (the contrast is
    given once, the patient leaves once), so repeating an earlier step never sends them back to "redo"."""
    steps = _contrast_and_later_steps(ctx)
    for step in steps:
        step.irreversible = True
    return steps


def _contrast_and_later_steps(ctx: CTContext) -> list[Step]:
    return [
        make_step(INJECT_STEP, "The injector starts and the contrast timer with it; low-dose monitoring scans "
                  "watch the region and the arterial scan starts by itself after the trigger plus the "
                  "post-trigger delay. Manual start overrides the trigger (note 01, CARE Bolus). Monitoring scans "
                  "are not added to the dose total.", _inject_and_arterial, check=_inject_blockers),
        make_step("scan_venous", "The venous scan is timed from the trigger (55 s here), so preparation starts "
                  "early enough for the beam to come on at that moment; without a trigger it is timed from the "
                  f"injection start ({FALLBACK_VENOUS_S:g} s, an assumption within note 02 section C's 60 to 75 s), "
                  "and waiting for a trigger ends in time for that.", _later_scan("venous", "scan_delayed"),
                  requires=("arm_injector",), check=_injection_started),
        make_step("scan_delayed", "The delayed scan is timed from the injection start (4 minutes here; "
                  "the usual range is 2 to 5 minutes, note 02 section C).", _later_scan("delayed", None),
                  requires=("scan_venous",), check=_injection_started),
        *review_steps(ctx),
        *aftercare_steps(ctx),
    ]
