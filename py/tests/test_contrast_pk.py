"""Tests for the contrast model (research note 02 section D).

Anchors: https://pubs.rsna.org/doi/pdf/10.1148/rg.250192 (arrival 15-18 s at the abdominal
aorta, 12-15 s ascending aorta), https://doi.org/10.1148/radiology.206.2.9457200 (aortic peak at
injection duration plus arrival time), Heiken 1995 via
https://pubs.rsna.org/doi/full/10.1148/radiol.10090908 (liver 96 +/- 19 HU per g iodine per kg;
aortic rate effect about 2.5 times the liver effect), Bae 2010 Fig. 7 (lower cardiac output gives
later, higher peaks).
"""
import numpy as np
import pytest

from scansim.patient.contrast_pk import COMPARTMENTS, ContrastModel, InjectionSegment


def liver_protocol(model, start=0.0):
    model.add_segment(InjectionSegment(start, 125 / 4.0, 4.0, 350))
    model.add_segment(InjectionSegment(start + 125 / 4.0, 40 / 4.0, 4.0, 0))


def test_aorta_anchors():
    m = ContrastModel(75, 6.5); liver_protocol(m); t = np.arange(0, 400, 0.5); a = m.curve("aorta", t)
    assert 250 <= a.max() <= 400
    assert 31 <= t[a.argmax()] <= 50                 # injection duration (31.25 s) plus up to the arrival time
    assert 12 <= t[np.argmax(a >= 100)] <= 24        # 100 HU first reached; mean trigger time in the note is 16.1 s
    assert a[t < 10].max() < 5                       # nothing before arrival
    assert 60 <= m.enhancement("aorta", 240) <= 140  # still enhanced at 4 minutes


def test_liver_and_portal_anchors():
    m = ContrastModel(75, 6.5); liver_protocol(m); t = np.arange(0, 400, 0.5)
    liver, portal, aorta = m.curve("liver", t), m.curve("portal_vein", t), m.curve("aorta", t)
    assert 40 <= liver.max() <= 75 and 55 <= t[liver.argmax()] <= 95      # 43.75 g iodine / 75 kg -> about 56 HU
    assert 8 <= t[portal.argmax()] - t[aorta.argmax()] <= 35
    assert m.enhancement("liver", 35) < 0.6 * liver.max()                 # arterial phase: liver not yet enhanced


def test_heavier_patient_enhances_less():
    a, b = ContrastModel(60, 6.0), ContrastModel(100, 7.5); liver_protocol(a); liver_protocol(b)
    t = np.arange(0, 120, 0.5)
    assert a.curve("aorta", t).max() > 1.2 * b.curve("aorta", t).max()


def test_faster_injection_peaks_higher_and_earlier():
    slow, fast = ContrastModel(75, 6.5), ContrastModel(75, 6.5)
    slow.add_segment(InjectionSegment(0, 125 / 3.0, 3.0, 350)); fast.add_segment(InjectionSegment(0, 125 / 5.0, 5.0, 350))
    t = np.arange(0, 120, 0.5); s, f = slow.curve("aorta", t), fast.curve("aorta", t)
    assert f.max() > s.max() and t[f.argmax()] < t[s.argmax()]


def test_nothing_before_injection_and_never_negative():
    m = ContrastModel(75, 6.5); liver_protocol(m, start=100.0); t = np.arange(0, 600, 1.0)
    for c in COMPARTMENTS:
        y = m.curve(c, t); assert (y >= 0).all() and y[t < 100].max() == 0


def _peak(weight, co, rate, volume=125.0, comp="aorta"):
    m = ContrastModel(weight, co); m.add_segment(InjectionSegment(0, volume / rate, rate, 350))
    return m.curve(comp, np.arange(0, 300, 0.5)).max()


def test_liver_peak_per_gram_iodine_per_kg_is_within_published_range():
    for weight in (60, 75, 100):
        per_g_kg = _peak(weight, 6.5, 4.0, comp="liver") / (43.75 / weight)
        assert 77 <= per_g_kg <= 115                  # 96 +/- 19 HU per g/kg


