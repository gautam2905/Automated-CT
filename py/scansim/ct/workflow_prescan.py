"""The first eighteen steps of the exam: from the order arriving to the technologist leaving the room.

Each step is one small routine plus one entry in `prescan_steps`. Routines check what can refuse the
step first (a refusal costs no time and changes nothing), then spend paperwork time, then act. The
pre-filled fields are in prescan_fields.py.

ASSUMPTIONS (research note 02 section A found no sourced durations for any of these):
  - PAPERWORK_JUMP_S: the simulated seconds each paperwork step takes (the brief's values);
  - PATIENT_ON_TABLE_STAGES (25 s in all) and CENTRING_S (5 s);
  - the largest placement offset and yaw the patient arrives with (25 mm and 3 degrees, the brief's values).
"""
from contextlib import contextmanager
from dataclasses import replace
from typing import Generator, Iterator

from scansim.core.fields import Field
from scansim.core.process import Sleep, Tick
from scansim.core.steps import Step, StepError
from scansim.ct import prescan_fields as fields
from scansim.ct.context import CTContext, ReadOnlyField
from scansim.ct.prescan_fields import MIN_PHASE_ML, POSITIONS, TEST_VOLUME_ML, saline_needed_ml
from scansim.ct.repeat_rules import before_injection
from scansim.examples import _STAGES as _SAMPLE_STAGES
from scansim.patient.contrast_pk import ContrastModel
from scansim.patient.record import (REFERENCE_BSA_M2, REFERENCE_CARDIAC_OUTPUT_L_MIN,
                                    body_surface_area_m2)
from scansim.room.placement import Placement

PAPERWORK_JUMP_S = {
    "order_received": 0.0, "protocol_assigned": 120.0, "chart_check": 120.0, "identify_patient": 60.0,
    "safety_screening": 120.0, "consent": 120.0, "change_clothes": 300.0, "iv_access": 300.0,
    "breath_coaching": 60.0, "register_patient": 90.0, "load_injector": 180.0, "leave_room": 20.0,
}
PATIENT_ON_TABLE_STAGES = (("entering", 10.0), ("standing", 5.0), ("sitting", 10.0))
CENTRING_S = 5.0
MAX_OFFSET_MM = 25.0
MAX_YAW_DEG = 3.0
EGFR_ALERT_BELOW = 30.0       # ACR Manual on Contrast Media, research note 02 section A
PATIENT_GONE = "The patient is not on the table, so there is nothing to position"

# ---- titles shared with the sample snapshot, so the live exam and the sample agree ----

_SAMPLE_STEPS = {step[0]: (stage_id, *step[1:]) for stage_id, _, steps in _SAMPLE_STAGES for step in steps}
STAGE_TITLES = {stage_id: title for stage_id, title, _ in _SAMPLE_STAGES}


def sample_step(step_id: str) -> tuple:
    """(stage_id, title, actor, place, info) of a step as the sample snapshot lists it."""
    return _SAMPLE_STEPS[step_id]


def _step(step_id: str, actor: str, place: str, routine, info: str, fields=(), **kwargs) -> Step:
    stage_id, title = sample_step(step_id)[:2]
    return Step(step_id, stage_id, title, actor=actor, place=place, info=info, fields=fields,
                routine=routine, **kwargs)


def _arrive(ctx: CTContext, where: str) -> None:
    ctx.room.technologist_at = where


def _to_gantry(ctx: CTContext) -> None:
    ctx.room.technologist_at = "gantry"
    ctx.room.door_open = True


@contextmanager
def _at_gantry(ctx: CTContext) -> Iterator[None]:
    """The technologist goes to the gantry for a step. If the step does not finish (refused or stopped),
    the room is left as it was: a repeat that fails must not leave the door open behind a done "Leave room"."""
    before = (ctx.room.technologist_at, ctx.room.door_open)
    _to_gantry(ctx)
    try:
        yield
    except BaseException:
        ctx.room.technologist_at, ctx.room.door_open = before
        raise


def _paperwork(ctx: CTContext, step: Step) -> None:
    ctx.jump(PAPERWORK_JUMP_S[step.id])


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise StepError(message)


# ---- request ----

def _order_received(ctx: CTContext, step: Step) -> None:
    _paperwork(ctx, step)
    step.add_result("Indication", step.value("indication"))


def _protocol_assigned(ctx: CTContext, step: Step) -> None:
    _paperwork(ctx, step)
    step.add_result("Protocol", ctx.protocol.title)


def _chart_check(ctx: CTContext, step: Step) -> None:
    _arrive(ctx, "reception")
    _paperwork(ctx, step)
    egfr = step.value("egfr")
    low = egfr < EGFR_ALERT_BELOW
    step.add_result("eGFR", f"{egfr:g} mL/min/1.73 m2" + (" (under 30: ask the radiologist)" if low else ""),
                    alert=low)
    if step.value("prior_reaction"):
        step.add_result("Prior contrast reaction", "Yes: the radiologist decides on premedication", alert=True)
    if step.value("on_metformin"):
        step.add_result("Metformin", "Yes: check the eGFR rule before contrast", alert=True)


