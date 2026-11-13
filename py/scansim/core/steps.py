"""Steps, and the workflow that orders them.

A step keeps one stored state: idle, running, done or redo. `locked` and `ready` are
worked out when asked, from the prerequisites and the step's `check`.

Repeats. A done step marked `repeatable` can be performed again unless its `check` gives a reason
not to; completing it turns the steps that depended on its old result to "redo". A step marked
`irreversible` (an injection, a review, a patient who has left) is never turned back to "redo": the
cascade stops there, and what comes after it waits until everything before it is done again.
"""
from typing import Any, Callable, Generator, Optional

from scansim.core.events import EventLog
from scansim.core.fields import Field
from scansim.core.process import ProcessTimeout, Scheduler, StepError
from scansim.snapshot import ResultView, StageView, StepView


class Step:
    def __init__(self, id: str, stage_id: str, title: str, *, actor: str, place: str, info: str,
                 fields=(), requires=(), repeatable: bool = False, invalidates=(),
                 action_label: str = "Do step", routine: Optional[Callable] = None,
                 check: Optional[Callable] = None, irreversible: bool = False) -> None:
        self.id, self.stage_id, self.title = id, stage_id, title
        self.actor, self.place, self.info = actor, place, info
        self.fields: dict[str, Field] = {f.key: f for f in fields}
        self.requires, self.invalidates = tuple(requires), tuple(invalidates)
        self.repeatable, self.action_label = repeatable, action_label
        self.routine, self.check = routine, check
        self.irreversible = irreversible         # cannot be done twice: never turned back to "redo"
        self.committed = False                   # set by a running routine once its result cannot be undone
        self.results: list[ResultView] = []
        self._state = "idle"                     # idle | running | done | redo
        self._blockers: Callable[[], list[str]] = list   # installed by the Workflow

    @property
    def status(self) -> str:
        if self._state != "idle":
            return self._state
        return "locked" if self._blockers() else "ready"

    def value(self, key: str) -> Any:
        return self.fields[key].value

    def add_result(self, label: str, value: str, alert: bool = False) -> None:
        self.results.append(ResultView(label=label, value=value, alert=alert))


