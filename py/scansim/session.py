"""The exam session: the one object the outside world (the server, the tests) talks to.

A session owns the simulated clock, the scan room, the patient and the workflow. The outside world
reads `snapshot()`, sends actions through `dispatch()`, and moves simulated time with `advance()`.

Errors: an expected refusal (a `StepError` or `FieldError`, or an action that does not parse) comes back
as `ActionResult(ok=False, error=...)`. Anything else is a programming error and propagates.
"""
import copy
import itertools
import re
from pathlib import Path
from typing import Generator, Optional

import numpy as np
from pydantic import ValidationError

from scansim.actions import (Abort, ActionResult, ManualStart, Perform, SetField, SetReference, SetTimeScale,
                             parse_action)
from scansim.core import (EventLog, FieldError, Scheduler, SimClock, StepError, Tick)
from scansim.ct.console import ConsoleState
from scansim.ct.context import CTContext
from scansim.ct.workflow import build_ct_workflow
from scansim.ct.workflow_contrast import request_manual_start
from scansim.devices.injector import Injector
from scansim.patient.breathing import Breathing
from scansim.patient.contrast_pk import ContrastModel
from scansim.patient.pack import PatientPack
from scansim.patient.record import SETUP_STREAM, make_record, variation_seed
from scansim.protocols.library import load_library
from scansim.room.room import Room
from scansim.room.table import Table
from scansim.scanner_spec import load_scanner
from scansim.snapshot import (ClockView, CTScannerView, PoseView, ProtocolView,
                              Snapshot, SurfaceMark)

SCANNER_FILE = "siemens_somatom_force.json"
# Assumption: the injector module declares no default (research note 02 B). The page labels it "assumed".
PRESSURE_LIMIT_PSI = 325.0
IDLE_STEP_S = 0.5
TIME_SCALE_RANGE = (1.0, 50.0)
LOG_ENTRIES_SHOWN = 50
SURFACE_MARKS = (("sternal_notch", "Sternal notch"), ("xiphoid", "Xiphoid process"),
                 ("iliac_crest", "Iliac crest"))
_PATIENT_ID = re.compile(r"[A-Za-z0-9_-]+")
_session_numbers = itertools.count(1)


def _breathe(ctx: CTContext) -> Generator:
    """Background process: the patient breathes from the moment the session opens."""
    while True:
        dt = yield Tick()
        ctx.breathing.advance(dt)


