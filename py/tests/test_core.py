import json

import pytest

from scansim.core.clock import SimClock
from scansim.core.events import EventLog
from scansim.core.fields import Field, FieldError
from scansim.core.process import ProcessTimeout, Scheduler, Sleep, Tick, Until, move_linear
from scansim.core.steps import Step, StepError, Workflow


class Ctx:
    """Plain stand-in for the real context."""


def sleeper(seconds=2.0):
    def routine(ctx, step):
        yield Sleep(seconds)
    return routine


def make_step(sid, stage="s1", requires=(), routine=None, **kw):
    return Step(sid, stage, sid.upper(), actor="technologist", place="scan_room", info="info",
                requires=requires, routine=routine or sleeper(), **kw)


@pytest.fixture
def clock():
    return SimClock()


@pytest.fixture
def scheduler(clock):
    return Scheduler(clock)


@pytest.fixture
def log(clock):
    return EventLog(clock)


@pytest.fixture
def ctx():
    return Ctx()


@pytest.fixture
def workflow(scheduler, log):
    a = make_step("a", repeatable=True, invalidates=("b",),
                  fields=[Field("n", "Count", "number", 1.0, source="protocol", min=0, max=10)])
    b = make_step("b", requires=("a",))
    c = make_step("c", requires=("b",))
    return Workflow([("s1", "Stage one", [a, b, c])], scheduler, log)


# ---- scheduler ----

def test_sleep_is_exact():
    clock = SimClock(); sch = Scheduler(clock); seen = []
    def gen():
        yield Sleep(1.5); seen.append(clock.now_s)
    sch.start(gen(), name="x"); sch.advance(1.0); assert seen == []
    sch.advance(1.0); assert seen == [pytest.approx(1.5, abs=0.021)] and clock.now_s == pytest.approx(2.0)


def test_move_linear_takes_distance_over_speed():
    clock = SimClock(); sch = Scheduler(clock); box = {"v": 0.0}
    h = sch.start(move_linear(lambda: box["v"], lambda v: box.__setitem__("v", v), 300.0, 100.0), name="m")
    sch.advance(2.9); assert not h.done
    sch.advance(0.2); assert h.done and box["v"] == 300.0


def test_until_times_out():
    clock = SimClock(); sch = Scheduler(clock); out = []
    def gen():
        try: yield Until(lambda: False, timeout_s=5)
        except ProcessTimeout: out.append("timeout")
    sch.start(gen(), name="u"); sch.advance(6); assert out == ["timeout"]


def test_until_resumes_when_predicate_becomes_true(clock, scheduler):
    flag = {"on": False}; out = []
    def gen():
        yield Until(lambda: flag["on"]); out.append(clock.now_s)
    scheduler.start(gen(), name="u")
    scheduler.advance(1.0); assert out == []
    flag["on"] = True; scheduler.advance(0.1); assert len(out) == 1


def test_move_linear_moves_downwards(scheduler):
    box = {"v": 10.0}
    h = scheduler.start(move_linear(lambda: box["v"], lambda v: box.__setitem__("v", v), 4.0, 2.0), name="m")
    scheduler.advance(3.1); assert h.done and box["v"] == 4.0


def test_nested_generators_via_yield_from(clock, scheduler):
    out = []
    def inner():
        yield Sleep(1.0); out.append("inner")
    def outer():
        yield from inner(); out.append("outer")
    h = scheduler.start(outer(), name="o"); scheduler.advance(1.1)
    assert out == ["inner", "outer"] and h.done


def test_cancel_runs_finally_and_marks_done(scheduler):
    out = []
    def gen():
        try: yield Sleep(10)
        finally: out.append("off")
    h = scheduler.start(gen(), name="g", foreground=True)
    assert scheduler.foreground is h
    scheduler.cancel(h)
    assert out == ["off"] and h.done and scheduler.foreground is None


def test_exception_in_process_is_recorded_on_handle(scheduler):
    def gen():
        yield Sleep(0.1); raise RuntimeError("boom")
    h = scheduler.start(gen(), name="g")
    with pytest.raises(RuntimeError, match="boom"):      # a programming error is loud
        scheduler.advance(0.5)
    assert h.done and isinstance(h.error, RuntimeError)


