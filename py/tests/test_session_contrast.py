import pytest
from helpers import do, perform_until, steps


def test_manual_start_rescues_the_arterial_phase(tracking_ready):      # session up to arm_injector, region off the aorta
    s = tracking_ready
    s.ctx.protocol.contrast.timing.max_monitoring_s = 20      # monitoring ends early enough to leave a manual window
    assert s.dispatch({"type": "perform", "step_id": "inject_and_arterial"}).ok
    for _ in range(4000):
        s.advance(0.05)
        if s.snapshot().console.tracking.state == "manual": break
    assert s.dispatch({"type": "manual_start"}).ok; s.run_until_idle()
    assert {x.id: x for x in s.snapshot().console.series}["arterial"].status == "done"


def test_abort_during_a_scan_turns_the_beam_off(tracking_ready):
    s = tracking_ready; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    for _ in range(4000):
        s.advance(0.05)
        if s.snapshot().scanner.beam_on: break
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot(); assert not snap.scanner.beam_on and not snap.room.warning_light_on and snap.active_step_id is None


# ---- tracking set-up ----

def _step(session, step_id):
    return steps(session.snapshot())[step_id]


def _results(session, step_id):
    return {r.label: r for r in _step(session, step_id).results}


def _run_for(session, seconds, until=None, dt=0.05):
    for _ in range(int(seconds / dt)):
        session.advance(dt)
        if until is not None and until(session.snapshot()):
            return True
    return until is None


@pytest.fixture
def on_aorta(session, pack):
    perform_until(session, pack, "arm_injector", roi_on_aorta=True)
    return session


def test_monitoring_slice_gives_an_image_without_contrast_and_a_midpoint_level(planned_base, pack):
    s = planned_base
    perform_until(s, pack, "review_noncontrast")
    assert _step(s, "monitoring_slice").status == "ready"
    plan = next(x for x in s.snapshot().console.series if x.id == "arterial").plan
    level = next(f for f in _step(s, "monitoring_slice").fields if f.key == "slice_mm")
    assert level.value == (plan.start_mm + plan.end_mm) / 2 and level.editable and level.source == "assumption"
    do(s, "monitoring_slice")
    tr = s.snapshot().console.tracking
    assert tr.state == "slice_acquired" and tr.slice_mm == level.value and tr.baseline_hu is None
    assert tr.image_url.endswith("tracking.png?n=1")
    assert len(s.tracking_png()) > 1000 and not s.snapshot().scanner.beam_on
    do(s, "monitoring_slice")                         # repeatable
    assert s.snapshot().console.tracking.image_url.endswith("?n=2")


def test_tracking_image_before_the_slice_is_not_available(session):
    with pytest.raises(LookupError):
        session.tracking_png()


def test_region_gives_a_baseline_and_a_relative_trigger_level(session, pack):
    perform_until(session, pack, "place_roi")
    tr = session.snapshot().console.tracking
    assert tr.baseline_hu == pytest.approx(float(_results(session, "place_roi")["Baseline"].value.split()[1]), abs=1)
    assert 20 < tr.baseline_hu < 120 and tr.threshold_hu == 100 and tr.samples == []
    assert f"{tr.baseline_hu + 100:.0f} HU" in _results(session, "place_roi")["Trigger"].value


def test_region_field_limits_name_the_field(session, pack):
    perform_until(session, pack, "review_noncontrast")
    r = session.dispatch({"type": "set_field", "step_id": "place_roi", "key": "roi_r_mm", "value": 0})
    assert not r.ok and "Region radius" in r.error


def test_reference_point_is_the_true_aorta_in_field_of_view_coordinates(session, pack):
    from helpers import aorta_in_plan_frame
    perform_until(session, pack, "monitoring_slice")
    session.dispatch({"type": "set_reference", "on": True})
    points = session.snapshot().console.reference_points
    ax, ay = aorta_in_plan_frame(session, pack)
    assert [p.name for p in points] == ["aorta"]
    assert (points[0].x_mm, points[0].y_mm) == pytest.approx((ax, ay))
    session.dispatch({"type": "set_reference", "on": False})
    assert session.snapshot().console.reference_points == []


