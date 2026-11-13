"""The monitoring level, and what a Stop leaves behind: the contrast given, the dose and the images."""
import pytest
from helpers import ORDER, do, perform_until, steps


def _set(session, step_id, key, value):
    return session.dispatch({"type": "set_field", "step_id": step_id, "key": key, "value": value})


def _field(session, step_id, key):
    return next(f for f in steps(session.snapshot())[step_id].fields if f.key == key)


def _series(session):
    return {s.id: s for s in session.snapshot().console.series}


def _run_until(session, condition, seconds=300.0, dt=0.05):
    for _ in range(int(seconds / dt)):
        session.advance(dt)
        if condition(session.snapshot()):
            return True
    return False


def _reconstructing(series_id):
    """The sweep is over (the series is done) but its step is still waiting for the images."""
    return lambda snap: ({s.id: s for s in snap.console.series}[series_id].status == "done"
                         and snap.active_step_id is not None)


@pytest.fixture
def on_aorta(session, pack):
    perform_until(session, pack, "arm_injector", roi_on_aorta=True)
    return session


# ---- the monitoring level ----

def test_the_monitoring_level_is_pre_filled_with_the_middle_of_the_arterial_range_and_follows_it(session, pack):
    perform_until(session, pack, "review_noncontrast")
    assert _field(session, "monitoring_slice", "slice_mm").value == 120          # middle of -80 to 320 mm
    assert _set(session, "plan_ranges", "arterial.end_mm", 280).ok
    do(session, "plan_ranges")
    level = _field(session, "monitoring_slice", "slice_mm")
    assert level.value == 100 and level.default == 100 and level.source == "assumption"


def test_a_chosen_monitoring_level_is_where_the_slice_is_taken(session, pack):
    perform_until(session, pack, "review_noncontrast")
    assert _field(session, "monitoring_slice", "slice_mm").editable
    assert _set(session, "monitoring_slice", "slice_mm", 60).ok
    do(session, "monitoring_slice")
    snap = session.snapshot()
    assert snap.console.tracking.slice_mm == 60 and snap.table.position_mm == pytest.approx(60, abs=0.5)
    assert "60 mm" in steps(snap)["monitoring_slice"].results[0].value
    assert _set(session, "plan_ranges", "arterial.end_mm", 280).ok               # the chosen level stays put
    assert _field(session, "monitoring_slice", "slice_mm").value == 60


def test_a_monitoring_level_outside_the_anatomy_data_is_refused_with_the_limits(session, pack):
    perform_until(session, pack, "review_noncontrast")
    result = _set(session, "monitoring_slice", "slice_mm", 900)
    assert not result.ok and "outside the patient's CT data" in result.error and "from the landmark" in result.error
    assert _field(session, "monitoring_slice", "slice_mm").value == 120          # unchanged


def test_the_monitoring_level_cannot_be_changed_once_the_injection_has_started(session, pack):
    perform_until(session, pack, "inject_and_arterial")
    result = _set(session, "monitoring_slice", "slice_mm", 60)
    assert not result.ok and "injection has started" in result.error
    assert not _field(session, "monitoring_slice", "slice_mm").editable


# ---- a stopped injection ----

def _aorta_at(session, seconds_after_start):
    return session.ctx.contrast.enhancement("aorta", session.ctx.injector.started_at_s + seconds_after_start)


def _stopped_injection(DATA, pack, after_s):
    from scansim.session import open_session
    session = open_session(DATA, "ohsu.ct.multiphase_liver", "sub-000", seed=1)
    perform_until(session, pack, "arm_injector")
    assert session.dispatch({"type": "perform", "step_id": "inject_and_arterial"}).ok
    session.advance(after_s)
    assert session.dispatch({"type": "abort"}).ok
    return session


def test_a_stopped_injection_gives_the_body_only_what_was_delivered(DATA, pack, session):
    perform_until(session, pack, "inject_and_arterial")                       # the whole 125 mL
    full = _aorta_at(session, 35)
    early, later = _stopped_injection(DATA, pack, 5.0), _stopped_injection(DATA, pack, 12.0)
    assert early.snapshot().injector.injected_contrast_ml == pytest.approx(20, abs=1.1)
    assert later.snapshot().injector.injected_contrast_ml == pytest.approx(48, abs=1.1)
    assert 0 < _aorta_at(early, 35) < _aorta_at(later, 35) < 0.6 * full
    # The body got what the injector says it gave: the enhancement scales with the volume delivered.
    ratio = _aorta_at(early, 200) / _aorta_at(later, 200)
    assert ratio == pytest.approx(20 / 48, rel=0.1)