def test_background_processes_advance_with_foreground(scheduler):
    out = []
    def mk(tag, s):
        def g():
            yield Sleep(s); out.append(tag)
        return g()
    scheduler.start(mk("fg", 1.0), name="fg", foreground=True)
    scheduler.start(mk("bg", 0.5), name="bg")
    scheduler.advance(1.1)
    assert out == ["bg", "fg"] and scheduler.foreground is None


def test_advance_moves_clock_by_exact_dt(clock, scheduler):
    scheduler.advance(0.33); scheduler.advance(1.0)
    assert clock.now_s == pytest.approx(1.33)


# ---- fields ----

@pytest.mark.parametrize("raw", ["", "abc", float("nan"), 2000, -1, None])
def test_number_field_rejects_bad_values(raw):
    f = Field("height", "Table height", "number", 900.0, source="scanner", unit="mm", min=500, max=1000)
    with pytest.raises(FieldError) as e:
        f.set(raw)
    assert "Table height" in str(e.value) and f.value == 900.0
    assert json.loads(f.view().model_dump_json())["value"] == 900.0


@pytest.mark.parametrize("raw", [True, float("inf"), "  ", "inf"])
def test_number_field_rejects_bool_infinity_blank(raw):
    f = Field("h", "Height", "number", 900.0, source="scanner", min=500, max=1000)
    with pytest.raises(FieldError):
        f.set(raw)


def test_number_field_error_names_limits():
    f = Field("h", "Table height", "number", 900.0, source="scanner", unit="mm", min=500, max=1000)
    with pytest.raises(FieldError) as e:
        f.set(2000)
    assert "500" in str(e.value) and "1000" in str(e.value)


def test_number_field_accepts_numeric_string_and_stores_float():
    f = Field("h", "Height", "number", 900.0, source="scanner", min=500, max=1000)
    f.set("750"); assert f.value == 750.0 and isinstance(f.value, float)
    f.set(800); assert isinstance(f.value, float)


def test_choice_field_rejects_unknown_option():
    f = Field("g", "IV gauge", "choice", "20g", source="protocol", options=[("18g", "18g"), ("20g", "20g")])
    with pytest.raises(FieldError): f.set("14g")


def test_choice_field_accepts_option_and_views_options():
    f = Field("g", "IV gauge", "choice", "20g", source="protocol", options=[("18g", "Eighteen"), ("20g", "20g")])
    f.set("18g")
    v = f.view()
    assert v.value == "18g" and [(o.value, o.label) for o in v.options] == [("18g", "Eighteen"), ("20g", "20g")]


def test_bool_field_accepts_only_bool():
    f = Field("k", "Consent", "bool", False, source="patient")
    f.set(True); assert f.value is True
    for bad in (1, "true", None):
        with pytest.raises(FieldError): f.set(bad)
    assert f.value is True


def test_text_field_strips_and_limits_length():
    f = Field("t", "Note", "text", "", source="protocol")
    f.set("  hello  "); assert f.value == "hello"
    with pytest.raises(FieldError): f.set("x" * 201)
    with pytest.raises(FieldError): f.set(5)
    f.set("x" * 200)


def test_field_view_editable_flag_and_metadata():
    f = Field("h", "Height", "number", 900.0, source="scanner", unit="mm", min=500, max=1000, step=5, help="tip")
    v = f.view(editable=False)
    assert v.editable is False and v.unit == "mm" and v.min == 500 and v.max == 1000
    assert v.step == 5 and v.help == "tip" and v.source == "scanner" and v.default == 900.0


# ---- events ----

def test_event_log_stamps_clock_time_and_tails(clock, log):
    log.add("event", "one"); clock.advance(2.0); log.add("alert", "two"); log.add("step", "three")
    t = log.tail(2)
    assert [e.text for e in t] == ["two", "three"] and t[0].t_s == 2.0 and t[0].kind == "alert"
    assert len(log.tail()) == 3


# ---- workflow ----

def test_locked_step_cannot_run_and_explains(workflow, ctx):
    with pytest.raises(StepError) as e: workflow.perform("b", ctx)
    assert "a" in str(e.value) or "first" in str(e.value).lower()
    assert workflow.step("b").status == "locked"


def test_locked_reason_names_prerequisite_title(workflow, ctx):
    stages = workflow.views(ctx)
    b = stages[0].steps[1]
    assert b.status == "locked" and b.blocked_by == ['Do "A" first']