def test_no_reference_point_before_the_monitoring_slice(planned_base):
    planned_base.dispatch({"type": "set_reference", "on": True})
    assert planned_base.snapshot().console.reference_points == []


def test_arming_needs_a_connected_injector(session, pack):
    perform_until(session, pack, "place_roi")
    session.ctx.injector.state = "purged"
    reasons = _step(session, "arm_injector").blocked_by
    assert any("connected" in r for r in reasons)
    assert not session.dispatch({"type": "perform", "step_id": "arm_injector"}).ok


def test_arming_more_than_is_loaded_is_refused_with_the_amounts(session, pack):
    perform_until(session, pack, "place_roi")
    session.dispatch({"type": "set_field", "step_id": "arm_injector", "key": "volume_ml", "value": 190})
    r = session.dispatch({"type": "perform", "step_id": "arm_injector"})
    assert not r.ok and "190" in r.error and "130" in r.error and session.snapshot().injector.state == "connected"


def test_default_chaser_is_loaded_and_programmed_in_full(session, pack):
    perform_until(session, pack, "arm_injector")
    assert session.snapshot().injector.saline_ml == 40 - 10 + 10 and "40 mL saline" in _results(session, "arm_injector")["Programmed"].value
    assert not any(r.alert for r in _step(session, "arm_injector").results)


def test_load_injector_saline_default_is_chaser_plus_test_flush_and_says_so(session):
    f = next(x for x in _step(session, "load_injector").fields if x.key == "saline_ml")
    assert f.value == 50 and f.source == "assumption" and "test flush" in f.help


def test_arming_more_saline_than_is_left_is_refused_with_the_amounts(session, pack):
    perform_until(session, pack, "place_roi")
    session.dispatch({"type": "set_field", "step_id": "arm_injector", "key": "saline_ml", "value": 45})
    r = session.dispatch({"type": "perform", "step_id": "arm_injector"})
    assert not r.ok and "45 mL saline" in r.error and "40 mL" in r.error
    assert session.snapshot().injector.state == "connected"
    session.dispatch({"type": "set_field", "step_id": "arm_injector", "key": "saline_ml", "value": 40})
    do(session, "arm_injector")


def test_injection_is_blocked_until_the_region_is_placed(session, pack):
    perform_until(session, pack, "monitoring_slice")
    assert any("region" in r.lower() for r in _step(session, "inject_and_arterial").blocked_by)


# ---- the injection and monitoring ----

