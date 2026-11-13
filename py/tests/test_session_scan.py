import pytest
from helpers import do, png_array, steps, truth_covered


def _fields(session, step_id):
    return {x.key: x.value for x in steps(session.snapshot())[step_id].fields}


def _alerts(session):
    return [e.text for e in session.snapshot().log if e.kind == "alert"]


def test_topogram_reveals_rows_in_step_with_the_table(positioned):
    s = positioned; assert s.dispatch({"type": "perform", "step_id": "topogram_ap"}).ok
    seen = []
    for _ in range(400):
        s.advance(0.1); t = s.snapshot().console.topograms
        if t and t[0].revealed_to_row > t[0].revealed_from_row: seen.append((t[0].revealed_to_row, s.snapshot().scanner.beam_on))
    final = s.snapshot().console.topograms[0]
    assert final.complete and not s.snapshot().scanner.beam_on
    assert [r for r, _ in seen] == sorted(r for r, _ in seen) and any(b for _, b in seen)
    f = {x.key: x.value for x in steps(s.snapshot())["topogram_ap"].fields}
    assert (final.revealed_to_row - final.revealed_from_row) * final.row_mm == pytest.approx(f["length_mm"], abs=final.row_mm)
    assert any(e.kind == "voice" and "hold" in e.text.lower() for e in s.snapshot().log)


def test_topogram_png_only_shows_acquired_rows(positioned):
    do(positioned, "topogram_ap"); t = positioned.snapshot().console.topograms[0]
    a = png_array(positioned.topogram_png("AP"))
    assert a[: t.revealed_from_row].max() == 0 and a[t.revealed_to_row:].max() == 0


def test_topogram_past_the_anatomy_data_is_refused(positioned):
    positioned.dispatch({"type": "set_field", "step_id": "topogram_ap", "key": "start_mm", "value": -900})
    positioned.dispatch({"type": "perform", "step_id": "topogram_ap"}); positioned.run_until_idle()
    snap = positioned.snapshot()
    assert steps(snap)["topogram_ap"].status == "ready" and any("anatomy data" in e.text for e in snap.log if e.kind == "alert")


def test_range_outside_the_topogram_is_refused(planned_base):
    s = planned_base
    s.dispatch({"type": "set_field", "step_id": "plan_ranges", "key": "noncontrast.end_mm", "value": 900})
    s.dispatch({"type": "perform", "step_id": "plan_ranges"}); s.run_until_idle()
    snap = s.snapshot()
    assert steps(snap)["plan_ranges"].status != "done" and any("topogram" in e.text.lower() for e in snap.log if e.kind == "alert")


def test_linked_ranges_move_together(planned_base):
    planned_base.dispatch({"type": "set_field", "step_id": "plan_ranges", "key": "arterial.start_mm", "value": -35})
    f = {x.key: x.value for x in steps(planned_base.snapshot())["plan_ranges"].fields}
    assert f["noncontrast.start_mm"] == f["venous.start_mm"] == f["delayed.start_mm"] == -35


def test_settings_give_feed_time_and_dose(planned_base):
    do(planned_base, "plan_ranges"); do(planned_base, "confirm_settings")
    p = planned_base.snapshot().console.series[0].plan
    assert p.feed_mm_s == pytest.approx(p.pitch * p.collimation_mm / p.rotation_s)
    assert p.scan_time_s == pytest.approx((p.end_mm - p.start_mm) / p.feed_mm_s)
    assert 2 < p.ctdi_vol_mgy < 40 and p.dlp_mgycm == pytest.approx(p.ctdi_vol_mgy * (p.end_mm - p.start_mm) / 10)


def test_noncontrast_scan_and_truthful_review(planned_base, pack):
    s = planned_base; do(s, "plan_ranges"); do(s, "confirm_settings"); do(s, "scan_noncontrast")
    snap = s.snapshot(); nc = snap.console.series[0]
    assert nc.status == "done" and nc.scanned_fraction == 1.0 and nc.recons[0].ready and not nc.motion
    assert snap.console.dose.total_dlp_mgycm > 0 and png_array(s.series_png("noncontrast", "axial", 0)).shape[0] == 512
    assert not s.dispatch({"type": "perform", "step_id": "review_noncontrast"}).ok        # not answered yet
    covered = truth_covered(s, pack)                                 # liver_top and liver_bottom inside [start, end]
    s.dispatch({"type": "set_field", "step_id": "review_noncontrast", "key": "liver_included", "value": "yes"})
    do(s, "review_noncontrast")
    res = steps(s.snapshot())["review_noncontrast"].results
    assert any("mm" in r.value for r in res) and any(r.alert for r in res) == (not covered)


