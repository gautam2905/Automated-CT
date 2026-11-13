import math

import pytest
from helpers import PRESCAN, do, steps

from scansim.examples import sample_snapshot
from scansim.session import open_session
from scansim.snapshot import Snapshot

PROTOCOL = "ohsu.ct.multiphase_liver"


def test_prescan_runs_with_defaults(session):
    for s in PRESCAN: do(session, s)
    snap = session.snapshot(); st = steps(snap)
    assert all(st[s].status == "done" for s in PRESCAN) and st["topogram_ap"].status == "ready"
    assert snap.pose.stage == "lying" and snap.pose.entry == "feet_first" and snap.pose.arms == "up"
    assert snap.pose.lateral_offset_mm == 0 and snap.pose.iv_connected
    assert snap.room.technologist_at == "console" and not snap.room.door_open and not snap.room.lasers_on
    assert snap.table.zero_long_mm is not None and snap.injector.state == "connected"
    assert 1500 < snap.clock.sim_time_s < 3000          # about half an hour of preparation


def test_out_of_order_is_refused_with_a_reason(session):
    r = session.dispatch({"type": "perform", "step_id": "set_landmark"})
    assert not r.ok and r.error and steps(session.snapshot())["set_landmark"].status == "locked"


def test_perform_while_running_changes_nothing(session):
    for s in PRESCAN[:11]: do(session, s)
    assert session.dispatch({"type": "perform", "step_id": "prepare_table"}).ok
    before = session.snapshot().model_dump_json()
    r = session.dispatch({"type": "perform", "step_id": "prepare_table"})
    assert not r.ok and session.snapshot().model_dump_json() == before


def test_bad_field_value_comes_back_as_an_error(session):
    r = session.dispatch({"type": "set_field", "step_id": "chart_check", "key": "egfr", "value": "abc"})
    assert not r.ok and "eGFR" in r.error


def test_landmark_default_is_the_proportion_estimate_not_the_anatomy(session, pack):
    f = {x.key: x for x in steps(session.snapshot())["set_landmark"].fields}["distance_from_head_mm"]
    assert f.source == "assumption" and f.value == pytest.approx(0.27 * pack.stature_mm, abs=1)


def test_estimated_defaults_are_rounded_for_display_and_stay_marked_estimated(session):
    st = steps(session.snapshot())
    landmark = {x.key: x.value for x in st["set_landmark"].fields}["distance_from_head_mm"]
    register = {x.key: x.value for x in st["register_patient"].fields}
    assert landmark == round(landmark) and round(register["height_cm"], 1) == register["height_cm"]
    assert round(register["weight_kg"], 1) == register["weight_kg"]
    for s in PRESCAN[:9]: do(session, s)
    do(session, "register_patient")                      # untouched defaults must not clear the estimate flags
    assert {"height_cm", "weight_kg"} <= set(session.snapshot().patient.estimated_fields)


def test_table_height_too_low_for_the_bore_is_explained(session):
    for s in PRESCAN[:15]: do(session, s)
    low = session.snapshot().table.height_min_mm
    assert session.dispatch({"type": "set_field", "step_id": "table_height", "key": "height_mm", "value": low}).ok
    do(session, "table_height")
    session.dispatch({"type": "perform", "step_id": "set_landmark"}); session.run_until_idle()
    snap = session.snapshot()
    assert steps(snap)["set_landmark"].status != "done" and any(e.kind == "alert" for e in snap.log)


def test_same_seed_same_result(DATA):
    a, b = (open_session(DATA, "ohsu.ct.multiphase_liver", "sub-000", seed=3) for _ in range(2))
    for s in PRESCAN:
        do(a, s); do(b, s)
    ja, jb = a.snapshot().model_dump(), b.snapshot().model_dump()
    ja.pop("session_id"); jb.pop("session_id"); assert ja == jb


def test_reference_is_hidden_by_default(session):
    for s in PRESCAN: do(session, s)
    assert session.snapshot().console.reference == []
    session.dispatch({"type": "set_reference", "on": True})
    assert {r.name for r in session.snapshot().console.reference} >= {"liver_top", "iliac_crest"}


# ---- additions beyond the brief ----

def _set(session, step_id, key, value):
    return session.dispatch({"type": "set_field", "step_id": step_id, "key": key, "value": value})


def test_live_stage_and_step_titles_match_the_sample_snapshot(session):
    live = [(g.id, g.title, [(s.id, s.title) for s in g.steps]) for g in session.snapshot().stages]
    sample = [(g.id, g.title, [(s.id, s.title) for s in g.steps]) for g in sample_snapshot().stages]
    assert live == sample