def test_monitoring_scans_follow_the_protocol_timing(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    assert s.snapshot().clock.contrast_timer_s == pytest.approx(0, abs=0.1)
    beams = []
    _run_for(s, 30, until=lambda snap: beams.append((snap.clock.contrast_timer_s, snap.scanner.beam_on)) or
             snap.console.tracking.state == "triggered")
    on_times = [t for (t, b), (_, prev) in zip(beams[1:], beams) if b and not prev]
    assert on_times[0] == pytest.approx(10, abs=0.2)
    assert [round(b - a, 1) for a, b in zip(on_times, on_times[1:])][:3] == [1.2] * 3
    tr = s.snapshot().console.tracking
    assert tr.samples[0].t_s == pytest.approx(10.25, abs=0.1) and len(tr.samples) == len(on_times)


def test_light_is_on_from_the_first_monitoring_scan_until_the_arterial_scan_ends(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    assert not s.snapshot().room.warning_light_on
    _run_for(s, 15, until=lambda snap: snap.scanner.beam_on)
    lights = []
    _run_for(s, 120, until=lambda snap: lights.append(snap.room.warning_light_on) or
             {x.id: x for x in snap.console.series}["arterial"].status == "done")
    assert all(lights[:-1]) and len(lights) > 100             # on through the post-trigger wait and the sweep
    assert not lights[-1]                                      # off as soon as the arterial scan has ended


def test_tracking_image_changes_url_and_shows_contrast_after_the_injection_starts(on_aorta):
    import numpy as np
    from helpers import png_array
    s = on_aorta; before = png_array(s.tracking_png()).astype(float); url0 = s.snapshot().console.tracking.image_url
    s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 40, until=lambda snap: snap.console.tracking.state == "triggered")
    after = png_array(s.tracking_png()).astype(float)
    tr = s.snapshot().console.tracking
    assert tr.image_url != url0 and tr.image_url.endswith(f"?n={1 + len(tr.samples)}")
    assert np.abs(after - before).max() > 50                  # the aorta lights up; the rest of the slice does not


def test_trigger_is_the_first_sample_at_or_above_baseline_plus_threshold(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 40, until=lambda snap: snap.console.tracking.state == "triggered")
    tr = s.snapshot().console.tracking; level = tr.baseline_hu + tr.threshold_hu
    assert all(x.hu < level for x in tr.samples[:-1]) and tr.samples[-1].hu >= level
    assert tr.triggered_at_s == pytest.approx(s.snapshot().clock.sim_time_s, abs=0.1)


def test_arterial_beam_comes_on_post_trigger_delay_after_the_trigger(session, pack):
    perform_until(session, pack, "inject_and_arterial")
    snap = session.snapshot(); tr = snap.console.tracking
    arterial = {x.id: x for x in snap.console.series}["arterial"]
    assert arterial.started_at_s - tr.triggered_at_s == pytest.approx(15, abs=0.2)
    assert not any("after its planned time" in e.text for e in snap.log)


def test_manual_start_is_refused_when_nothing_is_monitoring(on_aorta):
    r = on_aorta.dispatch({"type": "manual_start"})
    assert not r.ok and "Nothing to start manually" in r.error


def test_manual_start_during_monitoring_starts_the_arterial_scan(tracking_ready):
    s = tracking_ready; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 20, until=lambda snap: len(snap.console.tracking.samples) >= 3)
    assert s.dispatch({"type": "manual_start"}).ok
    s.advance(0.1)
    snap = s.snapshot(); tr = snap.console.tracking
    assert tr.state == "triggered" and tr.triggered_at_s == pytest.approx(snap.clock.sim_time_s, abs=0.2)
    s.run_until_idle()
    arterial = {x.id: x for x in s.snapshot().console.series}["arterial"]
    assert arterial.status == "done" and arterial.started_at_s - tr.triggered_at_s == pytest.approx(15, abs=0.5)


def test_no_trigger_with_a_short_monitoring_time_gives_a_manual_window_then_loses_the_phase(tracking_ready):
    s = tracking_ready
    s.ctx.protocol.contrast.timing.max_monitoring_s = 20
    s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    assert _run_for(s, 100, until=lambda snap: snap.console.tracking.state == "manual")
    snap = s.snapshot()
    assert snap.clock.contrast_timer_s == pytest.approx(30, abs=0.3)          # 10 s delay + 20 s of monitoring
    assert not snap.scanner.beam_on and not snap.room.warning_light_on and snap.active_step_id == "inject_and_arterial"
    assert any(e.kind == "alert" and "trigger" in e.text.lower() and "by hand within" in e.text for e in snap.log)
    assert _run_for(s, 70, until=lambda snap: snap.console.tracking.state == "missed")
    # The window closes when the venous scan must be prepared for its 70 s start, not 60 s after it opened.
    assert 50 < s.snapshot().clock.contrast_timer_s < 60


def test_no_trigger_ends_monitoring_in_time_to_prepare_the_venous_scan(tracking_ready):
    s = tracking_ready; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    states = set()
    assert _run_for(s, 100, until=lambda snap: states.add(snap.console.tracking.state) or
                    snap.console.tracking.state == "missed")
    snap = s.snapshot()
    assert 50 < snap.clock.contrast_timer_s < 60 and "manual" not in states    # before monitoring's own limit at 70 s
    assert any(e.kind == "alert" and "No trigger after" in e.text and "venous" in e.text for e in snap.log)
    assert {x.id: x for x in snap.console.series}["arterial"].status == "missed"


