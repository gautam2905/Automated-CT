"""The baseline run: every step performed with its pre-filled values and nothing else.

The design makes this run the baseline that later automation is compared against, so its timing is pinned
here. The only input given is the non-contrast review answer, which has no pre-filled value.
"""
import pytest
from conftest import DATA_DIR, PROTOCOL_ID
from helpers import ORDER, do, steps

from scansim.session import open_session

PATIENTS = sorted(p.name for p in (DATA_DIR / "patients").iterdir() if (p / "meta.json").is_file())
VENOUS_FALLBACK_S = 70.0       # with no trigger the venous scan is timed from the injection start
DELAYED_S = 240.0


def _run_on_defaults(session):
    for step_id in ORDER:
        if steps(session.snapshot())[step_id].status == "done":
            continue                                   # the venous and delayed scans start by themselves
        if step_id == "review_noncontrast":
            assert session.dispatch({"type": "set_field", "step_id": step_id, "key": "liver_included",
                                     "value": "yes"}).ok
        do(session, step_id)


@pytest.mark.parametrize("patient_id", PATIENTS)
def test_a_defaults_only_exam_scans_the_venous_phase_on_time(DATA, patient_id):
    session = open_session(DATA, PROTOCOL_ID, patient_id, seed=1)
    _run_on_defaults(session)
    snap = session.snapshot(); st = steps(snap)
    assert [s for s in ORDER if st[s].status != "done"] == [] and snap.pose.stage == "away"
    series = {s.id: s for s in snap.console.series}
    started = snap.clock.sim_time_s - snap.clock.contrast_timer_s
    # The pre-filled region is not on the aorta, so nothing triggers and the arterial phase is lost.
    assert snap.console.tracking.state == "missed" and series["arterial"].status == "missed"
    assert series["venous"].started_at_s - started == pytest.approx(VENOUS_FALLBACK_S, abs=0.5)
    assert series["delayed"].started_at_s - started == pytest.approx(DELAYED_S, abs=0.5)
    late = [e.text for e in session.ctx.log.tail(2000) if "after its planned time" in e.text]
    assert late == []


def test_five_patients_are_built():
    assert len(PATIENTS) >= 5