# ---- arrival and screening ----

def _identify_patient(ctx: CTContext, step: Step) -> None:
    _require(step.value("name_confirmed") and step.value("dob_confirmed"),
             "Confirm both the name and the date of birth against the order before going on")
    _arrive(ctx, "reception")
    _paperwork(ctx, step)
    step.add_result("Identity", "Name and date of birth match the order")


def _safety_screening(ctx: CTContext, step: Step) -> None:
    _require(step.value("pregnancy") != "yes", "Pregnancy reported: radiologist review required")
    _arrive(ctx, "preparation")
    _paperwork(ctx, step)
    step.add_result("Allergy", "Reported: tell the radiologist" if step.value("allergy") else "None reported",
                    alert=step.value("allergy"))


def _consent(ctx: CTContext, step: Step) -> None:
    _require(step.value("consent_given"), "Consent has not been given; do not go on without it")
    _arrive(ctx, "preparation")
    _paperwork(ctx, step)


def _change_clothes(ctx: CTContext, step: Step) -> None:
    _arrive(ctx, "preparation")
    _paperwork(ctx, step)
    removed = step.value("metal_removed")
    step.add_result("Metal", "Removed" if removed else "Still on: it will show in the images", alert=not removed)


def _iv_access(ctx: CTContext, step: Step) -> None:
    _require(step.value("flush_ok"), "The cannula does not flush: choose another site and start again")
    _arrive(ctx, "preparation")
    _paperwork(ctx, step)
    gauge = step.value("gauge")
    ctx.record = replace(ctx.record, iv_gauge=gauge)
    accepted = ctx.protocol.contrast.iv_gauges if ctx.protocol.contrast else []
    off_list = bool(accepted) and gauge not in accepted
    step.add_result("Cannula", f"{gauge}, {step.value('site').replace('_', ' ')}")
    if off_list:
        step.add_result("Protocol", f"The protocol accepts {' or '.join(accepted)}; {gauge} limits the flow rate",
                        alert=True)


def _breath_coaching(ctx: CTContext, step: Step) -> None:
    _arrive(ctx, "preparation")
    ctx.say("Breathe in, hold your breath, and breathe out when I say")
    _paperwork(ctx, step)


# ---- preparation ----

def _cardiac_output_l_min(height_cm: float, weight_kg: float) -> float:
    bsa = body_surface_area_m2(height_cm, weight_kg)
    return REFERENCE_CARDIAC_OUTPUT_L_MIN * bsa / REFERENCE_BSA_M2


def _register_patient(ctx: CTContext, step: Step) -> None:
    _arrive(ctx, "console")
    _paperwork(ctx, step)
    height, weight = step.value("height_cm"), step.value("weight_kg")
    entry, orientation, _ = POSITIONS[step.value("patient_position")]
    changed = {"height_cm": height != round(ctx.record.height_cm, 1), "weight_kg": weight != round(ctx.record.weight_kg, 1)}
    estimated = [f for f in ctx.record.estimated_fields if not changed.get(f, False)]
    cardiac_output = _cardiac_output_l_min(height, weight)
    ctx.record = replace(ctx.record, height_cm=height, weight_kg=weight, estimated_fields=estimated,
                         cardiac_output_l_min=cardiac_output)
    ctx.contrast = ContrastModel(weight, cardiac_output)
    ctx.entry, ctx.orientation = entry, orientation
    step.add_result("Position", POSITIONS[step.value("patient_position")][2])


def _load_injector(ctx: CTContext, step: Step) -> None:
    """The injector is loaded once and cannot be reloaded, so volumes the exam cannot be finished with are
    refused here, with the reason, and not later when nothing can be done about them."""
    contrast = ctx.protocol.contrast
    _require(contrast is not None, "This protocol gives no contrast, so there is nothing to load")
    loaded, saline, needed = step.value("contrast_ml"), step.value("saline_ml"), saline_needed_ml(ctx)
    _require(loaded >= MIN_PHASE_ML, f"Load some contrast (at least {MIN_PHASE_ML:g} mL): the injector cannot be "
             "armed with an empty contrast syringe, and it cannot be loaded again later")
    _require(saline >= needed, f"Load at least {needed:g} mL of saline: the {contrast.saline_ml:g} mL chaser and "
             f"the {TEST_VOLUME_ML:g} mL test flush both come from this syringe, and it cannot be loaded again "
             f"later ({saline:g} mL is not enough)")
    _require(step.value("purged"), "Purge the injector of air before it is connected to the patient")
    _to_gantry(ctx)
    _paperwork(ctx, step)
    ctx.injector.load(loaded, saline, contrast.concentration_mgi_ml)
    ctx.injector.purge()
    step.add_result("Loaded", f"{loaded:g} mL contrast, {saline:g} mL saline")