def test_missed_phase_still_lets_the_chain_run_with_the_venous_scan_on_time(session, pack):
    perform_until(session, pack, "scan_delayed", roi_on_aorta=False)
    snap = session.snapshot(); ser = {x.id: x for x in snap.console.series}
    started = snap.clock.sim_time_s - snap.clock.contrast_timer_s
    assert ser["arterial"].status == "missed"
    assert ser["venous"].started_at_s - started == pytest.approx(70, abs=0.5)
    assert any("no trigger" in e.text.lower() and "injection start" in e.text for e in snap.log if e.kind == "alert")
    assert not any("after its planned time" in e.text for e in snap.log)


def test_contrast_timer_keeps_counting_after_the_injection(session, pack):
    perform_until(session, pack, "scan_delayed")
    first = session.snapshot().clock.contrast_timer_s
    do(session, "review_phases"); do(session, "send_images")
    assert session.snapshot().clock.contrast_timer_s > first


def test_monitoring_scans_are_not_added_to_the_dose(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 40, until=lambda snap: snap.console.tracking.state == "triggered")
    assert s.snapshot().console.dose.total_dlp_mgycm == pytest.approx(316, abs=1)       # the non-contrast scan only
    assert "not added" in _step(s, "inject_and_arterial").info.lower()


def test_venous_and_delayed_follow_by_themselves_and_can_be_done_by_hand_after_an_abort(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 120, until=lambda snap: snap.active_step_id == "scan_venous")
    assert s.workflow.active_step_id == "scan_venous" and s.ctx.auto_next is None   # set when the venous scan ends
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot()
    assert s.ctx.auto_next is None and not snap.scanner.beam_on and not snap.room.warning_light_on
    assert steps(snap)["scan_venous"].status == "ready"
    do(s, "scan_venous")                                  # the venous step chains the delayed one again
    assert {x.id: x for x in s.snapshot().console.series}["delayed"].status == "done"


def test_abort_stops_the_injector_and_clears_the_chain(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 15, until=lambda snap: snap.scanner.beam_on)
    assert s.snapshot().injector.state == "injecting"
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot()
    assert snap.injector.state == "done" and snap.injector.flow_ml_s == 0 and s.ctx.auto_next is None
    assert snap.console.tracking.state == "missed" and snap.scanner.rotor_rps == 0     # the contrast is given: lost
    assert {x.id: x for x in snap.console.series}["arterial"].status == "missed"
    assert any(e.kind == "alert" and "lost" in e.text and "venous" in e.text for e in snap.log)
    before = snap.injector.injected_contrast_ml
    s.advance(10)
    assert s.snapshot().injector.injected_contrast_ml == before


def test_abort_during_the_arterial_scan_releases_the_breath_hold_and_resets_the_series(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 60, until=lambda snap: {x.id: x for x in snap.console.series}["arterial"].status == "scanning")
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot()
    assert {x.id: x for x in snap.console.series}["arterial"].status == "missed"
    assert not snap.pose.holding and not snap.scanner.beam_on and snap.injector.state == "done"


def test_place_roi_is_refused_once_the_injection_has_started(session, pack):
    perform_until(session, pack, "inject_and_arterial")
    r = session.dispatch({"type": "perform", "step_id": "place_roi"})
    assert not r.ok and "injection" in r.error.lower()
    r = session.dispatch({"type": "perform", "step_id": "monitoring_slice"})
    assert not r.ok and "injection" in r.error.lower()


# ---- review, send, aftercare ----

def test_review_reports_each_series_and_the_aortic_peak_timing(session, pack):
    perform_until(session, pack, "review_phases")
    res = _results(session, "review_phases")
    assert set(res) >= {"Non-contrast", "Arterial", "Venous", "4 minute delay", "Arterial timing"}
    assert "covered" in res["Arterial"].value and "no motion" in res["Arterial"].value
    assert "aorta +3" in res["Arterial"].value                        # a late-arterial aorta reads some 300 HU above baseline
    assert "Non-contrast" in res and "aorta +0 HU" in res["Non-contrast"].value


