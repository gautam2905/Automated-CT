"""Dose model: tube-current adaptation, CTDIvol, DLP, dose alerts and table feed.

Pure functions; units are mm, s, mAs, mGy and mGy*cm.

Assumption (modulation mapping): ``spec.modulation_strength`` is a
dimensionless 0..1 setting. The per-millimetre exponent is
``k = strength * ln(2) / MM_PER_DOUBLING_AT_FULL_STRENGTH`` with
``MM_PER_DOUBLING_AT_FULL_STRENGTH = 25``, so at strength 0.5 a patient 50 mm
larger (water-equivalent diameter) than ``reference_dw_mm`` gets 2.0 times the
reference mAs, and strength 0 gives a flat mAs. Simulator tuning value, no source.

Sources: DLP = CTDIvol x scan length,
https://academy.siemens-healthineers.com/_/en-us/pediatric-dose-in-ctimaging ;
notification value 50 mGy (adult torso) and alert value 1000 mGy,
https://www.aapm.org/pubs/CTProtocols/documents/NotificationLevelsStatement.pdf
"""

from dataclasses import dataclass

import numpy as np

from scansim.scanner_spec import CTScannerSpec

MM_PER_DOUBLING_AT_FULL_STRENGTH = 25.0
MM_PER_CM = 10.0


@dataclass(frozen=True)
class SeriesDose:
    ctdi_vol_mgy: float
    dlp_mgycm: float
    mean_eff_mas: float
    eff_mas_profile: np.ndarray


def _strength_per_mm(spec: CTScannerSpec) -> float:
    return spec.modulation_strength * np.log(2.0) / MM_PER_DOUBLING_AT_FULL_STRENGTH


def effective_mas(dw_mm: np.ndarray, quality_ref_mas: float, spec: CTScannerSpec) -> np.ndarray:
    """Effective mAs per position: quality_ref_mas * exp(k * (dw - reference_dw))."""
    dw = np.asarray(dw_mm, dtype=float)
    return quality_ref_mas * np.exp(_strength_per_mm(spec) * (dw - spec.reference_dw_mm))


def ctdi_vol_mgy(kv: int, eff_mas: float, spec: CTScannerSpec) -> float:
    per_100 = spec.ctdi_mgy_per_100mas.get(str(kv))
    if per_100 is None:
        raise ValueError(f"no CTDIvol calibration for {kv} kV")
    return per_100 * eff_mas / 100.0


def series_dose(
    dw_mm_along_range: np.ndarray,
    kv: int,
    quality_ref_mas: float,
    length_mm: float,
    spec: CTScannerSpec,
) -> SeriesDose:
    dw = np.asarray(dw_mm_along_range, dtype=float)
    if dw.size == 0:
        raise ValueError("dw_mm_along_range must not be empty")
    if length_mm < 0:
        raise ValueError("length_mm must not be negative")
    profile = effective_mas(dw, quality_ref_mas, spec)
    mean_mas = float(profile.mean())
    ctdi = ctdi_vol_mgy(kv, mean_mas, spec)
    return SeriesDose(ctdi, ctdi * length_mm / MM_PER_CM, mean_mas, profile)


def dose_alerts(ctdi_vol_mgy: float, spec: CTScannerSpec) -> list[str]:
    """Messages for a planned or cumulative CTDIvol above the configured values."""
    alerts = []
    if ctdi_vol_mgy > spec.dose_notification_ctdi_mgy:
        alerts.append(
            f"Dose notification: CTDIvol {ctdi_vol_mgy:.1f} mGy exceeds the "
            f"notification value {spec.dose_notification_ctdi_mgy:g} mGy"
        )
    if ctdi_vol_mgy > spec.dose_alert_ctdi_mgy:
        alerts.append(
            f"Dose alert: CTDIvol {ctdi_vol_mgy:.1f} mGy exceeds the "
            f"alert value {spec.dose_alert_ctdi_mgy:g} mGy"
        )
    return alerts


def table_feed_mm_s(pitch: float, collimation_mm: float, rotation_s: float) -> float:
    if rotation_s <= 0:
        raise ValueError("rotation_s must be positive")
    return pitch * collimation_mm / rotation_s
