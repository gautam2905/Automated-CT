"""Contrast power injector.

The injector is a device with a strict step order:
unloaded -> loaded -> purged -> connected -> armed -> injecting -> done.
A call made out of order raises `InjectorError` naming the step that is missing.

`run` delivers the programmed phases over simulated time. At the start of each phase it
announces an `InjectionSegment` to the body's contrast model, then delivers the volume
in steps of at most `STEP_S`. If the injection is stopped or aborted before a phase is
complete, `on_cut` is told the time up to which fluid was really delivered, so that the
model can shorten the segment it was given.

ASSUMPTIONS (research note 02 section B found no published default pressure limit and no
per-gauge flow table, so these are not sourced. The page says so: the Contrast tab labels the
pressure and its limit "assumed", and the step results that quote them say the same):
  - the pressure limit passed by the caller (the project uses 325 psi);
  - `GAUGE_K_PSI`: pressure coefficient per cannula gauge, psi per (mL/s)^2;
  - `VISCOSITY`: relative viscosity of contrast and of saline;
  - the model itself: pressure = k[gauge] * rate^2 * viscosity[fluid];
  - `TEST_INJECT_RATE_ML_S`: the test injection runs at 2 mL/s;
  - `STEP_S`: the 0.25 s delivery step.
The constants are chosen so that 20g at 4 mL/s of contrast stays under 325 psi and 22g at
5 mL/s of contrast exceeds it (the rate is then reduced to hold the limit, with one alert).

Known limitations:
  - a test injection takes its saline from the loaded saline, but does not count as
    injected saline;
  - an injection that is stopped or aborted ends in the state `done`, like one that ran to the end.
"""
import math
from dataclasses import dataclass
from typing import Callable, Generator, Optional

from scansim.core.clock import SimClock
from scansim.core.events import EventLog
from scansim.core.process import Sleep
from scansim.core.steps import StepError
from scansim.patient.contrast_pk import InjectionSegment
from scansim.snapshot import InjectorView

STEP_S = 0.25
TEST_INJECT_RATE_ML_S = 2.0
GAUGE_K_PSI = {"18g": 3.0, "20g": 8.0, "22g": 16.0}
VISCOSITY = {"contrast": 1.0, "saline": 0.4}

_ORDER = ["unloaded", "loaded", "purged", "connected", "armed", "injecting", "done"]
_NEXT_STEP = {"unloaded": "load", "loaded": "purge", "purged": "connect",
              "connected": "arm", "armed": "run", "injecting": "stop", "done": "load"}


class InjectorError(StepError):
    """The injector cannot do what was asked in its current state."""


@dataclass(frozen=True)
class InjectorPhase:
    fluid: str  # "contrast" or "saline"
    volume_ml: float
    rate_ml_s: float