def test_changing_table_height_keeps_a_dual_topogram(planned_base):
    s = planned_base; h = s.snapshot().table.height_mm
    s.dispatch({"type": "set_field", "step_id": "check_centring", "key": "new_height_mm", "value": h + 20})
    do(s, "check_centring"); snap = s.snapshot(); st = steps(snap)
    assert snap.table.height_mm == pytest.approx(h + 20)
    assert st["topogram_ap"].status == "done" and st["topogram_lat"].status == "done" and st["plan_ranges"].status == "ready"


# ---- further behaviour ----

def test_lateral_topogram_defaults_follow_the_ap_values(positioned):
    positioned.dispatch({"type": "set_field", "step_id": "topogram_ap", "key": "ma", "value": 30})
    do(positioned, "topogram_ap")
    assert _fields(positioned, "topogram_lat")["ma"] == 30


def test_tube_is_above_for_ap_and_on_the_patients_left_for_lateral(positioned):
    s = positioned
    do(s, "topogram_ap")
    assert s.dispatch({"type": "perform", "step_id": "topogram_lat"}).ok
    angles = set()
    for _ in range(300):
        s.advance(0.1)
        if s.snapshot().scanner.beam_on:
            angles.add(s.snapshot().scanner.tube_angle_deg)
    assert angles == {270.0}                       # supine, feet first: the patient's left is at -x
    assert s.snapshot().scanner.tube_angle_deg == 0 and not s.snapshot().room.warning_light_on


def test_topogram_image_url_changes_as_rows_appear(positioned):
    s = positioned; s.dispatch({"type": "perform", "step_id": "topogram_ap"})
    urls = set()
    for _ in range(100):
        s.advance(0.1); t = s.snapshot().console.topograms
        if t:
            assert t[0].image_url.endswith(f".png?r={t[0].revealed_to_row}")
            urls.add(t[0].image_url)
    assert len(urls) > 5


def test_topogram_beyond_table_travel_is_refused_before_moving(positioned):
    s = positioned; before = s.snapshot().table.long_mm
    s.dispatch({"type": "set_field", "step_id": "topogram_ap", "key": "start_mm", "value": 1400})
    r = s.dispatch({"type": "perform", "step_id": "topogram_ap"})
    assert not r.ok and s.snapshot().table.long_mm == before and not s.snapshot().scanner.beam_on


def test_centring_result_gives_offset_and_direction_only(planned_base):
    res = steps(planned_base.snapshot())["check_centring"].results
    assert any("isocentre" in r.value and "mm" in r.value for r in res)
    assert all("mm below" in r.value or "mm above" in r.value or "isocentre" in r.value for r in res[:1])


def test_pitch_above_the_scanner_maximum_is_refused(planned_base):
    s = planned_base; do(s, "plan_ranges")
    s.dispatch({"type": "set_field", "step_id": "confirm_settings", "key": "pitch", "value": 4})
    r = s.dispatch({"type": "perform", "step_id": "confirm_settings"})
    assert not r.ok and "3.2" in r.error


def test_reversed_range_is_refused(planned_base):
    s = planned_base
    s.dispatch({"type": "set_field", "step_id": "plan_ranges", "key": "noncontrast.end_mm", "value": -200})
    r = s.dispatch({"type": "perform", "step_id": "plan_ranges"})
    assert not r.ok and "end" in r.error.lower()


def test_series_images_refuse_what_does_not_exist(planned_base):
    s = planned_base; do(s, "plan_ranges"); do(s, "confirm_settings")
    with pytest.raises(Exception, match="not done|not scanned"):
        s.series_png("noncontrast", "axial", 0)
    do(s, "scan_noncontrast")
    count = s.snapshot().console.series[0].recons[0].image_count
    with pytest.raises(Exception, match="out of range|between"):
        s.series_png("noncontrast", "axial", count)
    assert png_array(s.series_png("noncontrast", "axial", count - 1)).shape == (512, 512)


def test_scan_leaves_the_room_safe_when_aborted(planned_base):
    s = planned_base; do(s, "plan_ranges"); do(s, "confirm_settings")
    assert s.dispatch({"type": "perform", "step_id": "scan_noncontrast"}).ok
    for _ in range(140):
        s.advance(0.1)
    mid = s.snapshot()
    assert mid.scanner.beam_on and mid.room.warning_light_on and mid.scanner.rotor_rps == pytest.approx(2.0)
    assert 0 < mid.console.series[0].scanned_fraction < 1
    s.dispatch({"type": "abort"}); snap = s.snapshot()
    assert not snap.scanner.beam_on and not snap.room.warning_light_on and snap.scanner.rotor_rps == 0
    assert not snap.pose.holding and snap.console.series[0].status == "planned"
    # The part of the range already exposed counts toward the dose total, and the log says so.
    delivered = mid.console.series[0].plan.dlp_mgycm * mid.console.series[0].scanned_fraction
    assert snap.console.dose.total_dlp_mgycm == pytest.approx(delivered, rel=0.05) and delivered > 0
    assert any(e.kind == "alert" and "stopped after" in e.text and "added to the dose total" in e.text
               for e in snap.log)