def test_the_review_states_the_enhancement_of_the_contrast_actually_given(DATA, pack):
    session = _stopped_injection(DATA, pack, 8.0)
    do(session, "scan_venous")                                                # by hand; it chains the delayed scan
    do(session, "review_phases")
    venous = {r.label: r for r in steps(session.snapshot())["review_phases"].results}["Venous"].value
    liver = float(venous.split("liver +")[1].split(" HU")[0])
    assert liver < 25                         # a full injection reads about +60 HU in the liver at this time


# ---- stop while the images are being rebuilt ----

def test_stop_during_reconstruction_keeps_the_scan_its_images_and_its_dose(session, pack):
    perform_until(session, pack, "confirm_settings")
    assert session.dispatch({"type": "perform", "step_id": "scan_noncontrast"}).ok
    assert _run_until(session, _reconstructing("noncontrast"))
    assert not _series(session)["noncontrast"].recons[0].ready
    assert session.dispatch({"type": "abort"}).ok
    snap = session.snapshot(); nc = _series(session)["noncontrast"]
    assert nc.status == "done" and all(r.ready for r in nc.recons)
    assert len(session.series_png("noncontrast", "axial", 40)) > 1000
    assert steps(snap)["scan_noncontrast"].status == "done"          # the exposure cannot be undone: no second scan
    assert snap.console.dose.total_dlp_mgycm == pytest.approx(nc.plan.dlp_mgycm)
    perform_until(session, pack, ORDER[-1])
    assert steps(session.snapshot())["close_exam"].status == "done"
    assert session.snapshot().console.dose.total_dlp_mgycm == pytest.approx(4 * nc.plan.dlp_mgycm, rel=0.01)


def test_stop_during_the_arterial_reconstruction_keeps_the_only_arterial_images(on_aorta, pack):
    s = on_aorta
    assert s.dispatch({"type": "perform", "step_id": "inject_and_arterial"}).ok
    assert _run_until(s, _reconstructing("arterial"))
    assert s.dispatch({"type": "abort"}).ok
    arterial = _series(s)["arterial"]
    assert arterial.status == "done" and [r.ready for r in arterial.recons] == [True, True, True]
    for plane in ("axial", "coronal", "sagittal"):
        assert len(s.series_png("arterial", plane, 5)) > 1000
    snap = s.snapshot(); st = steps(snap)
    assert st["inject_and_arterial"].status == "done" and snap.console.tracking.state == "triggered"
    assert st["scan_venous"].status == "ready" and snap.active_step_id is None      # Stop ends the automatic chain
    do(s, "scan_venous")
    perform_until(s, pack, ORDER[-1])
    assert [x.status for x in s.snapshot().console.series] == ["done"] * 4


def test_stop_before_the_sweep_ends_still_returns_the_step_to_ready(session, pack):
    perform_until(session, pack, "confirm_settings")
    assert session.dispatch({"type": "perform", "step_id": "scan_noncontrast"}).ok
    assert _run_until(session, lambda snap: snap.console.series[0].status == "scanning")
    assert session.dispatch({"type": "abort"}).ok
    assert steps(session.snapshot())["scan_noncontrast"].status == "ready"
    assert _series(session)["noncontrast"].status == "planned"


# ---- what a Stop adds to the dose ----

def test_an_arterial_sweep_stopped_part_way_counts_the_part_delivered(on_aorta):
    s = on_aorta
    before = s.snapshot().console.dose.total_dlp_mgycm
    assert s.dispatch({"type": "perform", "step_id": "inject_and_arterial"}).ok
    assert _run_until(s, lambda snap: 0.3 < {x.id: x for x in snap.console.series}["arterial"].scanned_fraction < 1)
    fraction = _series(s)["arterial"].scanned_fraction
    planned = _series(s)["arterial"].plan.dlp_mgycm
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot()
    assert snap.console.dose.total_dlp_mgycm - before == pytest.approx(planned * fraction, rel=0.02)
    assert any("Arterial: the scan was stopped after" in e.text and "added to the dose total" in e.text
               for e in snap.log if e.kind == "alert")
    assert _series(s)["arterial"].status == "missed" and snap.console.tracking.state == "missed"
    listed = snap.console.dose.extra_exposures                 # and it stays on the Dose tab, not only in the log
    assert [(e.label, e.what.split(" after")[0]) for e in listed] == [("Arterial", "stopped")]
    assert listed[0].dlp_mgycm == pytest.approx(planned * fraction, rel=0.02)