def test_second_perform_while_running_is_rejected(workflow, ctx, scheduler):
    workflow.perform("a", ctx)
    with pytest.raises(StepError): workflow.perform("a", ctx)
    scheduler.advance(2.1); assert workflow.step("a").status == "done" and workflow.step("b").status == "ready"


def test_perform_another_step_while_running_is_rejected(scheduler, log, ctx):
    a = make_step("a"); b = make_step("b")
    wf = Workflow([("s", "S", [a, b])], scheduler, log)
    wf.perform("a", ctx)
    with pytest.raises(StepError): wf.perform("b", ctx)
    assert wf.step("b").status == "ready" and wf.active_step_id == "a"


def test_repeating_a_step_marks_dependants_redo(workflow, ctx, scheduler):
    for s in ("a", "b"):
        workflow.perform(s, ctx); scheduler.advance(2.1)
    workflow.perform("a", ctx); scheduler.advance(2.1)
    assert workflow.step("b").status == "redo" and workflow.step("c").status == "locked"


def test_redo_is_transitive_over_done_steps(workflow, ctx, scheduler):
    for s in ("a", "b", "c"):
        workflow.perform(s, ctx); scheduler.advance(2.1)
    workflow.perform("a", ctx); scheduler.advance(2.1)
    assert workflow.step("b").status == "redo" and workflow.step("c").status == "redo"


def test_non_repeatable_done_step_cannot_run_again(workflow, ctx, scheduler):
    for s in ("a", "b"):
        workflow.perform(s, ctx); scheduler.advance(2.1)
    with pytest.raises(StepError): workflow.perform("b", ctx)


def test_abort_returns_step_to_ready(workflow, ctx, scheduler):
    workflow.perform("a", ctx); scheduler.advance(0.5); workflow.abort()
    assert workflow.step("a").status == "ready" and workflow.active_step_id is None


def test_abort_runs_routine_finally(scheduler, log, ctx):
    out = []
    def routine(c, s):
        try: yield Sleep(10)
        finally: out.append("beam off")
    wf = Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)
    wf.perform("a", ctx); wf.abort()
    assert out == ["beam off"]


def test_routine_without_waits_completes_inside_perform(scheduler, log, ctx):
    def routine(c, s):
        s.add_result("x", "1")
        return
        yield
    wf = Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)
    wf.perform("a", ctx)
    assert wf.step("a").status == "done" and wf.active_step_id is None
    assert wf.step("a").results[0].label == "x"


def test_step_error_before_first_wait_reraises_and_resets(scheduler, log, ctx):
    def routine(c, s):
        raise StepError("Door is open")
        yield
    wf = Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)
    with pytest.raises(StepError, match="Door is open"):
        wf.perform("a", ctx)
    assert wf.step("a").status == "ready" and wf.active_step_id is None
    assert scheduler.foreground is None
    assert log.tail()[-1].kind == "alert" and "Door is open" in log.tail()[-1].text


def test_step_error_while_advancing_logs_alert_without_raising(scheduler, log, ctx):
    def routine(c, s):
        yield Sleep(1.0); raise StepError("Pressure limit")
    wf = Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)
    wf.perform("a", ctx)
    scheduler.advance(1.5)
    assert wf.step("a").status == "ready" and wf.active_step_id is None
    assert any(e.kind == "alert" and "Pressure limit" in e.text for e in log.tail())


def test_until_timeout_in_routine_returns_step_to_ready_with_alert(scheduler, log, ctx):
    def routine(c, s):
        yield Until(lambda: False, timeout_s=1.0)
    wf = Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)
    wf.perform("a", ctx); scheduler.advance(2.0)
    assert wf.step("a").status == "ready"
    assert any(e.kind == "alert" for e in log.tail())


def test_check_reasons_lock_step_and_fill_blocked_by(scheduler, log, ctx):
    state = {"open": True}
    def check(c, s):
        return ["Close the door"] if state["open"] else []
    wf = Workflow([("s", "S", [make_step("a", check=check)])], scheduler, log)
    v = wf.views(ctx)[0].steps[0]
    assert v.status == "locked" and v.blocked_by == ["Close the door"]
    with pytest.raises(StepError, match="Close the door"):
        wf.perform("a", ctx)
    state["open"] = False
    assert wf.step("a").status == "ready"
    wf.perform("a", ctx)
    assert wf.step("a").status == "running"