def _prepare_table(ctx: CTContext, step: Step) -> Generator:
    _to_gantry(ctx)
    yield from ctx.table.move_height(step.value("loading_height_mm"))


# ---- positioning ----

def _patient_on_table(ctx: CTContext, step: Step) -> Generator:
    _to_gantry(ctx)
    arms, lying = step.value("arms"), False
    try:
        for stage, seconds in PATIENT_ON_TABLE_STAGES:
            ctx.pose_stage = stage
            yield Sleep(seconds)
        ctx.arms = arms
        ctx.placement = Placement(
            entry=ctx.entry, orientation=ctx.orientation, arms=arms, anchor_t_mm=ctx.anchor_t_mm(),
            stature_mm=ctx.pack.stature_mm,
            lateral_offset_mm=float(ctx.rng.uniform(-MAX_OFFSET_MM, MAX_OFFSET_MM)),
            yaw_deg=float(ctx.rng.uniform(-MAX_YAW_DEG, MAX_YAW_DEG)))
        ctx.pose_stage, lying = "lying", True
    finally:
        if not lying:
            ctx.pose_stage = "away"


def _centre_patient(ctx: CTContext, step: Step) -> Generator:
    placement = ctx.placement
    offset, yaw = placement.lateral_offset_mm, placement.yaw_deg
    elapsed = 0.0
    while elapsed < CENTRING_S:
        elapsed += yield Tick()
        remaining = max(0.0, 1.0 - elapsed / CENTRING_S)
        placement.lateral_offset_mm, placement.yaw_deg = offset * remaining, yaw * remaining
    placement.lateral_offset_mm = placement.yaw_deg = 0.0
    side = "left" if offset > 0 else "right"
    step.add_result("Corrected", f"{abs(offset):.0f} mm to the patient's {side} and {abs(yaw):.1f} degrees of turn")


def _connect_injector(ctx: CTContext, step: Step) -> Generator:
    volume = step.value("test_volume_ml")
    loaded = ctx.injector.view().saline_ml
    _require(volume <= loaded, f"Test injection of {volume:g} mL needs saline: only {loaded:g} mL is loaded")
    if ctx.injector.state == "purged":      # after an abort the line is already connected: retry the test only
        ctx.injector.connect(ctx.record.iv_gauge)
    peak = yield from ctx.injector.test_inject(volume)
    limit = ctx.injector.view().pressure_limit_psi
    step.add_result("Test injection", f"{volume:g} mL saline, peak {peak:.0f} psi (limit {limit:g} psi); the "
                    "pressure model and its limit are assumed", alert=peak >= limit)
    ctx.iv_connected = True


def _table_height(ctx: CTContext, step: Step) -> Generator:
    _require(ctx.placement is not None, PATIENT_GONE)
    height, low = step.value("height_mm"), ctx.spec.table.height_min_in_bore_mm
    with _at_gantry(ctx):
        yield from ctx.table.move_height(height)
    if height < low:
        step.add_result("Check", f"At {height:.0f} mm the table cannot enter the bore: raise it to at least "
                                 f"{low:.0f} mm (do this step again) before the landmark is set", alert=True)


def _set_landmark(ctx: CTContext, step: Step) -> Generator:
    _require(ctx.placement is not None, PATIENT_GONE)
    distance = step.value("distance_from_head_mm")
    with _at_gantry(ctx):
        ctx.room.lasers_on = True
        try:
            target = ctx.placement.long_for_body_at(distance, ctx.spec.laser_z_mm, ctx.spec.front_clearance_mm)
            yield from ctx.table.move_long(target)
            ctx.table.set_zero()
            _set_frame(ctx, distance)
        finally:
            ctx.room.lasers_on = False
    step.add_result("Zero set", f"{step.value('landmark')}, {distance:.0f} mm below the top of the head")


def _set_frame(ctx: CTContext, distance: float) -> None:
    """Store the landmark all later positions are measured from. When it replaces an earlier one, what was
    made in the old frame is dropped (the console keeps scanned series in their place in the body)."""
    earlier = ctx.landmark_z_body_mm
    ctx.landmark_z_body_mm = distance
    if earlier is not None:
        ctx.console.landmark_moved(earlier - distance)


def _leave_room(ctx: CTContext, step: Step) -> None:
    _paperwork(ctx, step)
    ctx.room.technologist_at = "console"
    ctx.room.door_open = False
    ctx.room.lasers_on = False


# ---- the steps ----