# ---- the Dose table adds up: every exposure in the total is a row or a listed exposure ----

def _dose(session):
    """(sum of the rows of scanned series, the listed exposures, the total)."""
    snap = session.snapshot()
    rows = sum(x.plan.dlp_mgycm for x in snap.console.series if x.status == "done")
    return rows, snap.console.dose.extra_exposures, snap.console.dose.total_dlp_mgycm


def _stop_the_noncontrast_sweep_part_way(session):
    assert session.dispatch({"type": "perform", "step_id": "scan_noncontrast"}).ok
    assert _run_until(session, lambda snap: 0.2 < snap.console.series[0].scanned_fraction < 1)
    delivered = _series(session)["noncontrast"].plan.dlp_mgycm * _series(session)["noncontrast"].scanned_fraction
    assert session.dispatch({"type": "abort"}).ok
    return delivered


def test_a_stopped_sweep_is_listed_as_an_exposure_of_its_own(session, pack):
    perform_until(session, pack, "confirm_settings")
    delivered = _stop_the_noncontrast_sweep_part_way(session)
    rows, listed, total = _dose(session)
    assert rows == 0 and len(listed) == 1
    assert listed[0].label == "Non-contrast" and listed[0].what.startswith("stopped after ")
    assert listed[0].dlp_mgycm == pytest.approx(delivered, rel=0.02) and total == pytest.approx(listed[0].dlp_mgycm)


def test_the_rows_and_the_listed_exposures_add_up_to_the_total_after_a_stop_and_a_repeat(session, pack):
    """A sweep stopped part-way, then the scan; planned again and scanned again: three exposures, one row."""
    perform_until(session, pack, "confirm_settings")
    _stop_the_noncontrast_sweep_part_way(session)
    do(session, "scan_noncontrast")
    first = _series(session)["noncontrast"].plan.dlp_mgycm
    assert _set(session, "plan_ranges", "noncontrast.end_mm", 250).ok
    for step_id in ("plan_ranges", "confirm_settings", "scan_noncontrast"):
        do(session, step_id)
    rows, listed, total = _dose(session)
    assert [e.label for e in listed] == ["Non-contrast", "Non-contrast"]
    assert listed[0].what.startswith("stopped after ") and listed[1].what == "earlier scan, scanned again"
    assert listed[1].dlp_mgycm == pytest.approx(first) and rows < first
    assert rows + sum(e.dlp_mgycm for e in listed) == pytest.approx(total)
    assert any("scanned again" in e.text and "stays in the dose total" in e.text for e in session.ctx.log.tail(2000))
    perform_until(session, pack, "send_images")
    rows, listed, total = _dose(session)
    assert len(listed) == 2 and rows + sum(e.dlp_mgycm for e in listed) == pytest.approx(total)
    sent = {r.label: r.value for r in steps(session.snapshot())["send_images"].results}
    assert "stopped after" in sent["Also in the total"] and "earlier scan, scanned again" in sent["Also in the total"]


def test_a_repeat_stopped_while_its_images_are_rebuilt_still_lists_the_scan_it_replaced(session, pack):
    perform_until(session, pack, "review_noncontrast")
    first = _series(session)["noncontrast"].plan.dlp_mgycm
    do(session, "plan_ranges"); do(session, "confirm_settings")
    assert session.dispatch({"type": "perform", "step_id": "scan_noncontrast"}).ok
    assert _run_until(session, _reconstructing("noncontrast"))
    assert session.dispatch({"type": "abort"}).ok
    rows, listed, total = _dose(session)
    assert [(e.label, e.what) for e in listed] == [("Non-contrast", "earlier scan, scanned again")]
    assert listed[0].dlp_mgycm == pytest.approx(first) and rows + first == pytest.approx(total)


def test_an_exam_without_stops_or_repeats_lists_no_extra_exposure(session, pack):
    perform_until(session, pack, "send_images")
    rows, listed, total = _dose(session)
    assert listed == [] and rows == pytest.approx(total)
    assert "Also in the total" not in {r.label for r in steps(session.snapshot())["send_images"].results}