class Injector:
    def __init__(self, clock: SimClock, log: EventLog, *, pressure_limit_psi: float) -> None:
        if not pressure_limit_psi > 0:
            raise ValueError("The pressure limit must be above 0 psi")
        self._clock = clock
        self._log = log
        self._limit = float(pressure_limit_psi)
        self.state = "unloaded"
        self.started_at_s: Optional[float] = None
        self._contrast_ml = 0.0
        self._saline_ml = 0.0
        self._iodine = 0.0
        self._gauge: Optional[str] = None
        self._phases: list[InjectorPhase] = []
        self._flow = 0.0
        self._pressure = 0.0
        self._inj_contrast = 0.0
        self._inj_saline = 0.0
        self._alerted = False
        self._on_cut: Optional[Callable[[float], None]] = None
        self._delivered_to_s = 0.0          # time up to which the running phase has really been delivered

    # ----- setup steps -----
    def _require(self, action: str, *allowed: str) -> None:
        if self.state in allowed:
            return
        if _ORDER.index(self.state) < _ORDER.index(allowed[0]):
            raise InjectorError(
                f"Cannot {action}: the injector is {self.state}; do '{_NEXT_STEP[self.state]}' first")
        raise InjectorError(f"Cannot {action}: the injector is already {self.state}")

    def load(self, contrast_ml: float, saline_ml: float, iodine_mg_ml: float) -> None:
        self._require("load", "unloaded", "done")
        if not (math.isfinite(contrast_ml) and contrast_ml >= 0 and math.isfinite(saline_ml)
                and saline_ml >= 0 and math.isfinite(iodine_mg_ml) and iodine_mg_ml > 0):
            raise InjectorError("Load needs contrast and saline volumes of 0 mL or more and an iodine "
                                "concentration above 0 mg/mL")
        self._contrast_ml, self._saline_ml, self._iodine = float(contrast_ml), float(saline_ml), float(iodine_mg_ml)
        self._inj_contrast = self._inj_saline = 0.0
        self._phases, self._gauge, self.started_at_s = [], None, None
        self._alerted = False
        self.state = "loaded"
        self._log.add("event", f"Injector loaded: {contrast_ml:g} mL contrast ({iodine_mg_ml:g} mgI/mL), {saline_ml:g} mL saline")

    def purge(self) -> None:
        self._require("purge", "loaded")
        self.state = "purged"
        self._log.add("event", "Injector purged of air")

    def connect(self, gauge: str) -> None:
        self._require("connect", "purged")
        if gauge not in GAUGE_K_PSI:
            raise InjectorError(f"Unknown cannula gauge '{gauge}'; use one of {', '.join(GAUGE_K_PSI)}")
        self._gauge = gauge
        self.state = "connected"
        self._log.add("event", f"Injector connected to a {gauge} cannula")

    def program(self, phases: list[InjectorPhase]) -> None:
        self._require("program", "connected")
        if not phases:
            raise InjectorError("Program needs at least one phase")
        totals = {"contrast": 0.0, "saline": 0.0}
        for p in phases:
            if p.fluid not in totals:
                raise InjectorError(f"Unknown fluid '{p.fluid}'; use contrast or saline")
            if not (math.isfinite(p.volume_ml) and p.volume_ml > 0 and math.isfinite(p.rate_ml_s) and p.rate_ml_s > 0):
                raise InjectorError("Each phase needs a volume and a rate above 0")
            totals[p.fluid] += p.volume_ml
        if totals["contrast"] > self._contrast_ml + 1e-9 or totals["saline"] > self._saline_ml + 1e-9:
            raise InjectorError(
                f"Programmed {totals['contrast']:g} mL contrast and {totals['saline']:g} mL saline, but only "
                f"{self._contrast_ml:g} mL and {self._saline_ml:g} mL are loaded")
        self._phases = list(phases)

    def arm(self) -> None:
        self._require("arm", "connected")
        if not self._phases:
            raise InjectorError("Cannot arm: program the injection phases first")
        self.state = "armed"
        self._log.add("event", "Injector armed")

    # ----- pressure model -----
    def _pressure_at(self, fluid: str, rate: float) -> float:
        return GAUGE_K_PSI[self._gauge] * rate * rate * VISCOSITY[fluid]

    def _delivered_rate(self, fluid: str, rate: float) -> float:
        if self._pressure_at(fluid, rate) <= self._limit:
            return rate
        held = math.sqrt(self._limit / (GAUGE_K_PSI[self._gauge] * VISCOSITY[fluid]))
        if not self._alerted:
            self._alerted = True
            self._log.add("alert", f"Pressure limit {self._limit:g} psi: rate reduced from {rate:g} to {held:.2f} mL/s")
        return held

    # ----- delivery -----
    def _deliver(self, fluid: str, volume: float, rate: float) -> Generator:
        """Deliver `volume` at `rate`; returns the peak pressure. Stops early if the state leaves `injecting`."""
        self._flow = rate
        self._pressure = self._pressure_at(fluid, rate)
        duration = volume / rate
        elapsed, started = 0.0, self._clock.now_s
        self._delivered_to_s = started
        while elapsed < duration - 1e-9:
            dt = min(STEP_S, duration - elapsed)
            yield Sleep(dt)
            if self.state != "injecting":
                return self._pressure
            elapsed += dt
            self._add_volume(fluid, rate * dt)
            self._delivered_to_s = started + elapsed
        return self._pressure

    def _add_volume(self, fluid: str, ml: float) -> None:
        if fluid == "contrast":
            ml = min(ml, self._contrast_ml)
            self._contrast_ml -= ml
            self._inj_contrast += ml
        else:
            ml = min(ml, self._saline_ml)
            self._saline_ml -= ml
            self._inj_saline += ml

    def run(self, on_segment: Callable[[InjectionSegment], None],
            on_cut: Optional[Callable[[float], None]] = None) -> Generator:
        self._require("run the injection", "armed")
        self.state = "injecting"
        self.started_at_s = self._delivered_to_s = self._clock.now_s
        self._on_cut = on_cut
        self._log.add("event", "Injection started")
        try:
            for phase in self._phases:
                rate = self._delivered_rate(phase.fluid, phase.rate_ml_s)
                iodine = self._iodine if phase.fluid == "contrast" else 0.0
                on_segment(InjectionSegment(self._clock.now_s, phase.volume_ml / rate, rate, iodine))
                yield from self._deliver(phase.fluid, phase.volume_ml, rate)
                if self.state != "injecting":
                    return
            self.state = "done"
            self._log.add("event", "Injection finished")
        finally:
            self._flow = self._pressure = 0.0
            if self.state == "injecting":  # generator closed or on_segment raised
                self.state = "done"
                self._log.add("alert", "Injection aborted")
                self._cut()

    def stop(self) -> None:
        self._require("stop", "injecting")
        self._flow = self._pressure = 0.0
        self.state = "done"
        self._log.add("event", "Injection stopped early")
        self._cut()

    def _cut(self) -> None:
        """Tell the listener that delivery ended early, at the time the delivered volume corresponds to."""
        if self._on_cut is not None:
            self._on_cut(self._delivered_to_s)

    def test_inject(self, saline_ml: float = 10.0) -> Generator:
        """Saline test injection at 2 mL/s. The state stays `connected`; returns the peak pressure."""
        self._require("test inject", "connected")
        if not (math.isfinite(saline_ml) and saline_ml > 0) or saline_ml > self._saline_ml + 1e-9:
            raise InjectorError(f"Test injection of {saline_ml:g} mL needs 0 to {self._saline_ml:g} mL of saline loaded")
        rate = self._delivered_rate("saline", TEST_INJECT_RATE_ML_S)
        self._flow = rate
        self._pressure = peak = self._pressure_at("saline", rate)
        try:
            yield Sleep(saline_ml / rate)
            self._saline_ml -= saline_ml
        finally:
            self._flow = self._pressure = 0.0
        self._log.add("event", f"Test injection {saline_ml:g} mL saline, peak {peak:.0f} psi")
        return peak

    def view(self) -> InjectorView:
        return InjectorView(
            state=self.state, contrast_ml=self._contrast_ml, saline_ml=self._saline_ml,
            flow_ml_s=self._flow, pressure_psi=self._pressure, pressure_limit_psi=self._limit,
            injected_contrast_ml=self._inj_contrast, injected_saline_ml=self._inj_saline)
