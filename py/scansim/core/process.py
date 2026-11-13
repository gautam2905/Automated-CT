"""Cooperative scheduler for step routines written as Python generators.

A routine yields `Sleep(seconds)`, `Until(predicate, timeout_s)` or `Tick()`; nested generators
are used through `yield from`. The scheduler advances the simulation clock in sub-steps
of at most `MAX_SUBSTEP_S`.
"""
import math
from typing import Callable, Generator, Optional

from scansim.core.clock import SimClock

MAX_SUBSTEP_S = 0.02
_EPS = 1e-9


class StepError(ValueError):
    """An expected refusal: the step or process cannot continue, and the message is shown to the user.

    Defined here so the scheduler can tell it from a programming error; `steps.py` re-exports it.
    """


class ProcessTimeout(Exception):
    """Thrown into a routine whose `Until` wait ran out of time."""


def _check_duration(value: float, what: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{what} must be a finite, non-negative number of seconds")
    return float(value)


class Sleep:
    def __init__(self, seconds: float) -> None:
        self.seconds = _check_duration(seconds, "Sleep duration")


class Until:
    def __init__(self, predicate: Callable[[], bool], timeout_s: Optional[float] = None) -> None:
        self.predicate = predicate
        self.timeout_s = None if timeout_s is None else _check_duration(timeout_s, "Until timeout")


class Tick:
    """Yield to be resumed on the next sub-step; the generator receives that sub-step's duration."""


class ProcessHandle:
    def __init__(self, name: str) -> None:
        self.name = name
        self.done = False
        self.error: Optional[BaseException] = None


class _Process:
    def __init__(self, gen: Generator, handle: ProcessHandle) -> None:
        self.gen = gen
        self.handle = handle
        self.wait: object = None
        self.wake_at_s: Optional[float] = None
        self.base_s: Optional[float] = None    # previous wake time while a Sleep chains into the next


class Scheduler:
    """Errors: a `StepError` or `ProcessTimeout` that ends a process is logged as an alert (if there is a
    log) and the process ends. Any other exception is a programming error: the process ends and the
    exception is re-raised from `start` (before the first wait) or from `advance` (after that sub-step's
    other processes have been ticked)."""

    def __init__(self, clock: SimClock, log=None) -> None:
        self.clock = clock
        self.log = log
        self.foreground: Optional[ProcessHandle] = None
        self._procs: list[_Process] = []
        self._errors: list[BaseException] = []

    def start(self, gen: Generator, *, name: str, foreground: bool = False) -> ProcessHandle:
        """Run `gen` at once up to its first wait and keep it alive until it finishes."""
        handle = ProcessHandle(name)
        proc = _Process(gen, handle)
        if foreground:
            self.foreground = handle
        self._procs.append(proc)
        known = len(self._errors)
        self._resume(proc)
        if len(self._errors) > known:
            raise self._errors.pop()
        return handle

    def advance(self, dt_s: float) -> None:
        _check_duration(dt_s, "Time step")
        if dt_s == 0:
            return
        n = max(1, math.ceil(dt_s / MAX_SUBSTEP_S - _EPS))
        sub_s = dt_s / n
        for _ in range(n):
            self.clock.advance(sub_s)
            for proc in list(self._procs):
                if not proc.handle.done:
                    self._tick(proc, sub_s)
            if self._errors:
                raise self._errors.pop(0)

    def cancel(self, handle: ProcessHandle) -> None:
        """Close the generator so its `finally` blocks run, then mark the handle done."""
        for proc in self._procs:
            if proc.handle is handle and not handle.done:
                try:
                    proc.gen.close()
                finally:
                    self._finish(proc)
                return

    def _tick(self, proc: _Process, sub_s: float) -> None:
        wait, now = proc.wait, self.clock.now_s
        if isinstance(wait, Tick):
            self._resume(proc, dt=sub_s)
        elif isinstance(wait, Sleep):
            if now >= proc.wake_at_s - _EPS:
                proc.base_s = proc.wake_at_s
                self._resume(proc, dt=sub_s)
        elif isinstance(wait, Until):
            self._tick_until(proc, wait, now, sub_s)

    def _tick_until(self, proc: _Process, wait: Until, now: float, sub_s: float) -> None:
        try:
            ready = wait.predicate()
        except Exception as err:
            self._resume(proc, err)
            return
        if ready:
            self._resume(proc, dt=sub_s)
        elif proc.wake_at_s is not None and now >= proc.wake_at_s - _EPS:
            self._resume(proc, ProcessTimeout(f"{proc.handle.name}: wait timed out"))

    def _resume(self, proc: _Process, exc: Optional[BaseException] = None, dt: Optional[float] = None) -> None:
        while True:
            try:
                wait = proc.gen.throw(exc) if exc is not None else proc.gen.send(dt)
            except StopIteration:
                self._finish(proc)
                return
            except Exception as err:
                self._fail(proc, err)
                return
            exc = self._arm(proc, wait)
            if exc is None:
                return
            dt = None

    def _arm(self, proc: _Process, wait: object) -> Optional[BaseException]:
        """Arm the wait; return a TypeError to throw into the generator if it yielded something else."""
        now = self.clock.now_s
        base, proc.base_s = proc.base_s, None
        if isinstance(wait, Sleep):
            proc.wake_at_s = (now if base is None else base) + wait.seconds
        elif isinstance(wait, Until):
            proc.wake_at_s = None if wait.timeout_s is None else now + wait.timeout_s
        elif not isinstance(wait, Tick):
            return TypeError(f"{proc.handle.name} yielded {wait!r}; expected Sleep, Until or Tick")
        proc.wait = wait
        return None

    def _fail(self, proc: _Process, err: Exception) -> None:
        proc.handle.error = err
        self._finish(proc)
        if isinstance(err, (StepError, ProcessTimeout)):
            if self.log is not None:
                self.log.add("alert", str(err))
        else:
            self._errors.append(err)

    def _finish(self, proc: _Process) -> None:
        proc.handle.done = True
        if proc in self._procs:
            self._procs.remove(proc)
        if self.foreground is proc.handle:
            self.foreground = None


def move_linear(get: Callable[[], float], set_: Callable[[float], None],
                target: float, speed_per_s: float) -> Generator:
    """Move a value toward `target` at a constant speed, landing on it exactly."""
    if speed_per_s <= 0:
        raise ValueError("Speed must be positive")
    while True:
        dt = yield Tick()
        step = speed_per_s * dt
        remaining = target - get()
        if abs(remaining) <= step + _EPS:
            set_(target)
            return
        set_(get() + math.copysign(step, remaining))
