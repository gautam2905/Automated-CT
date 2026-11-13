"""Doing a step again: every repeat must leave an exam that can be finished, or be refused with the reason."""
import hashlib

import pytest
from helpers import ORDER, PRESCAN, do, perform_all, perform_until, steps

from scansim.session import open_session

PROTOCOL = "ohsu.ct.multiphase_liver"
REPEATABLE = ["table_height", "set_landmark", "topogram_ap", "topogram_lat", "check_centring", "plan_ranges",
              "confirm_settings", "review_noncontrast", "monitoring_slice", "place_roi"]
LAST_BEFORE_INJECTION = "arm_injector"
# A different value for the repeat, so that it is a real change and not a no-op: (field, value).
CHANGES = {
    "table_height": ("height_mm", 830), "set_landmark": ("distance_from_head_mm", 500),
    "topogram_ap": ("ma", 30), "topogram_lat": ("ma", 35), "check_centring": ("new_height_mm", 860),
    "plan_ranges": ("noncontrast.end_mm", 300), "confirm_settings": ("quality_ref_mas", 160),
    "monitoring_slice": ("slice_mm", 100), "place_roi": ("roi_r_mm", 6),
}
POINTS = [(step, point) for step in REPEATABLE
          for point in ORDER[ORDER.index(step): ORDER.index(LAST_BEFORE_INJECTION) + 1]]


def _set(session, step_id, key, value):
    return session.dispatch({"type": "set_field", "step_id": step_id, "key": key, "value": value})


def _perform(session, step_id):
    return session.dispatch({"type": "perform", "step_id": step_id})


def _series(session):
    return {s.id: s for s in session.snapshot().console.series}


def _repeat(session, step_id):
    if step_id in CHANGES:
        key, value = CHANGES[step_id]
        assert _set(session, step_id, key, value).ok
    result = _perform(session, step_id)
    session.run_until_idle()
    return result


def _assert_finished(session):
    snap = session.snapshot(); st = steps(snap)
    assert [s for s in ORDER if st[s].status != "done"] == []
    assert [s.status for s in snap.console.series] == ["done"] * 4
    assert snap.pose.stage == "away" and snap.injector.state == "done"
    assert len(session.series_png("noncontrast", "axial", 10)) > 1000


def test_the_list_of_repeatable_steps_is_the_engines(session):
    live = [s.id for stage in session.snapshot().stages for s in stage.steps if s.repeatable]
    assert live == REPEATABLE


@pytest.mark.parametrize("step_id,point", POINTS, ids=[f"{s}@{p}" for s, p in POINTS])
def test_repeating_a_step_at_any_later_point_before_the_injection_leaves_an_exam_that_finishes(
        DATA, pack, step_id, point):
    session = open_session(DATA, PROTOCOL, "sub-000", seed=1)
    perform_until(session, pack, point)
    result = _repeat(session, step_id)
    assert result.ok, f"{step_id} after {point}: {result.error}"
    assert steps(session.snapshot())[step_id].status == "done"
    perform_all(session, pack)
    _assert_finished(session)


def test_after_the_injection_every_earlier_repeat_is_refused_with_the_reason_and_the_exam_finishes(session, pack):
    perform_until(session, pack, "inject_and_arterial")            # the chain runs on to the delayed scan
    for point in ORDER[ORDER.index("scan_delayed"):]:
        perform_until(session, pack, point)
        before = session.snapshot().model_dump_json()
        for step_id in REPEATABLE:
            result = _perform(session, step_id)
            assert not result.ok and "injection has started" in result.error, (step_id, point, result.error)
            field = steps(session.snapshot())[step_id].fields[-1]
            edit = _set(session, step_id, field.key, field.value)
            assert not edit.ok and "injection has started" in edit.error
        assert session.snapshot().model_dump_json() == before          # a refusal changes nothing
    _assert_finished(session)


def test_after_the_injection_done_steps_are_shown_as_not_repeatable_and_their_fields_are_locked(session, pack):
    perform_until(session, pack, "arm_injector")
    st = steps(session.snapshot())
    assert all(st[s].repeatable and st[s].fields[-1].editable for s in REPEATABLE)
    assert all(st[s].blocked_by == [] for s in REPEATABLE)
    perform_until(session, pack, "scan_delayed")
    st = steps(session.snapshot())
    assert not any(st[s].repeatable for s in REPEATABLE)
    assert not any(f.editable for s in REPEATABLE for f in st[s].fields)
    # The card itself says why "Do again" is gone: its button is disabled, so no refusal would ever be seen.
    for s in REPEATABLE:
        assert st[s].status == "done" and len(st[s].blocked_by) == 1, s
        assert "injection has started" in st[s].blocked_by[0], s
    assert st["load_injector"].blocked_by == []                      # a step that never could be repeated says nothing


