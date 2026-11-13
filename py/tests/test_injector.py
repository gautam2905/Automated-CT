import pytest

from scansim.core.clock import SimClock
from scansim.core.events import EventLog
from scansim.core.process import Scheduler
from scansim.devices.injector import Injector, InjectorError, InjectorPhase

LIMIT_PSI = 325.0


@pytest.fixture
def clock():
    return SimClock()


@pytest.fixture
def log(clock):
    return EventLog(clock)


@pytest.fixture
def inj(clock, log):
    return Injector(clock, log, pressure_limit_psi=LIMIT_PSI)


@pytest.fixture
def ready_inj(inj):
    inj.load(130, 50, 350)
    inj.purge()
    inj.connect("20g")
    return inj


@pytest.fixture
def drive(clock):
    def _drive(gen, max_s=600.0):
        sch = Scheduler(clock)
        handle = sch.start(gen, name="drive")
        t_end = clock.now_s + max_s
        while not handle.done and clock.now_s < t_end:
            sch.advance(0.25)
        assert handle.done, "generator did not finish"
        if handle.error is not None:
            raise handle.error
        return handle
    return _drive


def test_order_is_enforced(inj):
    with pytest.raises(InjectorError) as e:
        inj.arm()
    assert "load" in str(e.value).lower()


def test_program_cannot_exceed_loaded_volume(ready_inj):
    with pytest.raises(InjectorError):
        ready_inj.program([InjectorPhase("contrast", 150, 4.0)])


def test_injection_delivers_programmed_volumes_and_segments(ready_inj, drive, clock):
    segs = []
    ready_inj.program([InjectorPhase("contrast", 125, 4.0), InjectorPhase("saline", 40, 4.0)])
    ready_inj.arm()
    t0 = clock.now_s
    drive(ready_inj.run(segs.append))
    v = ready_inj.view()
    assert v.state == "done" and v.injected_contrast_ml == pytest.approx(125) and v.injected_saline_ml == pytest.approx(40)
    assert clock.now_s - t0 == pytest.approx(41.25, abs=0.1)
    assert [(s.rate_ml_s, s.iodine_mg_ml) for s in segs] == [(4.0, 350), (4.0, 0)]
    assert segs[0].duration_s == pytest.approx(31.25) and v.contrast_ml == pytest.approx(5)


def test_small_cannula_is_pressure_limited(inj, drive, log):
    inj.load(130, 50, 350); inj.purge(); inj.connect("22g")
    inj.program([InjectorPhase("contrast", 100, 5.0)]); inj.arm(); segs = []; drive(inj.run(segs.append))
    assert segs[0].rate_ml_s < 5.0 and any(e.kind == "alert" for e in log.tail())


def test_limited_rate_holds_pressure_at_limit_and_logs_one_alert(inj, clock, log):
    inj.load(130, 50, 350); inj.purge(); inj.connect("22g")
    inj.program([InjectorPhase("contrast", 50, 5.0), InjectorPhase("contrast", 20, 5.0)])
    inj.arm(); segs = []
    sch = Scheduler(clock); h = sch.start(inj.run(segs.append), name="inj")
    sch.advance(1.0)
    assert inj.view().pressure_psi == pytest.approx(LIMIT_PSI)
    while not h.done:
        sch.advance(0.25)
    assert segs[0].rate_ml_s == pytest.approx(segs[1].rate_ml_s)
    assert sum(e.kind == "alert" for e in log.tail()) == 1
    assert segs[0].duration_s == pytest.approx(50 / segs[0].rate_ml_s)


def test_closing_generator_mid_run_aborts_injection(ready_inj, clock, log):
    ready_inj.program([InjectorPhase("contrast", 100, 4.0)]); ready_inj.arm()
    sch = Scheduler(clock); h = sch.start(ready_inj.run(lambda s: None), name="inj")
    sch.advance(5.0)
    sch.cancel(h)
    v = ready_inj.view()
    assert v.state == "done" and v.flow_ml_s == 0 and v.pressure_psi == 0
    assert 15 < v.injected_contrast_ml < 25
    assert v.injected_contrast_ml + v.contrast_ml == pytest.approx(130)
    assert [e.text for e in log.tail() if e.kind == "alert"] == ["Injection aborted"]


def test_failing_on_segment_aborts_injection(ready_inj, clock, log):
    ready_inj.program([InjectorPhase("contrast", 10, 4.0)]); ready_inj.arm()

    def boom(seg):
        raise RuntimeError("model down")
    with pytest.raises(RuntimeError):
        next(ready_inj.run(boom))
    assert ready_inj.view().state == "done"


def test_pressure_limit_must_be_positive(clock, log):
    with pytest.raises(ValueError):
        Injector(clock, log, pressure_limit_psi=0)


def test_20g_at_4ml_s_is_not_limited(ready_inj, drive, log):
    ready_inj.program([InjectorPhase("contrast", 40, 4.0)]); ready_inj.arm(); segs = []
    drive(ready_inj.run(segs.append))
    assert segs[0].rate_ml_s == 4.0 and not any(e.kind == "alert" for e in log.tail())