def _request_and_arrival_steps(ctx: CTContext) -> list[Step]:
    flag = fields.flag
    return [
        _step("order_received", "radiologist", "reception", _order_received,
              "The referring clinician's order arrives with the clinical question and the exam wanted.",
              [Field("indication", "Indication", "text", ctx.protocol.indication, source="protocol")]),
        _step("protocol_assigned", "radiologist", "reception", _protocol_assigned,
              "The radiologist chooses the protocol that answers the question: phases, contrast and coverage.",
              [ReadOnlyField("protocol", "Protocol", "text", ctx.protocol.title, source="protocol")]),
        _step("chart_check", "technologist", "reception", _chart_check,
              "Kidney function is checked before contrast; eGFR 30 mL/min/1.73 m2 is the threshold with "
              "the most evidence (ACR Manual on Contrast Media).", fields.chart_fields(ctx)),
        _step("identify_patient", "technologist", "reception", _identify_patient,
              "The patient is identified with two identifiers, name and date of birth, against the order.",
              [flag("name_confirmed", "Name confirmed", True, "assumption"),
               flag("dob_confirmed", "Date of birth confirmed", True, "assumption")]),
        _step("safety_screening", "technologist", "preparation", _safety_screening,
              "Ask about allergies and previous contrast reactions; a prior reaction to the same class is "
              "the strongest predictor of another (ACR 2026).", fields.screening_fields(ctx)),
        _step("consent", "technologist", "preparation", _consent,
              "The patient is told about the scan and the contrast and agrees. Whether written consent is "
              "needed for routine IV contrast is not settled in the sources.",
              [flag("consent_given", "Consent given", True, "assumption")]),
        _step("change_clothes", "patient", "preparation", _change_clothes,
              "Metal in the scan range is removed and the patient changes into a gown.",
              [flag("metal_removed", "Metal removed", True, "assumption")]),
        _step("iv_access", "nurse", "preparation", _iv_access,
              "A plastic cannula, 20 gauge or larger for fast injection, goes into an antecubital or large "
              "forearm vein and is flushed with saline to prove it is patent (ACR 2026).", fields.iv_fields(ctx)),
        _step("breath_coaching", "technologist", "preparation", _breath_coaching,
              "Practise the breath-hold now so the commands in the scan room are familiar."),
    ]


def _preparation_and_positioning_steps(ctx: CTContext) -> list[Step]:
    pos = fields.positioning_fields(ctx)
    return [
        _step("register_patient", "technologist", "console", _register_patient,
              "Patient data comes from the worklist or is entered by hand, then the protocol is chosen "
              "(Siemens note 01, A1).", fields.register_fields(ctx)),
        _step("load_injector", "technologist", "scan_room", _load_injector,
              "Fill the contrast and saline syringes and clear the syringe and tubing of air; air embolism "
              "is rare but can be fatal (ACR 2026). The injector is loaded once for the exam.",
              fields.injector_fields(ctx)),
        _step("prepare_table", "technologist", "scan_room", _prepare_table,
              "Lower the table, cover it and lay out the arm and knee supports.", fields.table_fields(ctx)),
        _step("patient_on_table", "technologist", "scan_room", _patient_on_table,
              "The patient climbs on and lies as the protocol says; for the liver that is supine, "
              "feet first, arms above the head (AAPM).", pos["patient_on_table"]),
        _step("centre_patient", "technologist", "scan_room", _centre_patient,
              "Centre the patient in the gantry; mis-centring is common and affects dose and noise "
              "(research note 02, F)."),
        _step("connect_injector", "technologist", "scan_room", _connect_injector,
              "Connect the line to the cannula and give a saline test flush; stop and re-site if the patient "
              "feels pain or the site swells (ACR 2026).", pos["connect_injector"]),
        _step("table_height", "technologist", "scan_room", _table_height,
              "Raise the table to the isocentre so the dose modulation works as intended.",
              pos["table_height"], repeatable=True, invalidates=("set_landmark",), check=before_injection),
        # Doing this again means going back into the room, so "Leave room" must be done again as well.
        _step("set_landmark", "technologist", "scan_room", _set_landmark,
              "Switch the lasers on, put the light on the landmark and zero the table there; all later "
              "ranges are measured from it (Siemens note 01, A2). Setting it again drops the topograms and "
              "plans made from the old one.", pos["set_landmark"], repeatable=True,
              invalidates=("leave_room", "topogram_ap", "topogram_lat"), check=before_injection),
        _step("leave_room", "technologist", "scan_room", _leave_room,
              "Switch off the lasers, leave the room and close the door; the patient is watched through the "
              "window and spoken to by intercom (Siemens note 01, A4)."),
    ]


def prescan_steps(ctx: CTContext) -> list[Step]:
    """The eighteen steps up to leaving the room; each requires the one before unless stated."""
    return [*_request_and_arrival_steps(ctx), *_preparation_and_positioning_steps(ctx)]