class ExamSession:
    def __init__(self, ctx: CTContext, session_id: str) -> None:
        self.session_id = session_id
        self.ctx = ctx
        self.time_scale: float = 1.0
        self.workflow = build_ct_workflow(ctx)
        ctx.scheduler.start(_breathe(ctx), name="breathing")

    # ---- reading ----

    def snapshot(self) -> Snapshot:
        ctx = self.ctx
        started = ctx.injector.started_at_s
        return Snapshot(
            session_id=self.session_id, modality="CT", protocol=self._protocol_view(),
            patient=ctx.record.view(),
            clock=ClockView(sim_time_s=ctx.clock.now_s, time_scale=self.time_scale,
                            contrast_timer_s=None if started is None else ctx.clock.now_s - started),
            stages=self.workflow.views(ctx), active_step_id=self.workflow.active_step_id,
            busy_text=ctx.busy_text, room=ctx.room.view(),
            table=ctx.table.view(ctx.scan_plane_from_landmark_mm()), pose=self._pose_view(),
            scanner=self._scanner_view(), injector=ctx.injector.view(), console=ctx.console.view(ctx),
            log=ctx.log.tail(LOG_ENTRIES_SHOWN), show_reference=ctx.show_reference)

    def _protocol_view(self) -> ProtocolView:
        p = self.ctx.protocol
        return ProtocolView(id=p.id, title=p.title, modality=p.modality, region=p.region,
                            status=p.status, source_url=p.source.url)

    def _scanner_view(self) -> CTScannerView:
        c, s = self.ctx, self.ctx.spec
        return CTScannerView(model=s.model, tube_angle_deg=c.tube_angle_deg, rotor_rps=c.rotor_rps,
                             beam_on=c.beam_on, kv=c.kv, ma=c.ma, iso_height_mm=s.iso_height_mm,
                             laser_z_mm=s.laser_z_mm, front_clearance_mm=s.front_clearance_mm,
                             bore_diameter_mm=s.bore_diameter_mm)

    def _pose_view(self) -> PoseView:
        c, p = self.ctx, self.ctx.placement
        lying = c.pose_stage == "lying"
        marks = [SurfaceMark(name=name, label=label, z_body_mm=c.pack.landmarks[name])
                 for name, label in SURFACE_MARKS if lying and name in c.pack.landmarks]
        return PoseView(
            surface_marks=marks, stage=c.pose_stage, entry=c.entry, orientation=c.orientation, arms=c.arms,
            lateral_offset_mm=p.lateral_offset_mm if p else 0.0, yaw_deg=p.yaw_deg if p else 0.0,
            breath=c.breathing.value, holding=c.breathing.holding,
            anchor_t_mm=p.anchor_t_mm if p else c.anchor_t_mm(), stature_mm=c.pack.stature_mm,
            iv_connected=c.iv_connected)

    # ---- acting ----

    def dispatch(self, raw: dict) -> ActionResult:
        try:
            action = parse_action(raw)
        except ValidationError as err:
            return ActionResult(ok=False, error=_describe(err))
        try:
            self._apply(action)
        except (StepError, FieldError) as err:
            return ActionResult(ok=False, error=str(err))
        self._settle()
        return ActionResult(ok=True)

    def _apply(self, action) -> None:
        if isinstance(action, SetField):
            self._set_field(action)
        elif isinstance(action, Perform):
            self.workflow.perform(self._known(action.step_id)[0], self.ctx)
        elif isinstance(action, Abort):
            self.workflow.abort()
            self.ctx.auto_next = None
        elif isinstance(action, ManualStart):
            request_manual_start(self.ctx, self.workflow.active_step_id)
        elif isinstance(action, SetTimeScale):
            self._set_time_scale(action.value)
        elif isinstance(action, SetReference):
            self.ctx.show_reference = action.on

    def _set_field(self, action: SetField) -> None:
        step_id, key = self._known(action.step_id, action.key)
        # Check the value first on a copy, so a bad value is reported by field name and limits
        # even when the step cannot be edited yet, and the stored value is never touched.
        copy.copy(self.workflow.step(step_id).fields[key]).set(action.value)
        self.workflow.set_field(step_id, key, action.value)

    def _known(self, step_id: str, key: Optional[str] = None) -> tuple:
        try:
            step = self.workflow.step(step_id)
        except KeyError:
            raise StepError(f"Unknown step {step_id!r}") from None
        if key is not None and key not in step.fields:
            raise StepError(f'"{step.title}" has no field {key!r}')
        return (step_id,) if key is None else (step_id, key)

    def _set_time_scale(self, value: float) -> None:
        low, high = TIME_SCALE_RANGE
        if not low <= value <= high:
            raise StepError(f"Time scale must be between {low:g} and {high:g}")
        self.time_scale = float(value)

    # ---- time ----

    def advance(self, dt_s: float) -> None:
        """Move simulated time on, then start the step named in `auto_next` if nothing is running."""
        self.ctx.scheduler.advance(dt_s)
        self._run_auto_next()
        self._settle()

    def run_until_idle(self, max_s: float = 3600.0) -> None:
        elapsed = 0.0
        while (self.workflow.active_step_id is not None or self.ctx.auto_next) and elapsed < max_s:
            step_s = min(IDLE_STEP_S, max_s - elapsed)
            self.advance(step_s)
            elapsed += step_s

    def _run_auto_next(self) -> None:
        name = self.ctx.auto_next
        if not name or self.workflow.active_step_id is not None:
            return
        self.ctx.auto_next = None
        try:
            self.workflow.step(name)
        except KeyError:
            raise LookupError(f"auto_next names an unknown step: {name!r}") from None
        try:
            self.workflow.perform(name, self.ctx)
        except StepError as err:
            last = self.ctx.log.tail(1)
            if not last or last[0].text != str(err):      # a routine's own refusal is already logged
                self.ctx.log.add("alert", str(err))

    def _settle(self) -> None:
        if self.workflow.active_step_id is None:
            self.ctx.busy_text = None

    # ---- images (rendered on request; never part of the snapshot) ----

    def topogram_png(self, view: str) -> bytes:
        return self.ctx.console.topogram_png(self.ctx, view)

    def series_png(self, series_id: str, plane: str, index: int) -> bytes:
        return self.ctx.console.series_png(self.ctx, series_id, plane, index)

    def tracking_png(self) -> bytes:
        return self.ctx.console.tracking_png(self.ctx)


def _describe(err: ValidationError) -> str:
    first = err.errors()[0]
    where = ".".join(str(part) for part in first["loc"] if part != "type")
    return f"Invalid action{f' ({where})' if where else ''}: {first['msg']}"


def open_session(data_dir: Path, protocol_id: str, patient_id: str, seed: int = 0,
                 session_id: Optional[str] = None) -> ExamSession:
    data_dir = Path(data_dir)
    protocol = load_library(data_dir).get(protocol_id)
    if protocol is None:
        raise ValueError(f"Unknown protocol {protocol_id!r}")
    if not _PATIENT_ID.fullmatch(patient_id) or not (data_dir / "patients" / patient_id).is_dir():
        raise ValueError(f"Unknown patient {patient_id!r}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"The seed must be a whole number from 0 up, not {seed!r}")
    session_id = session_id or f"s{next(_session_numbers)}"
    pack = PatientPack.load(data_dir / "patients" / patient_id)
    record = make_record(pack, seed)
    clock = SimClock()
    log = EventLog(clock)
    spec = load_scanner(data_dir / "scanners" / SCANNER_FILE)
    ctx = CTContext(
        clock=clock, scheduler=Scheduler(clock, log), log=log, room=Room(), table=Table(spec.table),
        placement=None, pack=pack, record=record, breathing=Breathing(max_hold_s=record.max_hold_s),
        injector=Injector(clock, log, pressure_limit_psi=PRESSURE_LIMIT_PSI),
        contrast=ContrastModel(record.weight_kg, record.cardiac_output_l_min), spec=spec, protocol=protocol,
        console=ConsoleState(session_id),
        rng=np.random.default_rng(variation_seed(patient_id, seed, SETUP_STREAM)))
    return ExamSession(ctx, session_id)