def test_replanning_after_the_scan_makes_the_scan_redo(planned_base):
    s = planned_base
    for step_id in ("plan_ranges", "confirm_settings", "scan_noncontrast"):
        do(s, step_id)
    do(s, "plan_ranges")
    st = steps(s.snapshot())
    assert st["scan_noncontrast"].status == "redo" and st["confirm_settings"].status == "redo"


def test_single_ap_topogram_is_repeated_after_a_height_change(positioned):
    s = positioned
    do(s, "topogram_ap")
    s.workflow.step("check_centring").requires = ("topogram_ap",)   # a protocol with no lateral view
    h = s.snapshot().table.height_mm
    s.dispatch({"type": "set_field", "step_id": "check_centring", "key": "new_height_mm", "value": h + 20})
    s.ctx.protocol.topogram.views = ["AP"]
    do(s, "check_centring")
    assert steps(s.snapshot())["topogram_ap"].status == "redo"


def test_review_says_yes_to_a_cut_off_liver_is_an_alert(planned_base):
    s = planned_base
    s.dispatch({"type": "set_field", "step_id": "plan_ranges", "key": "noncontrast.start_mm", "value": 0})
    for step_id in ("plan_ranges", "confirm_settings", "scan_noncontrast"):
        do(s, step_id)
    s.dispatch({"type": "set_field", "step_id": "review_noncontrast", "key": "liver_included", "value": "yes"})
    do(s, "review_noncontrast")
    res = steps(s.snapshot())["review_noncontrast"].results
    assert any(r.alert for r in res) and any("above the start" in r.value for r in res)


def test_a_series_can_be_given_an_enhancement_function(planned_base):
    s = planned_base; do(s, "plan_ranges"); do(s, "confirm_settings")
    times = []
    from scansim.ct.acquisition import acquire_series

    def liver_enhancement(t_s):
        times.append(t_s)
        return {"liver": 100.0}

    s.ctx.console.enhancement_at["noncontrast"] = liver_enhancement
    do(s, "scan_noncontrast")
    plain = png_array(s.series_png("noncontrast", "axial", 133))
    assert times and times[0] >= s.snapshot().console.series[0].started_at_s
    s.ctx.console.enhancement_at.clear()
    assert (png_array(s.series_png("noncontrast", "axial", 133)) != plain).any()
    assert callable(acquire_series)


def _views(session, view="AP"):
    return [t for t in session.snapshot().console.topograms if t.view == view]


def test_abort_during_a_first_topogram_leaves_no_view(positioned):
    s = positioned
    assert s.dispatch({"type": "perform", "step_id": "topogram_ap"}).ok
    for _ in range(60):
        s.advance(0.1)
    assert s.snapshot().scanner.beam_on and _views(s)
    s.dispatch({"type": "abort"}); snap = s.snapshot()
    assert not _views(s) and steps(snap)["topogram_ap"].status == "ready"
    assert not snap.scanner.beam_on and not snap.room.warning_light_on


def test_abort_during_a_repeated_topogram_restores_the_earlier_view(planned_base):
    s = planned_base; do(s, "plan_ranges")
    before = _views(s)[0]
    assert s.dispatch({"type": "perform", "step_id": "topogram_ap"}).ok
    for _ in range(60):
        s.advance(0.1)
    assert s.snapshot().scanner.beam_on and _views(s)[0] != before
    s.dispatch({"type": "abort"}); snap = s.snapshot()
    assert _views(s) == [before] and before.complete
    # core's abort returns any step to idle, so the repeated step reads "ready" again; the view is the earlier one
    assert steps(snap)["topogram_ap"].status == "done" and steps(snap)["plan_ranges"].status == "done"
    assert not snap.scanner.beam_on and not snap.room.warning_light_on
    do(s, "plan_ranges")


def test_abort_while_the_table_positions_for_a_topogram(positioned):
    s = positioned
    assert s.dispatch({"type": "perform", "step_id": "topogram_ap"}).ok
    s.advance(0.5)
    assert not s.snapshot().scanner.beam_on
    s.dispatch({"type": "abort"}); snap = s.snapshot()
    assert not _views(s) and steps(snap)["topogram_ap"].status == "ready" and not snap.room.warning_light_on


def test_table_travel_refusal_names_the_limit(positioned):
    s = positioned
    before = s.snapshot().table.long_mm
    s.ctx.spec.table.long_max_mm = 600.0      # a shorter table: the data allow this run, the table does not
    r = s.dispatch({"type": "perform", "step_id": "topogram_ap"})
    assert not r.ok and "between 0 and 600 mm" in r.error and s.snapshot().table.long_mm == before