def test_set_field_validates_and_respects_editability(workflow, ctx, scheduler):
    workflow.views(ctx)
    with pytest.raises(FieldError): workflow.set_field("a", "n", 99)
    assert workflow.step("a").value("n") == 1.0
    workflow.set_field("a", "n", "5"); assert workflow.step("a").value("n") == 5.0
    workflow.perform("a", ctx)
    with pytest.raises(StepError): workflow.set_field("a", "n", 6)       # running
    scheduler.advance(2.1)
    workflow.set_field("a", "n", 7)                                      # done and repeatable
    assert workflow.step("a").value("n") == 7.0


def test_set_field_rejected_on_locked_step(scheduler, log, ctx):
    a = make_step("a"); b = make_step("b", requires=("a",),
                                      fields=[Field("n", "N", "number", 1.0, source="protocol")])
    wf = Workflow([("s", "S", [a, b])], scheduler, log)
    with pytest.raises(StepError): wf.set_field("b", "n", 2)


def test_views_flag_fields_editable_by_status(workflow, ctx, scheduler):
    assert workflow.views(ctx)[0].steps[0].fields[0].editable is True
    workflow.perform("a", ctx)
    assert workflow.views(ctx)[0].steps[0].fields[0].editable is False
    scheduler.advance(2.1)
    assert workflow.views(ctx)[0].steps[0].fields[0].editable is True   # done + repeatable


def test_views_serialise_and_carry_step_metadata(workflow, ctx, scheduler):
    workflow.perform("a", ctx); workflow.step("a").add_result("Dose", "5", alert=True)
    stages = workflow.views(ctx)
    json.dumps([s.model_dump(mode="json") for s in stages])
    s = stages[0]
    assert s.id == "s1" and s.title == "Stage one" and [x.id for x in s.steps] == ["a", "b", "c"]
    a = s.steps[0]
    assert a.status == "running" and a.repeatable and a.results[0].alert is True
    assert a.action_label == "Do step" and a.actor == "technologist" and a.place == "scan_room"


def test_perform_logs_step_events(workflow, ctx, scheduler, log):
    workflow.perform("a", ctx); scheduler.advance(2.1)
    kinds = [e.kind for e in log.tail()]
    assert kinds.count("step") >= 2


def test_workflow_rejects_unknown_references_and_duplicates(scheduler, log):
    with pytest.raises(ValueError):
        Workflow([("s", "S", [make_step("a", requires=("zzz",))])], scheduler, log)
    with pytest.raises(ValueError):
        Workflow([("s", "S", [make_step("a"), make_step("a")])], scheduler, log)


def test_unknown_step_raises_key_error(workflow):
    with pytest.raises(KeyError): workflow.step("nope")


# ---- fix round 1 ----

FRAME_S = 1 / 30


def one_step_workflow(scheduler, log, routine):
    return Workflow([("s", "S", [make_step("a", routine=routine)])], scheduler, log)


def test_bad_yield_runs_finally_resets_step_and_raises(scheduler, log, ctx):
    out = []
    def routine(c, s):
        try: yield "oops"
        finally: out.append("off")
    wf = one_step_workflow(scheduler, log, routine)
    with pytest.raises(TypeError):
        wf.perform("a", ctx)
    assert out == ["off"] and wf.step("a").status == "ready" and wf.active_step_id is None
    assert any(e.kind == "alert" and 'A failed: TypeError' in e.text for e in log.tail())
    with pytest.raises(TypeError):                        # recoverable: it can be performed (and fail) again
        wf.perform("a", ctx)
    assert scheduler.foreground is None


def test_bad_yield_after_first_wait_raises_from_advance(scheduler, log, ctx):
    def routine(c, s):
        yield Sleep(0.1); yield 42
    wf = one_step_workflow(scheduler, log, routine)
    wf.perform("a", ctx)
    with pytest.raises(TypeError):
        scheduler.advance(0.5)
    assert wf.step("a").status == "ready" and wf.active_step_id is None


def test_programming_error_before_first_wait_is_raised_from_perform(scheduler, log, ctx):
    def routine(c, s):
        raise AttributeError("typo")
        yield
    wf = one_step_workflow(scheduler, log, routine)
    with pytest.raises(AttributeError, match="typo"):
        wf.perform("a", ctx)
    assert wf.step("a").status == "ready" and wf.active_step_id is None
    assert any(e.kind == "alert" and "A failed: AttributeError: typo" in e.text for e in log.tail())