def test_rate_effect_on_aorta_is_about_two_and_a_half_times_the_liver_effect():
    aorta = np.log(_peak(75, 6.5, 5.0) / _peak(75, 6.5, 3.0))
    liver = np.log(_peak(75, 6.5, 5.0, comp="liver") / _peak(75, 6.5, 3.0, comp="liver"))
    assert liver > 0 and 1.8 <= aorta / liver <= 3.5


def test_lower_cardiac_output_peaks_later_and_higher():
    t = np.arange(0, 300, 0.5)
    for comp in ("aorta", "liver"):
        curves = []
        for co in (6.5, 3.9):
            m = ContrastModel(75, co); liver_protocol(m); curves.append(m.curve(comp, t))
        assert curves[1].max() > curves[0].max() and curves[1].argmax() > curves[0].argmax()


def test_results_do_not_depend_on_call_order_or_segment_order():
    a, b = ContrastModel(75, 6.5), ContrastModel(75, 6.5)
    liver_protocol(a)
    b.add_segment(InjectionSegment(125 / 4.0, 40 / 4.0, 4.0, 0)); b.add_segment(InjectionSegment(0, 125 / 4.0, 4.0, 350))
    t = np.arange(0, 200, 1.0)
    first = b.enhancement("liver", 80.0)
    np.testing.assert_allclose(a.curve("spleen", t), b.curve("spleen", t))
    assert b.enhancement("liver", 80.0) == first == pytest.approx(float(a.curve("liver", np.array([80.0]))[0]))


def test_segment_added_later_changes_later_results():
    m = ContrastModel(75, 6.5)
    assert m.enhancement("aorta", 30) == 0
    m.add_segment(InjectionSegment(0, 20, 4.0, 350))
    assert m.enhancement("aorta", 30) > 0


def test_invalid_inputs_are_rejected_with_names():
    with pytest.raises(ValueError, match="weight_kg"):
        ContrastModel(0, 6.5)
    with pytest.raises(ValueError, match="cardiac_output_l_min"):
        ContrastModel(75, float("nan"))
    m = ContrastModel(75, 6.5)
    with pytest.raises(ValueError, match="rate_ml_s"):
        m.add_segment(InjectionSegment(0, 10, -1.0, 350))
    with pytest.raises(ValueError, match="aortaa"):
        m.enhancement("aortaa", 1.0)


# ---- an injection that ends early ----

def test_ending_delivery_early_equals_a_shorter_injection():
    stopped = ContrastModel(75, 6.5); liver_protocol(stopped); stopped.end_delivery_at(8.0)
    short = ContrastModel(75, 6.5); short.add_segment(InjectionSegment(0.0, 8.0, 4.0, 350))
    t = np.arange(0, 300, 1.0)
    for name in ("aorta", "liver", "portal_vein"):
        assert stopped.curve(name, t) == pytest.approx(short.curve(name, t))
    full = ContrastModel(75, 6.5); liver_protocol(full)
    assert stopped.enhancement("aorta", 35.0) < 0.3 * full.enhancement("aorta", 35.0)     # the bolus has passed
    # Later, what is left in the blood is in proportion to the iodine given: 8 s of 31.25 s.
    assert stopped.enhancement("aorta", 200.0) / full.enhancement("aorta", 200.0) == pytest.approx(8 / 31.25, rel=0.05)


def test_ending_delivery_leaves_completed_segments_alone_and_drops_ones_not_begun():
    done = ContrastModel(75, 6.5); liver_protocol(done)
    before = done.curve("aorta", np.arange(0, 300, 1.0))
    done.end_delivery_at(35.0)                       # the contrast phase ended at 31.25 s
    assert done.curve("aorta", np.arange(0, 300, 1.0)) == pytest.approx(before)
    none = ContrastModel(75, 6.5); liver_protocol(none, start=10.0); none.end_delivery_at(10.0)
    assert none.curve("aorta", np.arange(0, 300, 1.0)).max() == 0
    with pytest.raises(ValueError, match="time_s"):
        none.end_delivery_at(float("nan"))
