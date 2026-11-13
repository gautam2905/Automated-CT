"""What the page is told about where a number comes from, and how patients differ from one another."""
import pytest
from conftest import PROTOCOL_ID
from helpers import PRESCAN, do, perform_until, steps

from scansim.ct.scan_fields import scanner_source
from scansim.session import open_session

# Step fields pre-filled from a value the protocol file lists among its assumptions.
PROTOCOL_ASSUMED = {
    ("topogram_ap", "kv"): "topogram.kv", ("topogram_ap", "ma"): "topogram.ma",
    ("topogram_ap", "start_mm"): "topogram.start_from_landmark_mm", ("topogram_ap", "length_mm"): "topogram.length_mm",
    ("plan_ranges", "noncontrast.start_mm"): "series.noncontrast.default_start_mm",
    ("plan_ranges", "delayed.end_mm"): "series.delayed.default_end_mm",
    ("plan_ranges", "fov_mm"): "scan_defaults.fov_mm", ("confirm_settings", "pitch"): "scan_defaults.pitch",
    ("confirm_settings", "rotation_s"): "scan_defaults.rotation_s",
    ("confirm_settings", "collimation_mm"): "scan_defaults.collimation_mm",
    ("place_roi", "threshold_hu"): "contrast.timing.threshold_hu",
    ("arm_injector", "saline_ml"): "contrast.saline_ml", ("arm_injector", "saline_rate_ml_s"): "contrast.saline_rate_ml_s",
}
SYNTHETIC_ANSWERS = [("chart_check", "egfr"), ("chart_check", "prior_reaction"), ("chart_check", "on_metformin"),
                     ("safety_screening", "pregnancy"), ("iv_access", "gauge")]
FROM_THE_PATIENTS_CT = {("register_patient", "weight_kg"), ("register_patient", "height_cm")}


def _fields(session):
    return {(step.id, f.key): f for stage in session.snapshot().stages for step in stage.steps for f in step.fields}


def test_values_the_protocol_file_calls_assumed_are_tagged_assumed(session):
    fields, assumptions = _fields(session), session.ctx.protocol.assumptions
    for where, path in PROTOCOL_ASSUMED.items():
        assert path in assumptions and fields[where].source == "assumption", where
    # and what the sheet does state keeps the protocol tag
    assert fields[("arm_injector", "volume_ml")].source == "protocol"
    assert fields[("confirm_settings", "quality_ref_mas")].source == "protocol"


def test_a_value_the_scanner_file_calls_assumed_is_tagged_assumed(session):
    spec = session.ctx.spec
    assert "table.height_min_mm" in spec.assumptions
    loading = _fields(session)[("prepare_table", "loading_height_mm")]
    assert loading.source == "assumption" and "assumed" in loading.help
    assert scanner_source(spec, "table.height_min_mm") == "assumption"
    assert scanner_source(spec, "bore_diameter_mm") == "scanner"                 # sourced in the file


def test_synthetic_clinical_answers_are_tagged_assumed_not_as_the_patients(session):
    fields = _fields(session)
    for where in SYNTHETIC_ANSWERS:
        assert fields[where].source == "assumption" and "synthetic" in fields[where].help, where
    assert {where for where, f in fields.items() if f.source == "patient"} == FROM_THE_PATIENTS_CT
    assert set(session.snapshot().patient.estimated_fields) == {"age", "sex", "height_cm", "weight_kg"}


def test_the_priming_overfill_makes_the_loaded_contrast_an_assumed_value(session):
    contrast = _fields(session)[("load_injector", "contrast_ml")]
    assert contrast.value == 130 and contrast.source == "assumption" and "priming" in contrast.help


def test_step_results_that_quote_the_injector_pressure_say_it_is_assumed(session, pack):
    perform_until(session, pack, "arm_injector")
    st = steps(session.snapshot())
    flush = next(r.value for r in st["connect_injector"].results if r.label == "Test injection")
    limit = next(r.value for r in st["arm_injector"].results if r.label == "Pressure limit")
    assert "psi" in flush and "assumed" in flush and "325 psi" in limit and "assumed" in limit


# ---- patients differ, and so do seeds ----

def _set_up(DATA, patient_id, seed):
    session = open_session(DATA, PROTOCOL_ID, patient_id, seed=seed)
    for step_id in PRESCAN[:13]:                       # up to the patient lying on the table
        do(session, step_id)
    snap = session.snapshot()
    return (snap.pose.lateral_offset_mm, snap.pose.yaw_deg), (snap.patient.age, snap.patient.sex)


def test_two_patients_arrive_with_different_set_up_errors_under_the_same_seed(DATA):
    (pose_a, person_a), (pose_b, person_b) = _set_up(DATA, "sub-000", 1), _set_up(DATA, "sub-001", 1)
    assert pose_a != pose_b and person_a != person_b
    assert all(abs(offset) <= 25 and abs(yaw) <= 3 for offset, yaw in (pose_a, pose_b))


def test_the_seed_changes_the_set_up_and_the_same_seed_repeats_it(DATA):
    first, again, other = (_set_up(DATA, "sub-000", seed) for seed in (1, 1, 2))
    assert first == again and first[0] != other[0]


def test_a_negative_seed_is_refused_by_name(DATA):
    with pytest.raises(ValueError):
        open_session(DATA, PROTOCOL_ID, "sub-000", seed=-1)