def test_programming_error_after_first_wait_is_raised_from_advance(scheduler, log, ctx):
    def routine(c, s):
        yield Sleep(0.1); raise AttributeError("typo")
    wf = one_step_workflow(scheduler, log, routine)
    wf.perform("a", ctx)
    with pytest.raises(AttributeError, match="typo"):
        scheduler.advance(0.5)
    assert wf.step("a").status == "ready" and wf.active_step_id is None and scheduler.foreground is None


def test_other_processes_are_ticked_before_error_is_raised(clock, scheduler):
    out = []
    def bad():
        yield Sleep(0.1); raise KeyError("x")
    def good():
        yield Sleep(0.1); out.append("good")
    scheduler.start(bad(), name="bad"); scheduler.start(good(), name="good")
    with pytest.raises(KeyError):
        scheduler.advance(0.5)
    assert out == ["good"]


def test_timeout_alert_uses_step_title(scheduler, log, ctx):
    def routine(c, s):
        yield Until(lambda: False, timeout_s=0.5)
    wf = Workflow([("s", "S", [Step("a", "s", "Pretty title", actor="technologist", place="scan_room",
                                    info="i", routine=routine)])], scheduler, log)
    wf.perform("a", ctx); scheduler.advance(1.0)
    assert any(e.kind == "alert" and "Pretty title" in e.text for e in log.tail())


def test_background_step_error_reaches_log_and_process_ends(clock, log):
    sch = Scheduler(clock, log)
    def bg():
        yield Sleep(0.1); raise StepError("Tube overheated")
    h = sch.start(bg(), name="bg"); sch.advance(0.5)
    assert h.done and isinstance(h.error, StepError)
    assert any(e.kind == "alert" and "Tube overheated" in e.text for e in log.tail())


def test_background_programming_error_is_raised_from_advance(clock, log):
    sch = Scheduler(clock, log)
    def bg():
        yield Sleep(0.1); raise ZeroDivisionError("bug")
    sch.start(bg(), name="bg")
    with pytest.raises(ZeroDivisionError):
        sch.advance(0.5)


def test_raising_predicate_is_thrown_into_generator(scheduler):
    out = []
    def pred():
        raise RuntimeError("bad predicate")
    def gen():
        try: yield Until(pred)
        finally: out.append("cleanup")
    h = scheduler.start(gen(), name="g")
    with pytest.raises(RuntimeError, match="bad predicate"):
        scheduler.advance(0.1)
    assert out == ["cleanup"] and h.done
    scheduler.advance(0.1)                                # no recurrence


def test_abort_with_nested_generator_runs_inner_finally(scheduler, log, ctx):
    out = []
    def inner():
        try: yield Sleep(10)
        finally: out.append("inner")
    def routine(c, s):
        try: yield from inner()
        finally: out.append("outer")
    wf = one_step_workflow(scheduler, log, routine)
    wf.perform("a", ctx); scheduler.advance(0.2); wf.abort()
    assert out == ["inner", "outer"] and wf.step("a").status == "ready" and wf.active_step_id is None


def test_move_linear_speed_is_right_at_30hz(clock, scheduler):
    box = {"v": 0.0}
    scheduler.start(move_linear(lambda: box["v"], lambda v: box.__setitem__("v", v), 500.0, 100.0), name="m")
    for _ in range(30):
        scheduler.advance(FRAME_S)
    assert clock.now_s == pytest.approx(1.0) and box["v"] == pytest.approx(100.0, abs=2.1)


def test_sequential_sleeps_do_not_accumulate_lateness(clock, scheduler):
    done = {}
    def gen():
        for _ in range(10):
            yield Sleep(0.1)
        done["t"] = clock.now_s
    scheduler.start(gen(), name="g")
    for _ in range(60):
        scheduler.advance(FRAME_S)
    assert done["t"] == pytest.approx(1.0, abs=0.021)


def test_sequential_sleeps_off_grid_stay_on_schedule(clock, scheduler):
    done = {}
    def gen():
        for _ in range(10):
            yield Sleep(0.07)
        done["t"] = clock.now_s
    scheduler.start(gen(), name="g")
    for _ in range(60):
        scheduler.advance(FRAME_S)
    assert done["t"] == pytest.approx(0.7, abs=0.021)


