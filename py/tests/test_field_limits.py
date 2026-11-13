"""A value inside a field's own limits must never end the exam: it works, or it is refused with a reason
and can be corrected."""
import pytest
from helpers import ORDER, do, steps, truth_covered

from scansim.session import open_session

PROTOCOL = "ohsu.ct.multiphase_liver"


def _set(session, step_id, key, value):
    return session.dispatch({"type": "set_field", "step_id": step_id, "key": key, "value": value})


def _perform(session, step_id):
    result = session.dispatch({"type": "perform", "step_id": step_id})
    session.run_until_idle()
    return result


def _status(session, step_id):
    return steps(session.snapshot())[step_id].status


def _number_fields(DATA):
    session = open_session(DATA, PROTOCOL, "sub-000", seed=1)
    return [(step.id, f.key, f.min, f.max)
            for stage in session.snapshot().stages for step in stage.steps
            for f in step.fields if f.type == "number"]


def _cases():
    from conftest import DATA_DIR
    return [(step_id, key, limit) for step_id, key, low, high in _number_fields(DATA_DIR)
            for limit in (low, high) if limit is not None]


def _prepare(session, pack, step_id):
    """The one answer no default can give. Everything else, the tracking region included, stays as pre-filled,
    so the exam takes the no-trigger path."""
    if step_id == "review_noncontrast":
        answer = "yes" if truth_covered(session, pack) else "no"
        assert _set(session, step_id, "liver_included", answer).ok


def _value(session, step_id, key):
    return next(f.value for f in steps(session.snapshot())[step_id].fields if f.key == key)


CASES = _cases()


def _lower_the_chaser(session):
    """The remedy the refusal itself names: programme no more saline than the test flush has left."""
    assert _set(session, "arm_injector", "saline_ml", session.snapshot().injector.saline_ml).ok


# A limit that is accepted but makes a later step refuse, and what the user then does about it. Every other
# such case is put right by doing the step again with its pre-filled value, which the test does by itself.
REMEDIES = {("connect_injector", "test_volume_ml"): _lower_the_chaser}


def _drive_to(session, pack, step_id):
    for earlier in ORDER[:ORDER.index(step_id)]:
        if _status(session, earlier) != "done":
            _prepare(session, pack, earlier)
            do(session, earlier)
    _prepare(session, pack, step_id)


def _finish(session, pack, step_id, key, usual):
    """Finish the exam; a refusal further on is answered once, by the remedy or by repeating the step."""
    remedied = False
    for _ in range(3):
        refused = None
        for later in ORDER:
            if _status(session, later) == "done":
                continue
            _prepare(session, pack, later)
            result = _perform(session, later)
            if not result.ok or _status(session, later) != "done":
                refused = (later, result.error)
                break
        if refused is None:
            return
        assert not remedied, f"still refused after the remedy: {refused}"
        remedied = True
        if (step_id, key) in REMEDIES:
            REMEDIES[(step_id, key)](session)
        else:
            card = steps(session.snapshot())[step_id]
            assert card.status == "done" and card.repeatable, f"{refused}: {step_id} cannot be done again"
            assert _set(session, step_id, key, usual).ok
            do(session, step_id)
    raise AssertionError("the exam did not finish")


@pytest.mark.parametrize("step_id,key,limit", CASES, ids=[f"{s}.{k}={v:g}" for s, k, v in CASES])
def test_every_number_field_at_its_limit_is_refused_at_once_or_leaves_an_exam_that_finishes(
        DATA, pack, step_id, key, limit):
    session = open_session(DATA, PROTOCOL, "sub-000", seed=1)
    _drive_to(session, pack, step_id)
    usual = _value(session, step_id, key)         # the pre-filled value, as the step shows it when it is reached
    edit = _set(session, step_id, key, limit)
    if not edit.ok:                               # the field itself refuses its limit here, and says why
        assert edit.error
    else:
        result = _perform(session, step_id)
        if not result.ok or _status(session, step_id) != "done":      # refused at once, with the reason
            alerts = [e.text for e in session.snapshot().log if e.kind == "alert"]
            assert result.error or alerts
            assert _set(session, step_id, key, usual).ok
            do(session, step_id)
    _finish(session, pack, step_id, key, usual)
    snap = session.snapshot(); st = steps(snap)
    assert [s for s in ORDER if st[s].status != "done"] == []
    assert snap.pose.stage == "away" and st["close_exam"].status == "done"


def test_the_limits_test_covers_every_number_field(DATA):
    fields = {(s, k) for s, k, *_ in _number_fields(DATA)}
    assert len(fields) >= 35 and ("monitoring_slice", "slice_mm") in fields
    assert {(s, k) for s, k, _ in CASES} == fields and len(CASES) == 2 * len(fields)


# ---- load_injector: volumes the exam cannot be finished with are refused when they are loaded ----

def _to_load_injector(session):
    for step_id in ORDER[:ORDER.index("load_injector")]:
        do(session, step_id)


@pytest.mark.parametrize("key,value,words", [
    ("contrast_ml", 0, ("contrast", "cannot be loaded again")),
    ("saline_ml", 0, ("50 mL of saline", "test flush", "0 mL is not enough")),
    ("saline_ml", 10, ("50 mL of saline", "chaser", "10 mL is not enough")),
    ("saline_ml", 49, ("50 mL of saline", "49 mL is not enough")),
])
def test_load_injector_refuses_a_volume_the_exam_cannot_be_finished_with(session, pack, key, value, words):
    _to_load_injector(session)
    assert _set(session, "load_injector", key, value).ok
    before = session.snapshot().clock.sim_time_s
    result = session.dispatch({"type": "perform", "step_id": "load_injector"})
    assert not result.ok and all(word in result.error for word in words), result.error
    snap = session.snapshot()
    assert steps(snap)["load_injector"].status == "ready" and snap.injector.state == "unloaded"
    assert snap.clock.sim_time_s == before                         # a refusal costs no time
    default = next(f.default for f in steps(snap)["load_injector"].fields if f.key == key)
    assert _set(session, "load_injector", key, default).ok
    do(session, "load_injector")
    assert session.snapshot().injector.state == "purged"


def test_load_injector_accepts_exactly_the_chaser_plus_the_test_flush(session, pack):
    _to_load_injector(session)
    assert _set(session, "load_injector", "saline_ml", 50).ok
    do(session, "load_injector")
    assert session.snapshot().injector.saline_ml == 50


def test_load_injector_cannot_be_done_twice(session):
    _to_load_injector(session)
    do(session, "load_injector")
    card = steps(session.snapshot())["load_injector"]
    assert not card.repeatable and not card.fields[0].editable
    assert not session.dispatch({"type": "perform", "step_id": "load_injector"}).ok
