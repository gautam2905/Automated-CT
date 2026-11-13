"""Aftercare: table out, disconnect, patient off the table, observation, room turnaround, close.

ASSUMPTIONS (research note 02 section I: the disconnecting sequence, the site inspection and the room
turnaround time for multiphase liver CT are all UNCONFIRMED):
  - AFTERCARE_JUMP_S: 30 s to disconnect the line and inspect the site, 180 s to turn the room round (the
    brief's value for the room);
  - PATIENT_OFF_TABLE_STAGES: 25 s in all, the arrival stages in reverse;
  - `observe_min` defaults to 15 minutes with the cannula left in: note 02 section I gives 15 minutes routinely
    for low-risk patients and 30 for high-risk, and most reactions begin within 20 minutes.
"""
from typing import Generator

from scansim.core.fields import Field
from scansim.core.process import Sleep
from scansim.core.steps import Step
from scansim.ct.context import CTContext
from scansim.ct.step_factory import make_step
from scansim.ct.scan_fields import number_field

AFTERCARE_JUMP_S = {"disconnect_injector": 30.0, "room_turnaround": 180.0}
PATIENT_OFF_TABLE_STAGES = (("sitting", 10.0), ("standing", 5.0), ("leaving", 10.0))
OBSERVE_DEFAULT_MIN = 15.0
OBSERVE_MAX_MIN = 120.0
SECONDS_PER_MIN = 60.0
SITE_ADVICE = ("Pain or swelling at the site: stop, examine the arm, raise it above the heart and cool it, and "
               "tell the radiologist (ACR Manual on Contrast Media, extravasation)")
AFTER_CARE_ADVICE = ("Drink plenty of fluids; a rash can appear from 30 minutes up to a week later and usually "
                     "settles by itself (ACR Manual on Contrast Media)")


def _table_out(ctx: CTContext, step: Step) -> Generator:
    ctx.room.warning_light_on = False
    ctx.room.technologist_at = "gantry"
    ctx.room.door_open = True
    yield from ctx.table.move_long(0.0)
    yield from ctx.table.move_height(ctx.spec.table.height_min_mm)


def _disconnect_injector(ctx: CTContext, step: Step) -> None:
    ctx.jump(AFTERCARE_JUMP_S[step.id])
    ctx.iv_connected = False
    step.add_result("Line", "Disconnected; the cannula stays in for the observation period")
    if not step.value("site_ok"):
        step.add_result("Site", SITE_ADVICE, alert=True)


def _patient_off_table(ctx: CTContext, step: Step) -> Generator:
    left = False
    try:
        for stage, seconds in PATIENT_OFF_TABLE_STAGES:
            ctx.pose_stage = stage
            yield Sleep(seconds)
        ctx.pose_stage, ctx.placement, left = "away", None, True
    finally:
        if not left:
            ctx.pose_stage = "lying"


def _post_contrast_care(ctx: CTContext, step: Step) -> None:
    minutes = step.value("observe_min")
    ctx.jump(minutes * SECONDS_PER_MIN)
    short = minutes < OBSERVE_DEFAULT_MIN
    step.add_result("Observed", f"{minutes:g} min with the cannula in"
                    + (": shorter than the 15 minutes usual for low-risk patients" if short else ""), alert=short)
    step.add_result("Advice", AFTER_CARE_ADVICE)


def _room_turnaround(ctx: CTContext, step: Step) -> None:
    ctx.jump(AFTERCARE_JUMP_S[step.id])


def _close_exam(ctx: CTContext, step: Step) -> None:
    step.add_result("Exam time", f"Exam time: {ctx.clock.now_s / SECONDS_PER_MIN:.0f} min")


def aftercare_steps(ctx: CTContext) -> list[Step]:
    site = Field("site_ok", "Site normal", "bool", True, source="assumption",
                 help="Assumes no pain or swelling at the cannula site.")
    observe = number_field("observe_min", "Observation time", OBSERVE_DEFAULT_MIN, "assumption", unit="min", lo=0,
                           hi=OBSERVE_MAX_MIN, help="15 to 30 minutes with the cannula in (research note 02 section I).")
    return [
        make_step("table_out", "Bring the table out and lower it, switch off the warning light and enter the room.",
                  _table_out),
        make_step("disconnect_injector", "Disconnect the line from the cannula and look at the site; the cannula "
                  "stays in during observation.", _disconnect_injector, [site]),
        make_step("patient_off_table", "Help the patient sit up and step down from the table.", _patient_off_table),
        make_step("post_contrast_care", "Nearly all serious reactions begin within 20 minutes, so the patient is "
                  "watched for 15 minutes (30 for high risk) with the IV left in (note 02 section I).",
                  _post_contrast_care, [observe]),
        make_step("room_turnaround", "Clean the table and reset the room for the next patient.", _room_turnaround),
        make_step("close_exam", "Complete the record.", _close_exam),
    ]
