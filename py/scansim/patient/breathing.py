"""Breathing model: quiet breathing, breath-hold on command, release.

``value`` runs from -1 (full expiration) to +1 (full inspiration). Quiet breathing is a sine of
amplitude ``QUIET_AMPLITUDE``. The engine calls ``advance(dt_s)`` every tick; ``hold()`` is a
generator run by the scheduler.

Assumptions: quiet amplitude 0.35, 1.5 s ramp into a hold and 2 s ease back out, and the 25 s
default ``max_hold_s`` (no sourced figure exists for CT breath-hold limits).
"""
from __future__ import annotations

import math
from typing import Generator

from scansim.core.process import Sleep

QUIET_AMPLITUDE = 0.35
HOLD_RAMP_S = 1.5
RELEASE_EASE_S = 2.0
RAMP_STEP_S = 0.02
_PHASE_TARGET = {"inspiration": 1.0, "expiration": -1.0}


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


class Breathing:
    def __init__(self, period_s: float = 4.0, max_hold_s: float = 25.0) -> None:
        if period_s <= 0 or max_hold_s <= 0:
            raise ValueError("period_s and max_hold_s must be positive")
        self.period_s = period_s
        self.max_hold_s = max_hold_s
        self.value = 0.0
        self.holding = False
        self.broke_hold = False
        self._mode = "quiet"          # quiet | ramp | hold | release
        self._quiet_t_s = 0.0
        self._hold_t_s = 0.0
        self._ease_t_s = 0.0
        self._ease_from = 0.0

    def _quiet_value(self) -> float:
        return QUIET_AMPLITUDE * math.sin(2.0 * math.pi * self._quiet_t_s / self.period_s)

    def advance(self, dt_s: float) -> None:
        if dt_s < 0:
            raise ValueError("Cannot advance by a negative time")
        if self._mode in ("quiet", "release"):
            self._quiet_t_s += dt_s
        if self._mode == "quiet":
            self.value = self._quiet_value()
        elif self._mode == "release":
            self._ease_t_s += dt_s
            frac = _smoothstep(self._ease_t_s / RELEASE_EASE_S)
            self.value = self._ease_from + (self._quiet_value() - self._ease_from) * frac
            if self._ease_t_s >= RELEASE_EASE_S:
                self._mode = "quiet"
        elif self._mode == "hold":
            self._hold_t_s += dt_s
            if self._hold_t_s > self.max_hold_s:
                self.broke_hold = True
                self._begin_release()

    def hold(self, phase: str = "inspiration") -> Generator:
        if phase not in _PHASE_TARGET:
            raise ValueError(f"phase must be 'inspiration' or 'expiration', not {phase!r}")
        target = _PHASE_TARGET[phase]
        self.broke_hold = False
        self.holding = False
        self._mode = "ramp"
        start, elapsed = self.value, 0.0
        while elapsed < HOLD_RAMP_S:
            yield Sleep(RAMP_STEP_S)
            if self._mode != "ramp":      # released during the ramp
                return
            elapsed += RAMP_STEP_S
            self.value = start + (target - start) * _smoothstep(elapsed / HOLD_RAMP_S)
        self.value = target
        self._hold_t_s = 0.0
        self._mode = "hold"
        self.holding = True

    def release(self) -> None:
        if self._mode in ("ramp", "hold"):
            self._begin_release()

    def _begin_release(self) -> None:
        self.holding = False
        self._mode = "release"
        self._ease_t_s = 0.0
        self._ease_from = self.value