def test_review_says_so_when_the_arterial_scan_was_late(tracking_ready):
    s = tracking_ready; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 100, until=lambda snap: snap.clock.contrast_timer_s >= 50)
    assert s.dispatch({"type": "manual_start"}).ok; s.run_until_idle()   # started by hand 50 s after the injection
    do(s, "review_phases")
    note = _results(s, "review_phases")["Arterial timing"]
    assert note.alert and "late" in note.value and "peak" in note.value


def test_review_says_so_when_the_arterial_scan_was_early(session, pack):
    perform_until(session, pack, "scan_delayed")
    start = session.ctx.injector.started_at_s
    session.ctx.console.update_series("arterial", started_at_s=start + 8)      # white box: pretend it came too soon
    do(session, "review_phases")
    note = _results(session, "review_phases")["Arterial timing"]
    assert note.alert and "early" in note.value and "peak" in note.value


def test_review_flags_a_missed_phase(session, pack):
    perform_until(session, pack, "review_phases", roi_on_aorta=False)
    arterial = _results(session, "review_phases")["Arterial"]
    assert arterial.alert and "missed" in arterial.value


def test_send_images_lists_dose_per_series_and_the_total(session, pack):
    perform_until(session, pack, "send_images")
    res = _results(session, "send_images"); snap = session.snapshot()
    assert "CTDIvol" in res["Venous"].value and "DLP" in res["Venous"].value
    assert res["Total DLP"].value == f"{snap.console.dose.total_dlp_mgycm:.0f} mGy·cm"


def test_table_out_opens_the_room_and_lowers_the_table(session, pack):
    perform_until(session, pack, "table_out")
    snap = session.snapshot()
    assert snap.table.long_mm == 0 and snap.table.height_mm == snap.table.height_min_mm
    assert snap.room.door_open and not snap.room.warning_light_on and snap.room.technologist_at == "gantry"


def test_disconnect_marks_the_line_off_and_warns_about_a_bad_site(session, pack):
    perform_until(session, pack, "table_out")
    session.dispatch({"type": "set_field", "step_id": "disconnect_injector", "key": "site_ok", "value": False})
    do(session, "disconnect_injector")
    assert not session.snapshot().pose.iv_connected
    assert any(r.alert and "swelling" in r.value for r in _step(session, "disconnect_injector").results)


def test_patient_leaves_through_the_pose_stages_in_25_seconds(session, pack):
    perform_until(session, pack, "disconnect_injector")
    t0 = session.snapshot().clock.sim_time_s; stages = []
    assert session.dispatch({"type": "perform", "step_id": "patient_off_table"}).ok
    _run_for(session, 40, until=lambda snap: stages.append(snap.pose.stage) or snap.pose.stage == "away")
    assert [k for i, k in enumerate(stages) if i == 0 or k != stages[i - 1]] == ["sitting", "standing", "leaving", "away"]
    assert session.snapshot().clock.sim_time_s - t0 == pytest.approx(25, abs=0.2)


def test_abort_while_the_patient_is_leaving_puts_them_back_on_the_table(session, pack):
    perform_until(session, pack, "disconnect_injector")
    session.dispatch({"type": "perform", "step_id": "patient_off_table"})
    session.advance(12)
    assert session.snapshot().pose.stage == "standing"
    session.dispatch({"type": "abort"})
    assert session.snapshot().pose.stage == "lying"
    do(session, "patient_off_table")
    assert session.snapshot().pose.stage == "away"


def test_short_observation_is_flagged_and_the_clock_jumps_by_the_minutes(session, pack):
    perform_until(session, pack, "patient_off_table")
    session.dispatch({"type": "set_field", "step_id": "post_contrast_care", "key": "observe_min", "value": 5})
    t0 = session.snapshot().clock.sim_time_s
    do(session, "post_contrast_care")
    assert session.snapshot().clock.sim_time_s - t0 == pytest.approx(300, abs=1)
    assert any(r.alert and "15 minutes" in r.value for r in _step(session, "post_contrast_care").results)


def test_observation_field_cites_its_source_as_an_assumption(session):
    f = next(x for x in _step(session, "post_contrast_care").fields if x.key == "observe_min")
    assert f.value == 15 and f.source == "assumption" and "note 02 section I" in f.help


