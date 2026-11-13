import numpy as np
import pytest
from helpers import ORDER, perform_all, png_array, steps


def test_full_exam(session, pack):
    perform_all(session, pack)
    snap = session.snapshot(); st = steps(snap)
    assert [s for s in ORDER if st[s].status != "done"] == []
    ser = {s.id: s for s in snap.console.series}; tr = snap.console.tracking
    assert all(ser[k].status == "done" for k in ("noncontrast", "arterial", "venous", "delayed"))
    inj_start = snap.clock.sim_time_s - snap.clock.contrast_timer_s
    assert tr.state == "triggered" and 10 <= tr.triggered_at_s - inj_start <= 30
    assert tr.samples[-1].hu >= tr.baseline_hu + tr.threshold_hu
    assert ser["venous"].started_at_s - tr.triggered_at_s == pytest.approx(55, abs=1.0)
    assert ser["delayed"].started_at_s - inj_start == pytest.approx(240, abs=1.0)
    assert ser["arterial"].started_at_s > tr.triggered_at_s
    assert snap.injector.state == "done" and snap.injector.injected_contrast_ml == pytest.approx(125)
    assert snap.pose.stage == "away" and snap.table.long_mm == 0 and snap.room.door_open
    assert 30 * 60 < snap.clock.sim_time_s < 90 * 60 and snap.console.dose.total_dlp_mgycm > 100


def test_phases_look_different(session, pack):
    perform_all(session, pack)
    k = lambda sid: png_array(session.series_png(sid, "axial", 40)).astype(float)
    assert np.abs(k("arterial") - k("noncontrast")).mean() > 1.0
    assert np.abs(k("venous") - k("arterial")).mean() > 0.5


def test_region_off_the_aorta_never_triggers_but_exam_completes(session, pack):
    perform_all(session, pack, roi_on_aorta=False)
    snap = session.snapshot(); ser = {s.id: s for s in snap.console.series}
    assert snap.console.tracking.state == "missed" and ser["arterial"].status == "missed"
    assert any(e.kind == "alert" and "trigger" in e.text.lower() for e in snap.log)
    assert ser["venous"].status == "done" and steps(snap)["close_exam"].status == "done"