def test_sample_range_fields_have_the_keys_the_engine_sends(session):
    def keys(snapshot):
        return [f.key for g in snapshot.stages for s in g.steps if s.id == "plan_ranges" for f in s.fields]
    assert keys(sample_snapshot()) == keys(session.snapshot())
    assert "noncontrast.start_mm" in keys(sample_snapshot()) and "start_mm" not in keys(sample_snapshot())


def test_snapshot_round_trips_and_ids_are_distinct(DATA):
    a, b = open_session(DATA, PROTOCOL, "sub-000"), open_session(DATA, PROTOCOL, "sub-000")
    assert a.session_id != b.session_id
    assert Snapshot.model_validate_json(a.snapshot().model_dump_json()).session_id == a.session_id
    assert open_session(DATA, PROTOCOL, "sub-000", session_id="mine").session_id == "mine"


def test_unknown_step_field_and_action_are_errors_not_exceptions(session):
    assert not session.dispatch({"type": "perform", "step_id": "nope"}).ok
    assert not session.dispatch({"type": "set_field", "step_id": "chart_check", "key": "nope", "value": 1}).ok
    r = session.dispatch({"type": "teleport"})
    assert not r.ok and r.error


def test_open_session_rejects_unknown_protocol_and_unsafe_patient_id(DATA):
    with pytest.raises(ValueError):
        open_session(DATA, "no.such.protocol", "sub-000")
    with pytest.raises(ValueError):
        open_session(DATA, PROTOCOL, "../scanners")


def test_time_scale_accepts_one_to_fifty_only(session):
    assert session.dispatch({"type": "set_time_scale", "value": 20}).ok and session.time_scale == 20
    for bad in (0.5, 51, math.nan):
        assert not session.dispatch({"type": "set_time_scale", "value": bad}).ok
    assert session.time_scale == 20 and session.snapshot().clock.time_scale == 20


def test_manual_start_has_nothing_to_start_yet(session):
    r = session.dispatch({"type": "manual_start"})
    assert not r.ok and "Nothing to start manually" in r.error


def test_identification_and_consent_block_while_unticked(session):
    do(session, "order_received"); do(session, "protocol_assigned"); do(session, "chart_check")
    assert _set(session, "identify_patient", "name_confirmed", False).ok
    t0 = session.snapshot().clock.sim_time_s
    r = session.dispatch({"type": "perform", "step_id": "identify_patient"})
    assert not r.ok and steps(session.snapshot())["identify_patient"].status == "ready"
    assert session.snapshot().clock.sim_time_s == t0          # a refusal costs no time
    assert _set(session, "identify_patient", "name_confirmed", True).ok
    do(session, "identify_patient")


def test_pregnancy_yes_needs_radiologist_review(session):
    for s in PRESCAN[:4]: do(session, s)
    assert _set(session, "safety_screening", "pregnancy", "yes").ok
    r = session.dispatch({"type": "perform", "step_id": "safety_screening"})
    assert not r.ok and "radiologist review required" in r.error


def test_low_egfr_raises_an_alert_result(session):
    do(session, "order_received"); do(session, "protocol_assigned")
    assert _set(session, "chart_check", "egfr", 25).ok
    do(session, "chart_check")
    assert any(r.alert for r in steps(session.snapshot())["chart_check"].results)


def test_read_only_fields_cannot_be_edited(session):
    f = {x.key: x for x in steps(session.snapshot())["protocol_assigned"].fields}["protocol"]
    assert f.source == "protocol" and not f.editable
    do(session, "order_received")
    assert not _set(session, "protocol_assigned", "protocol", "something else").ok


def test_positioning_places_the_patient_within_the_seeded_offsets(session, pack):
    for s in PRESCAN[:13]: do(session, s)
    snap = session.snapshot()
    assert snap.pose.stage == "lying" and snap.pose.stature_mm == pack.stature_mm
    assert abs(snap.pose.lateral_offset_mm) <= 25 and abs(snap.pose.yaw_deg) <= 3
    assert snap.pose.anchor_t_mm == 120 and {m.name for m in snap.pose.surface_marks} == {
        "sternal_notch", "xiphoid", "iliac_crest"}
    do(session, "centre_patient")
    assert session.snapshot().pose.lateral_offset_mm == 0 and session.snapshot().pose.yaw_deg == 0
    assert steps(session.snapshot())["centre_patient"].results


def test_surface_marks_only_once_the_patient_lies_down(session):
    assert session.snapshot().pose.surface_marks == []