def test_a_done_step_gives_no_reason_while_an_earlier_step_is_being_done_again(session, pack):
    perform_until(session, pack, "set_landmark")
    assert _set(session, "table_height", "height_mm", 860).ok
    assert _perform(session, "table_height").ok
    session.advance(0.1)
    st = steps(session.snapshot())
    assert st["table_height"].status == "running" and st["set_landmark"].status == "done"
    assert st["set_landmark"].blocked_by == []            # it is not refused, only waiting its turn
    session.run_until_idle()
    st = steps(session.snapshot())
    assert st["set_landmark"].status == "redo" and st["leave_room"].blocked_by == ['Do "Set landmark" first']


def test_a_stopped_injection_refuses_earlier_repeats_and_the_exam_still_finishes(session, pack):
    perform_until(session, pack, "arm_injector")
    assert _perform(session, "inject_and_arterial").ok
    session.advance(8.0)
    assert session.dispatch({"type": "abort"}).ok
    for step_id in ("plan_ranges", "topogram_ap", "set_landmark", "table_height"):
        result = _perform(session, step_id)
        assert not result.ok and "injection has started" in result.error
    st = steps(session.snapshot())
    assert st["arm_injector"].status == "done" and st["scan_venous"].status == "ready"
    do(session, "scan_venous")                                        # by hand; it chains the delayed scan
    for step_id in ORDER[ORDER.index("review_phases"):]:
        do(session, step_id)
    snap = session.snapshot(); st = steps(snap)
    assert [s for s in ORDER if st[s].status != "done"] == ["inject_and_arterial"]
    assert snap.pose.stage == "away" and _series(session)["arterial"].status == "missed"


def test_a_repeat_before_the_injection_never_sends_the_armed_injector_to_redo(session, pack):
    perform_until(session, pack, "arm_injector")
    assert _repeat(session, "plan_ranges").ok
    st = steps(session.snapshot())
    assert st["arm_injector"].status == "done" and session.snapshot().injector.state == "armed"
    assert st["place_roi"].status == "redo" and st["confirm_settings"].status == "redo"
    # The injection waits for everything before the armed injector to be done again.
    inject = st["inject_and_arterial"]
    assert inject.status == "locked" and inject.blocked_by == ['Do "Place ROI" first']
    assert not _perform(session, "inject_and_arterial").ok
    perform_all(session, pack)
    _assert_finished(session)


def test_replanning_after_the_scan_keeps_the_scanned_series_until_it_is_scanned_again(session, pack):
    perform_until(session, pack, "review_noncontrast")
    before = _series(session)["noncontrast"]
    image = session.series_png("noncontrast", "axial", 40)
    assert _set(session, "plan_ranges", "noncontrast.end_mm", 250).ok
    do(session, "plan_ranges")
    ser = _series(session)
    assert ser["noncontrast"] == before and session.series_png("noncontrast", "axial", 40) == image
    assert ser["arterial"].plan.end_mm == 250 and ser["arterial"].status == "planned"
    assert steps(session.snapshot())["scan_noncontrast"].status == "redo"
    do(session, "confirm_settings"); do(session, "scan_noncontrast")
    again = _series(session)["noncontrast"]
    assert again.status == "done" and again.plan.end_mm == 250 and again.recons[0].ready
    assert again.plan.dlp_mgycm < before.plan.dlp_mgycm
    assert session.snapshot().console.dose.total_dlp_mgycm == pytest.approx(
        before.plan.dlp_mgycm + again.plan.dlp_mgycm)                 # both scans exposed the patient


def test_a_repeat_scan_that_is_stopped_early_leaves_the_earlier_images_in_place(session, pack):
    perform_until(session, pack, "review_noncontrast")
    before = _series(session)["noncontrast"]
    do(session, "plan_ranges"); do(session, "confirm_settings")
    assert _perform(session, "scan_noncontrast").ok
    session.advance(2.0)                                              # still preparing: nothing exposed yet
    assert session.dispatch({"type": "abort"}).ok
    assert _series(session)["noncontrast"] == before
    assert steps(session.snapshot())["scan_noncontrast"].status == "redo"
    assert len(session.series_png("noncontrast", "axial", 40)) > 1000


