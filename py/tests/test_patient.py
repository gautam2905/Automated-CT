import pytest

from scansim.core.clock import SimClock
from scansim.core.process import Scheduler
from scansim.patient.breathing import Breathing
from scansim.patient.record import make_record


@pytest.fixture
def run_with():
    def run(gen, on_tick, dt=0.05, limit_s=60.0):
        sched = Scheduler(SimClock())
        handle = sched.start(gen, name="test")
        elapsed = 0.0
        while not handle.done:
            assert elapsed < limit_s, "routine did not finish"
            sched.advance(dt)
            on_tick(dt)
            elapsed += dt
        assert handle.error is None
    return run


def test_record_is_deterministic_and_flags_estimates(pack):
    a, b = make_record(pack, 7), make_record(pack, 7)
    assert a == b and len({make_record(pack, s).age for s in range(8)}) > 1
    assert a.estimated_fields == ["age", "sex", "height_cm", "weight_kg"] and a.name == "Volunteer 000"
    assert a.height_cm == pytest.approx(pack.stature_mm / 10) and 3.0 < a.cardiac_output_l_min < 10.0


def test_record_defaults_and_view(pack):
    for seed in range(8):
        r = make_record(pack, seed)
        assert 25 <= r.age <= 75 and r.sex in ("F", "M")
        assert r.pregnancy == ("not applicable" if r.sex == "M" else "no")
    assert (r.egfr, r.iv_gauge, r.max_hold_s) == (90, "20g", 25.0)
    assert not r.prior_contrast_reaction and not r.on_metformin
    v = r.view()
    assert v.name == r.name and v.height_cm == r.height_cm and v.estimated_fields == r.estimated_fields
    assert make_record(pack, 1).estimated_fields is not make_record(pack, 1).estimated_fields


def test_two_patients_differ_under_the_same_seed_and_the_seed_still_matters(pack, DATA):
    from scansim.patient.pack import PatientPack
    from scansim.patient.record import RECORD_STREAM, SETUP_STREAM, variation_seed
    packs = [PatientPack.load(p) for p in sorted((DATA / "patients").iterdir()) if (p / "meta.json").is_file()]
    people = {(r.age, r.sex) for r in (make_record(p, 1) for p in packs)}
    assert len(packs) >= 5 and len(people) >= 3            # not five copies of one person
    assert {r.sex for r in (make_record(p, 1) for p in packs)} == {"F", "M"}
    assert len({make_record(pack, s).age for s in range(8)}) > 1
    assert variation_seed("sub-000", 1, RECORD_STREAM) != variation_seed("sub-001", 1, RECORD_STREAM)
    assert variation_seed("sub-000", 1, RECORD_STREAM) != variation_seed("sub-000", 1, SETUP_STREAM)
    assert variation_seed("sub-000", 1, RECORD_STREAM) == variation_seed("sub-000", 1, RECORD_STREAM)


def test_quiet_breathing_oscillates():
    b = Breathing(period_s=4.0); vals = []
    for _ in range(200): b.advance(0.05); vals.append(b.value)
    assert max(vals) > 0.25 and min(vals) < -0.25 and not b.holding


def test_hold_and_release(run_with):
    b = Breathing(); run_with(b.hold("inspiration"), b.advance)
    assert b.holding and b.value == pytest.approx(1.0)
    for _ in range(100): b.advance(0.05)
    assert b.value == pytest.approx(1.0)
    b.release(); b.advance(2.0); assert not b.holding


def test_hold_breaks_after_max(run_with):
    b = Breathing(max_hold_s=3.0); run_with(b.hold("inspiration"), b.advance)
    for _ in range(100): b.advance(0.05)
    assert b.broke_hold and not b.holding


def test_expiration_hold_and_new_hold_clears_broke_flag(run_with):
    b = Breathing(max_hold_s=1.0); run_with(b.hold("expiration"), b.advance)
    assert b.value == pytest.approx(-1.0)
    for _ in range(40): b.advance(0.05)
    assert b.broke_hold
    b.advance(3.0)
    run_with(b.hold(), b.advance)
    assert b.holding and not b.broke_hold


def test_release_returns_to_quiet_breathing(run_with):
    b = Breathing(); run_with(b.hold(), b.advance); b.release()
    for _ in range(60): b.advance(0.05)
    assert not b.holding and abs(b.value) <= 0.35 + 1e-9
    seen = []
    for _ in range(100): b.advance(0.05); seen.append(b.value)
    assert max(seen) > 0.25 and min(seen) < -0.25


def test_hold_rejects_unknown_phase():
    with pytest.raises(ValueError):
        next(Breathing().hold("sideways"))