def test_close_exam_reports_the_exam_time_in_minutes(session, pack):
    perform_until(session, pack, "close_exam")
    minutes = round(session.snapshot().clock.sim_time_s / 60)
    assert _results(session, "close_exam")["Exam time"].value == f"Exam time: {minutes} min"


# ---- fix round 1 ----

def test_each_slice_is_rendered_with_the_enhancement_at_its_own_scan_time(session, pack):
    from helpers import png_array
    perform_until(session, pack, "inject_and_arterial")
    c = session.ctx.console; ser = c.find_series("arterial"); plan = ser.plan
    recon = next(r for r in ser.recons if r.plane == "axial")
    asked = []
    def ramp(t):                                  # 20 HU per second in the aorta: far from the window's ceiling
        asked.append(t); return {"aorta": 20.0 * (t - ser.started_at_s)}
    c.enhancement_at["arterial"] = ramp
    last = recon.image_count - 1
    ks = {}
    for k in range(last + 1):
        z = session.ctx.body_z(plan.start_mm + k * recon.increment_mm)
        if pack.slice_index(z) is not None and abs(pack.metrics.aorta_x_mm[pack.slice_index(z)]) < 1e6:
            ks.setdefault("first", k); ks["last"] = k
    grey = {}
    for name, k in ks.items():
        a = png_array(session.series_png("arterial", "axial", k)).astype(float)
        i = pack.slice_index(session.ctx.body_z(plan.start_mm + k * recon.increment_mm))
        px = int(round((pack.metrics.aorta_x_mm[i] - (plan.fov_center_x_mm - plan.fov_mm / 2)) / plan.fov_mm * 512))
        py = int(round((pack.metrics.aorta_y_mm[i] - (plan.fov_center_y_mm - plan.fov_mm / 2)) / plan.fov_mm * 512))
        grey[name] = a[py - 1:py + 2, px - 1:px + 2].mean()
    t_of = lambda k: ser.started_at_s + k * recon.increment_mm / (plan.end_mm - plan.start_mm) * plan.scan_time_s
    assert asked == pytest.approx([t_of(ks["first"]), t_of(ks["last"])])
    expected_hu = 20.0 * (t_of(ks["last"]) - t_of(ks["first"]))
    window_hu_per_grey = 400 / 255
    assert expected_hu > 20
    assert (grey["last"] - grey["first"]) * window_hu_per_grey == pytest.approx(expected_hu, abs=20)


def test_default_region_is_flagged_as_not_blood(session, pack):
    perform_until(session, pack, "monitoring_slice")
    do(session, "place_roi")
    check = _results(session, "place_roi")["Check"]
    assert check.alert and "not blood" in check.value and "aorta" in check.value
    assert "Contrast tab" in _step(session, "place_roi").info and "Show reference anatomy" in _step(session, "place_roi").info


def test_region_on_the_aorta_gets_no_blood_warning(session, pack):
    perform_until(session, pack, "place_roi")
    assert "Check" not in _results(session, "place_roi")


def test_abort_between_trigger_and_arterial_scan_ends_in_a_lost_phase_with_a_real_trigger_time(on_aorta):
    s = on_aorta; s.dispatch({"type": "perform", "step_id": "inject_and_arterial"})
    _run_for(s, 40, until=lambda snap: snap.console.tracking.state == "triggered")
    assert s.snapshot().scanner.beam_on is False and s.workflow.active_step_id == "inject_and_arterial"
    assert s.dispatch({"type": "abort"}).ok
    snap = s.snapshot(); tr = snap.console.tracking
    assert tr.state == "missed" and tr.triggered_at_s is not None
    assert {x.id: x for x in snap.console.series}["arterial"].status == "missed"
    assert any(e.kind == "alert" and "arterial" in e.text and "lost" in e.text for e in snap.log)
    s.advance(60)                                             # a hand-done venous scan is aimed at a time long past
    do(s, "scan_venous")
    log = [e.text for e in s.snapshot().log if e.kind == "alert"]
    assert any("was" in t and "s ago" in t for t in log)
    assert any("after its planned time" in e.text for e in s.snapshot().log)