class Workflow:
    def __init__(self, stages: list[tuple[str, str, list[Step]]], scheduler: Scheduler, log: EventLog) -> None:
        self._stages = [(sid, title, list(steps)) for sid, title, steps in stages]
        self._scheduler, self._log = scheduler, log
        self._steps: dict[str, Step] = {}
        for _, _, steps in self._stages:
            for s in steps:
                if s.id in self._steps:
                    raise ValueError(f"Duplicate step id {s.id!r}")
                self._steps[s.id] = s
        self._validate_references()
        for s in self._steps.values():
            s._blockers = lambda s=s: self._blockers(s)
        self.active_step_id: Optional[str] = None
        self._ctx: Any = None                    # last context seen; `check` is skipped until one exists
        self._raised: Optional[StepError] = None
        # State and results of a done or redo step while it runs again; restored if the run does not complete.
        self._earlier: dict[str, tuple[str, list[ResultView]]] = {}

    # ---- lookups ----

    def step(self, step_id: str) -> Step:
        return self._steps[step_id]

    def set_field(self, step_id: str, key: str, raw: Any) -> None:
        step = self.step(step_id)
        field = step.fields[key]
        if not self._editable(step):
            why = self._blockers(step) if step.status == "done" and step.repeatable else []
            raise StepError(f'"{step.title}" cannot be edited ' +
                            (f'any more: {"; ".join(why)}' if why else f'while it is {step.status}'))
        field.set(raw)

    def views(self, ctx: Any) -> list[StageView]:
        self._ctx = ctx
        return [StageView(id=sid, title=title, steps=[self._view(s) for s in steps])
                for sid, title, steps in self._stages]

    # ---- running ----

    def perform(self, step_id: str, ctx: Any) -> None:
        step = self.step(step_id)
        self._ctx = ctx
        self._check_can_perform(step)
        if step._state in ("done", "redo"):      # a repeat: remember the outcome still in force
            self._earlier[step.id] = (step._state, step.results)
        step.results = []
        step.committed = False
        step._state = "running"
        self.active_step_id = step.id
        self._log.add("step", f"Started: {step.title}")
        self._raised = None
        self._scheduler.start(self._run(step, ctx), name=step.id, foreground=True)
        if self._raised is not None:
            raised, self._raised = self._raised, None
            raise raised

    def abort(self) -> None:
        handle = self._scheduler.foreground
        if handle is None or self.active_step_id is None:
            return
        step = self.step(self.active_step_id)
        self._scheduler.cancel(handle)
        if step.committed:                       # what the step produced cannot be undone: it stands
            self._log.add("step", f"Stopped: {step.title} (its result was already in and is kept)")
            self._complete(step)
        else:
            self._unwind(step)
            self._log.add("step", f"Aborted: {step.title}")

    def _run(self, step: Step, ctx: Any) -> Generator:
        try:
            gen = step.routine(ctx, step) if step.routine else None
            if gen is not None:
                yield from gen
        except StepError as err:
            self._fail(step, str(err), err)
        except ProcessTimeout:
            self._fail(step, f"{step.title}: wait timed out", None)
        except Exception as err:
            self._fail(step, f"{step.title} failed: {type(err).__name__}: {err}", None)
            raise                                # programming error: the scheduler re-raises it
        else:
            self._complete(step)

    # ---- internals ----

    def _complete(self, step: Step) -> None:
        self._invalidate_dependants(step)
        step._state = "done"
        self._earlier.pop(step.id, None)
        self.active_step_id = None
        self._log.add("step", f"Done: {step.title}")

    def _fail(self, step: Step, message: str, to_raise: Optional[StepError]) -> None:
        self._unwind(step)
        self._log.add("alert", message)
        self._raised = to_raise

    def _unwind(self, step: Step) -> None:
        """A run that did not complete: a repeat goes back to where it was (done or redo) with its earlier
        results, a first run to ready."""
        step._state, step.results = self._earlier.pop(step.id, ("idle", step.results))
        self.active_step_id = None

    def _invalidate_dependants(self, step: Step) -> None:
        pending, seen = list(step.invalidates), set()
        while pending:
            sid = pending.pop()
            if sid in seen or self._steps[sid].irreversible:     # the cascade stops at what cannot be redone
                continue
            seen.add(sid)
            pending.extend(s.id for s in self._steps.values() if sid in s.requires)
        for sid in seen:
            if self._steps[sid]._state == "done":
                self._steps[sid]._state = "redo"

    def _check_can_perform(self, step: Step) -> None:
        if step._state == "running":
            raise StepError(f'"{step.title}" is already running')
        if self.active_step_id is not None:
            raise StepError(f'Wait for "{self.step(self.active_step_id).title}" to finish first')
        if step._state == "done" and not step.repeatable:
            raise StepError(f'"{step.title}" is already done')
        reasons = self._blockers(step)
        if reasons:
            raise StepError("; ".join(reasons))

    def _blockers(self, step: Step) -> list[str]:
        reasons = [f'Do "{required.title}" first' for required in self._unmet(step)]
        if step.check is not None and self._ctx is not None:
            reasons.extend(step.check(self._ctx, step))
        return reasons

    def _unmet(self, step: Step) -> list[Step]:
        """Prerequisites that are not done. A done prerequisite that is irreversible is looked through:
        a repeat further back could not turn it to "redo", so what it rests on must be done again first."""
        unmet, seen, pending = [], set(), list(step.requires)
        while pending:
            required = self._steps[pending.pop(0)]
            if required.id in seen:
                continue
            seen.add(required.id)
            if required._state != "done":
                unmet.append(required)
            elif required.irreversible:
                pending.extend(required.requires)
        return unmet

    def _can_repeat(self, step: Step) -> bool:
        return step.repeatable and not self._blockers(step)

    def _editable(self, step: Step) -> bool:
        return step.status in ("ready", "redo") or (step.status == "done" and self._can_repeat(step))

    def _view(self, step: Step) -> StepView:
        status = step.status
        pending = status in ("locked", "redo")
        editable = self._editable(step)
        return StepView(
            id=step.id, stage_id=step.stage_id, title=step.title, actor=step.actor, place=step.place,
            info=step.info, status=status, blocked_by=self._blockers(step) if pending else [],
            fields=[f.view(editable) for f in step.fields.values()], results=list(step.results),
            repeatable=step.repeatable and (status != "done" or self._can_repeat(step)),
            action_label=step.action_label)

    def _validate_references(self) -> None:
        for s in self._steps.values():
            for ref in (*s.requires, *s.invalidates):
                if ref not in self._steps:
                    raise ValueError(f'Step {s.id!r} refers to unknown step {ref!r}')
