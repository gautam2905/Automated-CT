"""Contrast enhancement over time in the body (research note 02 section D).

The full Bae compartment constants (permeability, renal clearance) are unconfirmed in the
note, so each compartment is modelled as a linear, time-invariant response: the iodine delivery
rate (mg/s) is convolved with a transit function (a delayed gamma variate plus an equilibrium
tail that rises after the first pass and is cleared slowly) and scaled by an iodine-to-HU
factor, dilution by blood flow and weight. Every segment is reduced to a closed form using the
cached step response of each transit function, so a call costs two interpolations per segment.

Known simplification: the portal-vein and liver peaks (about 65 s and 70 s for the 31 s liver
protocol) come earlier than the roughly 102 s portal peak of the clinical series in research
note 02 section D.

Every parameter lives in GLOBAL_PARAMS (shared constants) or PARAMS (per compartment), each
with a source URL or the word "fitted".

Units: seconds, mL, mL/s, mg iodine/mL, kg, HU above baseline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

COMPARTMENTS = ("aorta", "portal_vein", "liver", "veins", "kidney", "spleen", "pancreas", "heart", "soft_tissue")

NOTE = "research note 02 section D"
BAE_2010 = "https://pubs.rsna.org/doi/full/10.1148/radiol.10090908"
RG_2026 = "https://pubs.rsna.org/doi/pdf/10.1148/rg.250192"
SAHBAEE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC4720919"


@dataclass(frozen=True)
class GlobalParam:
    value: float
    source: str


# Shared constants. Each has a source URL or "fitted".
GLOBAL_PARAMS: Dict[str, GlobalParam] = {
    "hu_per_mg_ml": GlobalParam(26.18, BAE_2010 + " Fig. 1 (120 kVp; 100 kVp 31.74, 80 kVp 41.12)"),
    "co_ref_l_min": GlobalParam(6.5, SAHBAEE + " Table 1 (108.3 mL/s)"),
    "ref_rate_ml_s": GlobalParam(4.0, "fitted (reference injection rate for dilution normalisation)"),
    "weight_ref_kg": GlobalParam(75.0, "fitted (weight at which the gains are quoted)"),
    "grid_dt_s": GlobalParam(0.25, "fitted (step-response grid spacing)"),
    "grid_end_s": GlobalParam(1800.0, "fitted (step response held constant beyond this time)"),
    "blood_eq_level_per_s": GlobalParam(0.0075, "derived from " + SAHBAEE + " Table 1 flows, 108.3 mL/s over an assumed 15 L; volume fitted"),
    "clear_s": GlobalParam(7200.0, "fitted (renal clearance time constant; Bae constants unconfirmed in " + NOTE + ")"),
}
HU_PER_MG_ML = GLOBAL_PARAMS["hu_per_mg_ml"].value
CO_REF_L_MIN = GLOBAL_PARAMS["co_ref_l_min"].value
REF_RATE_ML_S = GLOBAL_PARAMS["ref_rate_ml_s"].value
WEIGHT_REF_KG = GLOBAL_PARAMS["weight_ref_kg"].value
GRID_DT_S = GLOBAL_PARAMS["grid_dt_s"].value
GRID_END_S = GLOBAL_PARAMS["grid_end_s"].value
_BLOOD_EQ = GLOBAL_PARAMS["blood_eq_level_per_s"].value
_CLEAR_S = GLOBAL_PARAMS["clear_s"].value

# Per compartment: gain is HU per (mg/mL) of local iodine relative to the aorta first pass;
# enhancement scales with (WEIGHT_REF/weight)^weight_exp; the first-pass dilution is
# ((CO_ref + REF_RATE)/(CO+rate))^rate_exp / (CO_ref + REF_RATE) with rate_exp 1 for arteries and
# 0.4 for the liver (the aorta is about 2.5 times as rate-sensitive as the liver, NOTE) and an
# extra (CO_ref/CO)^co_extra so that lower cardiac output still raises the liver peak. Delay and
# widths stretch by CO_ref/CO.
# The transit function is a delayed gamma variate plus an equilibrium tail: after the first pass
# iodine equilibrates in blood and extracellular fluid, level eq_level (1/s, about
# CO/distribution volume = 108 mL/s / 15 L = 0.007/s for blood), rising over eq_rise_s and
# cleared with time constant eq_clear_s.
@dataclass(frozen=True)
class CompartmentParams:
    gain: float
    weight_exp: float
    rate_exp: float
    co_extra: float
    delay_s: float
    shape: float
    scale_s: float
    eq_level: float
    eq_delay_s: float
    eq_rise_s: float
    eq_clear_s: float
    source: str


PARAMS: Dict[str, CompartmentParams] = {
    # arrival 15-18 s at the abdominal aorta, 12-15 s ascending aorta (RG_2026); peak ~330 HU matches the derived estimate in NOTE
    "aorta": CompartmentParams(1.0, 0.7, 1.0, 0.0, 14.0, 2.0, 2.0, _BLOOD_EQ, 25.0, 30.0, _CLEAR_S, "arrival: " + RG_2026 + "; rest fitted"),
    "heart": CompartmentParams(1.0, 0.7, 1.0, 0.0, 10.0, 2.0, 2.0, _BLOOD_EQ, 21.0, 30.0, _CLEAR_S, "arrival: " + RG_2026 + "; rest fitted"),
    "portal_vein": CompartmentParams(0.55, 0.9, 0.6, 0.0, 28.0, 3.0, 8.0, _BLOOD_EQ, 40.0, 40.0, _CLEAR_S, "fitted (portal flow 23.8 mL/s: " + SAHBAEE + ")"),
    "liver": CompartmentParams(0.24, 1.0, 0.4, 0.8, 30.0, 3.0, 10.0, 0.003, 40.0, 60.0, _CLEAR_S, "per g/kg and 2.5x rule: Heiken 1995 via " + BAE_2010 + "; rest fitted"),
    "veins": CompartmentParams(0.3, 0.9, 0.6, 0.0, 40.0, 3.0, 12.0, _BLOOD_EQ, 60.0, 40.0, _CLEAR_S, "fitted"),
    "kidney": CompartmentParams(0.6, 0.8, 0.8, 0.0, 18.0, 2.0, 6.0, 0.012, 30.0, 60.0, 1800.0, "fitted"),
    "spleen": CompartmentParams(0.45, 0.9, 0.8, 0.0, 17.0, 2.0, 6.0, 0.004, 40.0, 60.0, _CLEAR_S, "fitted"),
    "pancreas": CompartmentParams(0.35, 0.9, 0.8, 0.0, 17.0, 2.0, 5.0, 0.003, 40.0, 60.0, _CLEAR_S, "peak ~120 HU late arterial: https://pmc.ncbi.nlm.nih.gov/articles/PMC8173674; rest fitted"),
    "soft_tissue": CompartmentParams(0.06, 0.9, 0.6, 0.0, 40.0, 2.0, 40.0, 0.001, 60.0, 90.0, _CLEAR_S, "fitted"),
}


@dataclass(frozen=True)
class InjectionSegment:
    start_s: float
    duration_s: float
    rate_ml_s: float
    iodine_mg_ml: float  # 0 for saline


_GRID_T = np.arange(0.0, GRID_END_S + GRID_DT_S, GRID_DT_S)


def _gamma_pdf(t: np.ndarray, delay: float, shape: float, scale: float) -> np.ndarray:
    x = np.clip(t - delay, 0.0, None)
    out = x ** (shape - 1.0) * np.exp(-x / scale) / (math.gamma(shape) * scale ** shape)
    return np.where(t > delay, out, 0.0)


def _step_response(p: CompartmentParams, time_stretch: float) -> np.ndarray:
    """Cumulative integral of the transit function on the grid."""
    t = _GRID_T
    h = _gamma_pdf(t, p.delay_s * time_stretch, p.shape, p.scale_s * time_stretch)
    x = np.clip(t - p.eq_delay_s * time_stretch, 0.0, None)
    h = h + p.eq_level * (1.0 - np.exp(-x / (p.eq_rise_s * time_stretch))) * np.exp(-t / p.eq_clear_s)
    return np.concatenate(([0.0], np.cumsum((h[1:] + h[:-1]) * 0.5 * GRID_DT_S)))


def _require_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return float(value)


class ContrastModel:
    def __init__(self, weight_kg: float, cardiac_output_l_min: float):
        self.weight_kg = _require_positive("weight_kg", weight_kg)
        self.cardiac_output_l_min = _require_positive("cardiac_output_l_min", cardiac_output_l_min)
        self._co_ml_s = self.cardiac_output_l_min * 1000.0 / 60.0
        stretch = CO_REF_L_MIN / self.cardiac_output_l_min
        self._steps = {c: _step_response(PARAMS[c], stretch) for c in COMPARTMENTS}
        # per compartment: list of (start_s, end_s, amplitude HU) with amplitude = gain * delivery rate
        self._segments: Dict[str, List[Tuple[float, float, float]]] = {c: [] for c in COMPARTMENTS}

    def _amplitude(self, comp: str, seg: InjectionSegment) -> float:
        p = PARAMS[comp]
        ref = self._co_ml_s_ref() + REF_RATE_ML_S
        dilution = (ref ** (p.rate_exp - 1.0)) / (self._co_ml_s + seg.rate_ml_s) ** p.rate_exp
        dilution *= (CO_REF_L_MIN / self.cardiac_output_l_min) ** p.co_extra
        weight = (WEIGHT_REF_KG / self.weight_kg) ** p.weight_exp
        return p.gain * HU_PER_MG_ML * weight * dilution * seg.rate_ml_s * seg.iodine_mg_ml

    @staticmethod
    def _co_ml_s_ref() -> float:
        return CO_REF_L_MIN * 1000.0 / 60.0

    def add_segment(self, seg: InjectionSegment) -> None:
        for name in ("start_s", "duration_s", "rate_ml_s", "iodine_mg_ml"):
            value = getattr(seg, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or (name != "start_s" and value < 0):
                raise ValueError(f"{name} must be a finite number{'' if name == 'start_s' else ' >= 0'}, got {value!r}")
        if seg.duration_s == 0 or seg.rate_ml_s == 0 or seg.iodine_mg_ml == 0:
            return  # saline and empty segments carry no iodine in this linear model
        for comp in COMPARTMENTS:
            self._segments[comp].append((seg.start_s, seg.start_s + seg.duration_s, self._amplitude(comp, seg)))

    def end_delivery_at(self, time_s: float) -> None:
        """The injection ended early at `time_s`: no announced segment delivers anything after that time."""
        if not isinstance(time_s, (int, float)) or not math.isfinite(time_s):
            raise ValueError(f"time_s must be a finite number, got {time_s!r}")
        for comp in COMPARTMENTS:
            self._segments[comp] = [(start, min(end, time_s), amp)
                                    for start, end, amp in self._segments[comp] if start < time_s]

    def curve(self, compartment: str, t: np.ndarray) -> np.ndarray:
        if compartment not in self._steps:
            raise ValueError(f"unknown compartment {compartment!r}; expected one of {COMPARTMENTS}")
        t = np.asarray(t, dtype=float)
        step, total = self._steps[compartment], np.zeros(t.shape)
        for start, end, amp in self._segments[compartment]:
            total += amp * (np.interp(t - start, _GRID_T, step, left=0.0) - np.interp(t - end, _GRID_T, step, left=0.0))
        return np.where(t >= self._first_start(compartment), np.clip(total, 0.0, None), 0.0)

    def _first_start(self, compartment: str) -> float:
        segs = self._segments[compartment]
        return min((s[0] for s in segs), default=math.inf)

    def enhancement(self, compartment: str, t_s: float) -> float:
        return float(self.curve(compartment, np.asarray(t_s))[()])