def test_tick_receives_substep_duration(scheduler):
    seen = []
    def gen():
        seen.append((yield Tick()))
    scheduler.start(gen(), name="g"); scheduler.advance(0.01)
    assert seen == [pytest.approx(0.01)]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_non_finite_or_negative_durations_are_rejected(clock, scheduler, bad):
    with pytest.raises(ValueError): clock.advance(bad)
    with pytest.raises(ValueError): scheduler.advance(bad)
    with pytest.raises(ValueError): Sleep(bad)
    with pytest.raises(ValueError): Until(lambda: True, timeout_s=bad)


# ---- aborted or refused repeat restores done ----

def _repeat_workflow(scheduler, log, ctx, second_run):
    runs = {"n": 0}
    def routine(c, s):
        runs["n"] += 1
        if runs["n"] == 1:
            s.add_result("run", "first")
            yield Sleep(1.0)
        else:
            s.add_result("run", "second")
            yield from second_run(s)
    a = make_step("a", repeatable=True, invalidates=("b",), routine=routine)
    wf = Workflow([("s", "S", [a, make_step("b", requires=("a",))])], scheduler, log)
    wf.perform("a", ctx); scheduler.advance(1.1); wf.perform("b", ctx); scheduler.advance(2.1)
    assert wf.step("a").status == "done" and wf.step("b").status == "done"
    return wf


def _wait_forever(s):
    yield Sleep(10)


def test_abort_of_a_repeat_restores_done_and_earlier_results(scheduler, log, ctx):
    wf = _repeat_workflow(scheduler, log, ctx, _wait_forever)
    wf.perform("a", ctx); scheduler.advance(0.3)
    assert wf.step("a").status == "running"
    wf.abort()
    a = wf.step("a")
    assert a.status == "done" and [r.value for r in a.results] == ["first"] and wf.active_step_id is None
    assert wf.step("b").status == "done"


def test_step_error_during_a_repeat_restores_done_and_logs_alert(scheduler, log, ctx):
    def fail_later(s):
        yield Sleep(0.5); raise StepError("Table jammed")
    wf = _repeat_workflow(scheduler, log, ctx, fail_later)
    wf.perform("a", ctx); scheduler.advance(1.0)
    a = wf.step("a")
    assert a.status == "done" and [r.value for r in a.results] == ["first"]
    assert any(e.kind == "alert" and "Table jammed" in e.text for e in log.tail())
    assert wf.step("b").status == "done"


def test_step_error_before_first_wait_of_a_repeat_restores_done(scheduler, log, ctx):
    def fail_now(s):
        raise StepError("Door open")
        yield
    wf = _repeat_workflow(scheduler, log, ctx, fail_now)
    with pytest.raises(StepError, match="Door open"):
        wf.perform("a", ctx)
    a = wf.step("a")
    assert a.status == "done" and [r.value for r in a.results] == ["first"]


def test_programming_error_in_a_repeat_restores_done_before_reraise(scheduler, log, ctx):
    def bug(s):
        raise AttributeError("typo")
        yield
    wf = _repeat_workflow(scheduler, log, ctx, bug)
    with pytest.raises(AttributeError):
        wf.perform("a", ctx)
    assert wf.step("a").status == "done" and wf.active_step_id is None


def test_timeout_during_a_repeat_restores_done(scheduler, log, ctx):
    def wait_out(s):
        yield Until(lambda: False, timeout_s=0.5)
    wf = _repeat_workflow(scheduler, log, ctx, wait_out)
    wf.perform("a", ctx); scheduler.advance(1.0)
    assert wf.step("a").status == "done" and [r.value for r in wf.step("a").results] == ["first"]


def test_completed_repeat_replaces_results_and_marks_dependants_redo(scheduler, log, ctx):
    def short(s):
        yield Sleep(0.5)
    wf = _repeat_workflow(scheduler, log, ctx, short)
    wf.perform("a", ctx); scheduler.advance(0.6)
    assert wf.step("a").status == "done" and [r.value for r in wf.step("a").results] == ["second"]
    assert wf.step("b").status == "redo"


def test_abort_of_a_first_run_still_gives_ready(scheduler, log, ctx):
    wf = _repeat_workflow(scheduler, log, ctx, _wait_forever)
    wf2 = Workflow([("s", "S", [make_step("x", repeatable=True)])], scheduler, log)
    wf2.perform("x", ctx); scheduler.advance(0.5); wf2.abort()
    assert wf2.step("x").status == "ready" and wf2.step("x").results == []