def test_a_new_landmark_keeps_scanned_images_in_place_and_drops_what_was_made_from_the_old_one(session, pack):
    perform_until(session, pack, "monitoring_slice")
    session.dispatch({"type": "set_reference", "on": True})
    digest = hashlib.sha256(session.series_png("noncontrast", "axial", 40)).hexdigest()
    old = _series(session)["noncontrast"].plan
    assert _set(session, "set_landmark", "distance_from_head_mm", 700).ok       # 224 mm further down
    do(session, "set_landmark")
    snap = session.snapshot()                                         # the reference is on: this must not raise
    assert snap.console.topograms == [] and snap.console.tracking is None and snap.console.reference_points == []
    assert [s.id for s in snap.console.series] == ["noncontrast"]
    moved = snap.console.series[0].plan
    assert (moved.start_mm, moved.end_mm) == pytest.approx((old.start_mm - 224, old.end_mm - 224))
    assert hashlib.sha256(session.series_png("noncontrast", "axial", 40)).hexdigest() == digest
    st = steps(snap)
    assert st["leave_room"].status == "redo" and st["topogram_ap"].status == "redo"
    assert st["scan_noncontrast"].status == "redo"


def test_a_landmark_far_from_the_liver_can_be_corrected_and_the_exam_finished(session, pack):
    perform_until(session, pack, "monitoring_slice")
    assert _set(session, "set_landmark", "distance_from_head_mm", 700).ok
    do(session, "set_landmark")
    assert _set(session, "set_landmark", "distance_from_head_mm", 476).ok
    do(session, "set_landmark")
    perform_all(session, pack)
    _assert_finished(session)


def test_a_repeat_that_is_refused_or_stopped_leaves_the_door_closed(session, pack):
    perform_until(session, pack, "check_centring")                    # the table is in the bore, the door closed
    assert _set(session, "table_height", "height_mm", 600).ok
    result = _perform(session, "table_height")                        # refused: too low while inside the bore
    assert not result.ok and "bore" in result.error
    room = session.snapshot().room
    assert not room.door_open and room.technologist_at == "console"
    assert _set(session, "table_height", "height_mm", 840).ok
    assert _perform(session, "table_height").ok
    session.advance(0.1)
    assert session.snapshot().room.door_open
    assert session.dispatch({"type": "abort"}).ok                     # stopped half way
    room = session.snapshot().room
    assert not room.door_open and room.technologist_at == "console"
    assert steps(session.snapshot())["table_height"].status == "done"
    do(session, "plan_ranges")                                        # the exam goes on


def test_a_table_too_low_for_the_bore_is_flagged_and_corrected_by_doing_the_step_again(session, pack):
    for step_id in PRESCAN[:15]:
        do(session, step_id)
    assert _set(session, "table_height", "height_mm", 600).ok          # inside the field's limits
    do(session, "table_height")
    check = [r for r in steps(session.snapshot())["table_height"].results if r.alert]
    assert check and "do this step again" in check[0].value
    assert not _perform(session, "set_landmark").ok                    # the table cannot enter the bore
    card = steps(session.snapshot())["table_height"]
    assert card.status == "done" and card.repeatable and card.fields[0].editable
    assert _set(session, "table_height", "height_mm", 850).ok
    do(session, "table_height")
    perform_all(session, pack)
    _assert_finished(session)


def test_positioning_steps_are_refused_once_the_patient_has_left(session, pack):
    perform_all(session, pack)
    for step_id in ("set_landmark", "table_height"):
        result = _perform(session, step_id)                           # refused, not an AttributeError
        assert not result.ok and result.error
    session.ctx.injector.started_at_s = None                          # white box: reach the routines' own guard
    for step_id in ("set_landmark", "table_height"):
        result = _perform(session, step_id)
        assert not result.ok and "not on the table" in result.error
    assert session.snapshot().pose.stage == "away"


def test_a_new_monitoring_slice_sends_the_region_back_to_redo(session, pack):
    perform_until(session, pack, "place_roi")
    do(session, "monitoring_slice")
    st = steps(session.snapshot())
    assert st["place_roi"].status == "redo" and session.snapshot().console.tracking.baseline_hu is None