def test_table_position_is_the_planning_coordinate_of_the_scan_plane(session):
    for s in PRESCAN: do(session, s)
    ctx = session.ctx
    assert ctx.landmark_z_body_mm == pytest.approx(0.27 * ctx.pack.stature_mm, abs=1)
    # Zeroed with the landmark at the laser, so the scan plane is laser_z_mm away, toward the feet.
    assert session.snapshot().table.position_mm == pytest.approx(ctx.spec.laser_z_mm)
    ctx.table.long_mm += 100                                  # 100 mm further in: toward the head
    assert session.snapshot().table.position_mm == pytest.approx(ctx.spec.laser_z_mm - 100)
    ctx.table.long_mm = ctx.long_for(0.0)                     # landmark in the scan plane
    assert session.snapshot().table.position_mm == pytest.approx(0.0, abs=1e-6)
    ctx.table.long_mm = ctx.long_for(-120.0)
    assert session.snapshot().table.position_mm == pytest.approx(-120.0, abs=1e-6)


def test_position_is_unknown_until_zero_is_set(session):
    assert session.snapshot().table.position_mm is None


def test_repeating_table_height_sends_landmark_back_to_redo(session):
    for s in PRESCAN: do(session, s)
    assert _set(session, "table_height", "height_mm", 800).ok
    do(session, "table_height")
    st = steps(session.snapshot())
    assert st["set_landmark"].status == "redo" and st["leave_room"].status == "redo"
    assert st["leave_room"].blocked_by



def test_auto_next_runs_once_when_nothing_is_running_and_abort_clears_it(session):
    session.ctx.auto_next = "order_received"
    session.advance(0.1)
    assert steps(session.snapshot())["order_received"].status == "done" and session.ctx.auto_next is None
    session.ctx.auto_next = "protocol_assigned"
    session.dispatch({"type": "abort"})
    assert session.ctx.auto_next is None


def test_auto_next_refusal_is_logged_not_raised(session):
    session.ctx.auto_next = "set_landmark"
    session.advance(0.1)
    assert session.ctx.auto_next is None and any(e.kind == "alert" for e in session.snapshot().log)


def test_aborting_the_patient_getting_on_the_table_puts_the_patient_back(session):
    for s in PRESCAN[:12]: do(session, s)
    assert session.dispatch({"type": "perform", "step_id": "patient_on_table"}).ok
    session.advance(12)
    assert session.snapshot().pose.stage == "standing"
    assert session.dispatch({"type": "abort"}).ok
    snap = session.snapshot()
    assert snap.pose.stage == "away" and steps(snap)["patient_on_table"].status == "ready"
    assert session.ctx.placement is None


def test_later_steps_exist_but_are_not_built_yet(session):
    for s in PRESCAN: do(session, s)
    r = session.dispatch({"type": "perform", "step_id": "monitoring_slice"})      # the tracking stage is still a stub
    assert not r.ok
    assert steps(session.snapshot())["monitoring_slice"].status == "locked"
    assert steps(session.snapshot())["topogram_ap"].status == "ready"


def test_images_are_refused_until_something_exists_to_draw(session):
    for call in (lambda: session.topogram_png("AP"), lambda: session.series_png("arterial", "axial", 0),
                 session.tracking_png):
        with pytest.raises(LookupError):
            call()


def test_breathing_runs_from_the_start_and_snapshot_is_cheap(session):
    session.advance(3.0)
    assert session.snapshot().pose.breath != 0.0
    assert session.ctx.console.view(session.ctx).topograms == []


def test_connect_injector_can_be_retried_after_an_abort(session):
    for s in PRESCAN[:14]: do(session, s)
    assert session.dispatch({"type": "perform", "step_id": "connect_injector"}).ok
    session.advance(1.0)
    assert session.dispatch({"type": "abort"}).ok
    assert session.snapshot().injector.state == "connected" and not session.snapshot().pose.iv_connected
    do(session, "connect_injector")
    snap = session.snapshot()
    assert steps(snap)["connect_injector"].status == "done" and snap.pose.iv_connected
    assert snap.injector.state == "connected"


def test_auto_next_with_an_unknown_step_fails_loudly_and_by_name(session):
    session.ctx.auto_next = "no_such_step"
    with pytest.raises(LookupError, match="no_such_step"):
        session.advance(0.1)
    assert session.ctx.auto_next is None


def test_allergy_default_is_labelled_an_assumption(session):
    f = {x.key: x for x in steps(session.snapshot())["safety_screening"].fields}["allergy"]
    assert f.source == "assumption" and f.help
