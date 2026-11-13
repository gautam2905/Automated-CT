from pathlib import Path

import numpy as np
import pytest

from scansim.ct.dose import (
    ctdi_vol_mgy,
    dose_alerts,
    effective_mas,
    series_dose,
    table_feed_mm_s,
)
from scansim.scanner_spec import load_scanner

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec():
    return load_scanner(ROOT / "data" / "scanners" / "siemens_somatom_force.json")


def test_reference_size_gets_reference_mas(spec):
    assert effective_mas(np.array([spec.reference_dw_mm]), 147, spec)[0] == pytest.approx(147)


def test_larger_patient_gets_more(spec):
    m = effective_mas(np.array([250.0, 300.0, 350.0]), 147, spec)
    assert m[0] < m[1] < m[2]


def test_plus_50mm_gives_about_double(spec):
    m = effective_mas(np.array([spec.reference_dw_mm + 50.0]), 100, spec)[0]
    assert 150 <= m <= 250


def test_zero_strength_is_flat(spec):
    flat = spec.model_copy(update={"modulation_strength": 0.0})
    m = effective_mas(np.array([250.0, 400.0]), 147, flat)
    assert m == pytest.approx([147, 147])


def test_dlp_is_ctdi_times_length(spec):
    d = series_dose(np.full(50, spec.reference_dw_mm), 120, 147, 250.0, spec)
    assert d.dlp_mgycm == pytest.approx(d.ctdi_vol_mgy * 25.0) and 3 < d.ctdi_vol_mgy < 30


def test_series_profile_and_mean(spec):
    dw = np.linspace(250.0, 350.0, 10)
    d = series_dose(dw, 120, 147, 200.0, spec)
    assert d.eff_mas_profile.shape == (10,)
    assert d.mean_eff_mas == pytest.approx(d.eff_mas_profile.mean())


def test_calibration_matches_the_published_protocol(spec):
    assert ctdi_vol_mgy(120, 170, spec) == pytest.approx(13, rel=0.25)


def test_unknown_kv_rejected(spec):
    with pytest.raises(ValueError, match="kV"):
        ctdi_vol_mgy(121, 100, spec)


def test_empty_range_rejected(spec):
    with pytest.raises(ValueError):
        series_dose(np.array([]), 120, 147, 250.0, spec)


def test_alert_above_threshold(spec):
    assert dose_alerts(spec.dose_alert_ctdi_mgy + 1, spec) and not dose_alerts(1.0, spec)


def test_notification_only_between_thresholds(spec):
    a = dose_alerts(spec.dose_notification_ctdi_mgy + 1, spec)
    assert len(a) == 1 and "notification" in a[0].lower()


def test_feed():
    assert table_feed_mm_s(0.6, 57.6, 0.5) == pytest.approx(69.12)


def test_feed_rejects_nonpositive_rotation():
    with pytest.raises(ValueError):
        table_feed_mm_s(0.6, 57.6, 0.0)