def test_pressure_and_flow_reported_while_running_and_zero_after(ready_inj, drive, clock):
    ready_inj.program([InjectorPhase("contrast", 20, 4.0)]); ready_inj.arm()
    sch = Scheduler(clock); h = sch.start(ready_inj.run(lambda s: None), name="inj")
    sch.advance(1.0)
    v = ready_inj.view()
    assert v.state == "injecting" and v.flow_ml_s == 4.0 and 0 < v.pressure_psi <= LIMIT_PSI
    assert ready_inj.started_at_s == 0.0
    while not h.done:
        sch.advance(0.5)
    v = ready_inj.view()
    assert v.flow_ml_s == 0 and v.pressure_psi == 0 and v.state == "done"


def test_stop_ends_injection_early(ready_inj, clock):
    ready_inj.program([InjectorPhase("contrast", 100, 4.0)]); ready_inj.arm()
    sch = Scheduler(clock); h = sch.start(ready_inj.run(lambda s: None), name="inj")
    sch.advance(5.0)
    ready_inj.stop()
    sch.advance(1.0)
    v = ready_inj.view()
    assert h.done and v.state == "done" and v.flow_ml_s == 0 and v.pressure_psi == 0
    assert 15 < v.injected_contrast_ml < 25
    assert v.injected_contrast_ml + v.contrast_ml == pytest.approx(130)


def test_test_inject_returns_peak_pressure_and_stays_connected(ready_inj, drive, clock):
    sch = Scheduler(clock); seen = []
    h = sch.start(ready_inj.test_inject(10.0), name="ti")
    while not h.done:
        sch.advance(0.25); seen.append(ready_inj.view().pressure_psi)
    assert ready_inj.view().state == "connected" and ready_inj.view().pressure_psi == 0
    assert max(seen) > 0 and ready_inj.view().injected_saline_ml == 0
    assert ready_inj.view().saline_ml == pytest.approx(40)
    assert clock.now_s == pytest.approx(5.0, abs=0.3)


def test_test_inject_returns_peak_value(ready_inj, clock):
    gen = ready_inj.test_inject(4.0)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        assert stop.value > 0


def test_test_inject_requires_connected(inj):
    inj.load(130, 50, 350)
    with pytest.raises(InjectorError):
        next(inj.test_inject())


def test_connect_rejects_unknown_gauge(inj):
    inj.load(130, 50, 350); inj.purge()
    with pytest.raises(InjectorError):
        inj.connect("16g")


def test_run_requires_armed(ready_inj):
    with pytest.raises(InjectorError) as e:
        next(ready_inj.run(lambda s: None))
    assert "arm" in str(e.value).lower()


def test_program_rejects_bad_phases(ready_inj):
    for bad in ([], [InjectorPhase("air", 5, 2)], [InjectorPhase("contrast", 0, 2)],
                [InjectorPhase("contrast", 5, 0)]):
        with pytest.raises(InjectorError):
            ready_inj.program(bad)


def test_program_checks_total_per_fluid(ready_inj):
    with pytest.raises(InjectorError):
        ready_inj.program([InjectorPhase("saline", 30, 3), InjectorPhase("saline", 30, 3)])


def test_load_validates_amounts(inj):
    with pytest.raises(InjectorError):
        inj.load(-1, 50, 350)
    with pytest.raises(InjectorError):
        inj.load(100, 50, 0)


# ---- an injection that ends early tells its listener how far it got ----

def test_stop_reports_the_time_up_to_which_contrast_was_delivered(ready_inj, clock):
    ready_inj.program([InjectorPhase("contrast", 100, 4.0)]); ready_inj.arm()
    cuts = []
    sch = Scheduler(clock); sch.start(ready_inj.run(lambda s: None, cuts.append), name="inj")
    sch.advance(8.1)
    ready_inj.stop()
    assert cuts == [pytest.approx(8.0)]                                       # delivery runs in 0.25 s steps
    assert ready_inj.view().injected_contrast_ml == pytest.approx(4.0 * cuts[0])
    sch.advance(1.0)
    assert len(cuts) == 1


def test_an_aborted_injection_reports_its_cut_and_a_finished_one_does_not(ready_inj, drive, clock):
    ready_inj.program([InjectorPhase("contrast", 100, 4.0)]); ready_inj.arm()
    cuts = []
    sch = Scheduler(clock); h = sch.start(ready_inj.run(lambda s: None, cuts.append), name="inj")
    sch.advance(5.0)
    sch.cancel(h)
    assert cuts == [pytest.approx(5.0)]
    assert ready_inj.view().injected_contrast_ml == pytest.approx(20.0)


def test_a_finished_injection_reports_no_cut(ready_inj, drive):
    ready_inj.program([InjectorPhase("contrast", 20, 4.0)]); ready_inj.arm()
    cuts = []
    drive(ready_inj.run(lambda s: None, cuts.append))
    assert cuts == [] and ready_inj.view().state == "done"
