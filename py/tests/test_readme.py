"""The README states what is real, what is assumed and what the limits are. These tests keep those statements
in step with the data files and the code: a number that changes there must change in the README too."""
import os
import re
from pathlib import Path

import numpy as np
import pytest
from helpers import ORDER, do, steps

from scansim.ct import prescan_fields, workflow_aftercare, workflow_contrast, workflow_prescan, workflow_tracking
from scansim.patient import record
from scansim.patient.contrast_pk import ContrastModel, InjectionSegment
from scansim.protocols.library import load_protocol
from scansim.scanner_spec import load_scanner
from scansim.session import PRESSURE_LIMIT_PSI

ROOT = Path(__file__).resolve().parents[2]
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
PROTOCOL = load_protocol(ROOT / "data/protocols/ct/ohsu_ct_multiphase_liver.json")
SCANNER = load_scanner(ROOT / "data/scanners/siemens_somatom_force.json")


def section(title: str) -> str:
    """The text of one `## title` section, with the white space collapsed."""
    found = re.search(rf"## {re.escape(title)} (.*?)(?= ## |$)", README)
    assert found, f"the README has no section called {title!r}"
    return found.group(1)


def number_before(text: str, pattern: str) -> float:
    """The number captured by `pattern` in `text`; the test fails by name when the sentence is gone."""
    found = re.search(pattern, text)
    assert found, f"the README no longer says: {pattern}"
    return float(found.group(1))


# ---- the corrections ----

def test_add_a_patient_names_what_the_pack_tool_reads_and_what_the_tests_need():
    text = section("Add a patient")
    assert re.findall(r"--subject (\S+)", text) == ["sub-006"] and "there is no `sub-003`" in text
    tool = (ROOT / "tools/build_patient_pack.py").read_text(encoding="utf-8")
    reads = {"`/mnt/CT_SCAN/DATASET`": 'DEFAULT_DATASET = Path("/mnt/CT_SCAN/DATASET")',
             "`source_cache/multimodal_hc/<subject>/`": '"source_cache" / "multimodal_hc" / subject',
             "`short_abdominal_v1/`": '"short_abdominal_v1"', "`arrays/<subject>_AP.npy`": "_AP.npy",
             "`_LATERAL.npy`": "_LATERAL.npy", "`geometry/`": '"geometry"', "`--dataset`": '"--dataset"',
             "letters, digits, `_` and `-`": 'SUBJECT_NAME = re.compile(r"[A-Za-z0-9_-]+")'}
    for said, in_the_tool in reads.items():
        assert said in text and in_the_tool in tool, said
    tests = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "py/tests").glob("*.py")
                    if path.name != "test_readme.py") + (ROOT / "client/e2e/helpers.ts").read_text(encoding="utf-8")
    named = sorted(set(re.findall(r"sub-00\d", tests)) - {"sub-006"})       # sub-006 is only a made-up tool argument
    assert named == ["sub-000", "sub-001"] and "need `sub-000` and `sub-001` by name" in text
    assert "len(PATIENTS) >= 5" in tests and "at least five packs in all" in text


def test_scanner_geometry_is_called_a_proxy_and_only_sourced_numbers_are_called_real():
    text = section("What is real and what is assumed")
    real, assumed = text.split("Assumed:")[0], text.split("Assumed:")[1]
    assert "table and gantry geometry" not in real and "geometry" not in real
    assert "proxy" in assumed and "go.Top" in assumed
    for path in ("iso_height_mm", "laser_z_mm", "table.height_min_mm", "table.long_max_mm"):
        assert path in SCANNER.assumptions               # what the README calls a proxy or placeholder is one
    spec, t = SCANNER, SCANNER.table
    for path, said in {"bore_diameter_mm": f"{spec.bore_diameter_mm:g} mm bore",
                       "table.max_load_kg": f"{t.max_load_kg:g} kg table load",
                       "collimations_mm": f"{spec.collimations_mm[0]:g} mm collimation",
                       "max_pitch": f"maximum pitch of {spec.max_pitch:g}",
                       "dose_notification_ctdi_mgy": f"notification ({spec.dose_notification_ctdi_mgy:g} mGy)",
                       "dose_alert_ctdi_mgy": f"alert ({spec.dose_alert_ctdi_mgy:g} mGy)"}.items():
        assert path in spec.sources and said in real, said
    assert "aapm.org" in spec.sources["dose_alert_ctdi_mgy"] and "they are the AAPM's, not the scanner's" in real
    assert "topogram current" not in real            # the pre-filled 20 mA is the protocol's, and listed as assumed
    assert "topogram.ma" in PROTOCOL.assumptions


def test_the_readme_says_which_values_are_tagged_and_which_are_not(session):
    text = section("What is real and what is assumed")
    assert "shows in the app with the tag" not in text   # the old claim that every assumption is tagged
    assert "Not marked number by number" in text
    used = {f.source for stage in session.snapshot().stages for step in stage.steps for f in step.fields}
    assert used == {"protocol", "patient", "computed", "assumption"}
    for tag in ("`protocol`", "`patient`", "`computed`", "`assumed`"):
        assert tag in text
    assert "A `scanner` tag exists" in text and "no pre-filled value uses it today" in text


def test_every_label_the_instructions_quote_is_one_the_app_shows():
    text = section("Run an exam")
    headings = {line[3:].strip() for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")}
    quoted = set(re.findall(r'"([^"]+)"', text)) - headings          # a quoted heading points at another section
    assert {"Do again", "Plan ranges", "Link ranges", "Place ROI", "Inject and arterial scan", "Show reference anatomy",
            "Start scan manually", "CT Multiphase Liver"} <= quoted
    sources = [path.read_text(encoding="utf-8") for folder, pattern in (("client/src", "*.tsx"), ("py/scansim", "*.py"))
               for path in (ROOT / folder).rglob(pattern) if ".test." not in path.name]
    app = " ".join(("".join(sources) + PROTOCOL.title).split())
    for label in quoted:
        assert label in app, label
    for word in ("Start exam", "Seed", "Speed", "Reset", "Stop"):               # top-bar and card controls it names
        assert word in text and word in app, word
    assert "put a side away with the handle between it and the room" in text    # and the handles that hide a side
    assert all(label in app for label in ("Hide steps", "Show steps", "Hide console", "Show console"))


def test_the_instructions_say_how_pending_values_are_drawn_and_accepted():
    text = section("Run an exam")
    viewer = (ROOT / "client/src/console/TopogramViewer.tsx").read_text(encoding="utf-8")
    contrast = (ROOT / "client/src/console/ContrastTab.tsx").read_text(encoding="utf-8")
    assert "strokeDasharray" in viewer and "not accepted yet" in viewer and "not taken yet" in viewer
    assert "strokeDasharray" in contrast and 'data-testid="pending-roi"' in contrast
    for said in ("dashed box", "the box turns solid", "dashed line", "dashed circle", "the circle turns solid"):
        assert said in text, said
    assert len(PROTOCOL.series) == 4 and "the four series share one range" in text
    assert "plan the three scan ranges" not in text and "never triggers. \"Start" not in text


def test_other_exams_are_said_to_need_code_because_the_steps_name_this_exams_series():
    limits = section("Known limits")
    assert "Another exam needs code as well as a protocol file" in limits
    assert "Other exams need protocol files" not in limits
    ct = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "py/scansim/ct").glob("workflow*.py"))
    for series in PROTOCOL.series:                       # a protocol with other series would not run on these steps
        assert f'"{series.id}"' in ct, series.id
    assert '"liver_top"' in ct                           # and the reviews ask about the liver


def test_the_low_graphics_mode_is_said_to_be_blurry_and_the_only_one_the_browser_tests_cover():
    assert "blurry" in section("Start it") and "blurry" in section("Known limits")
    assert "only mode the browser tests cover" in section("Known limits")
    assert "`?lowgfx` only" in section("Run the tests")
    helpers = (ROOT / "client/e2e/helpers.ts").read_text(encoding="utf-8")
    assert "APP_URL = '/?lowgfx'" in helpers


# ---- the numbers the README quotes ----

def test_numbers_quoted_from_the_protocol_file_are_the_ones_in_it():
    text = section("What is real and what is assumed")
    c, t, by_id = PROTOCOL.contrast, PROTOCOL.contrast.timing, {s.id: s for s in PROTOCOL.series}
    scan = PROTOCOL.scan_defaults
    box = by_id["noncontrast"]
    assert "contrast.agent" in PROTOCOL.assumptions and "contrast.concentration_mgi_ml" in PROTOCOL.assumptions
    for said in (f"{c.volume_ml:g} mL of \"OMNI 350\" contrast at {c.rate_ml_s:g} mL/s",
                 f"that \"OMNI 350\" is Omnipaque 350 with {c.concentration_mgi_ml:g} mg of iodine per mL",
                 f"venous {by_id['venous'].timing.delay_s:g} s after the tracker",
                 f"delayed {by_id['delayed'].timing.delay_s / 60:g} minutes after the injection start",
                 f"reference {scan.kv} kV and quality reference {scan.quality_ref_mas:g} mAs",
                 f"the {c.saline_ml:g} mL saline chaser", f"the {t.threshold_hu:g} HU tracking threshold",
                 f"the {t.monitoring_delay_s:g} s monitoring delay", f"the {t.monitoring_interval_s:g} s interval",
                 f"the {t.max_monitoring_s:g} s monitoring limit",
                 f"the {t.post_trigger_delay_s:g} s post-trigger delay",
                 f"{PROTOCOL.positioning.landmark_fraction_of_height * 100:g} percent of the patient's height",
                 f"{box.default_start_mm:g} to {box.default_end_mm:g} mm"):
        assert said in text, said


def test_numbers_quoted_from_the_modules_are_the_ones_in_force():
    text, limits = section("What is real and what is assumed"), section("Known limits")
    low, high = workflow_tracking.BLOOD_BASELINE_HU
    for said in (f"up to {workflow_prescan.MAX_OFFSET_MM:g} mm and {workflow_prescan.MAX_YAW_DEG:g} degrees",
                 f"a {record.DEFAULT_MAX_HOLD_S:g} s breath-hold limit",
                 f"{prescan_fields.INJECTOR_OVERFILL_ML:g} mL of contrast drawn up for priming",
                 f"a {prescan_fields.TEST_VOLUME_ML:g} mL saline test flush",
                 f"{prescan_fields.SYRINGE_ML:g} mL syringes",
                 f"the tabletop {prescan_fields.TABLE_HEIGHT_BELOW_ISO_MM:g} mm below the isocentre",
                 f"{workflow_tracking.MONITORING_KV} kV and {workflow_tracking.MONITORING_MAS:g} mAs for a "
                 "monitoring scan",
                 f"{low:g} to {high:g} HU as \"blood\"",
                 f"a venous scan {workflow_contrast.FALLBACK_VENOUS_S:g} s after the injection start",
                 f"{workflow_aftercare.OBSERVE_DEFAULT_MIN:g} minutes of observation",
                 f"eGFR {record.DEFAULT_EGFR}", f"a {record.DEFAULT_IV_GAUGE} cannula",
                 f"Cardiac output is {record.REFERENCE_CARDIAC_OUTPUT_L_MIN:g} L/min"):
        assert said in text, said
    assert f"the {PRESSURE_LIMIT_PSI:g} psi limit" in limits
    assert f"starts {workflow_contrast.FALLBACK_VENOUS_S:g} s after the injection start" in limits


# ---- the limits ----

def test_the_limits_cover_every_topic_the_project_review_asked_for():
    """A checklist of the sentences, not of their truth: the tests below check the numbers and the behaviour."""
    limits = section("Known limits")
    for said in ("every voxel of an organ label", "has not been validated",                      # the contrast model
                 "It leaves out the topograms, the monitoring slice and the bolus-monitoring scans",   # the dose total
                 "has a row of its own on the Dose tab, so the rows add up to the total",
                 "`k x rate^2 x viscosity`", "None of these constants is sourced",               # the pressure model
                 "is not physical, and it has not been retuned",                                 # the late curve
                 "With no trigger and no manual start",                                          # the no-trigger timing
                 "Open defect:"):
        assert said in limits, said


def test_the_late_contrast_curve_is_described_as_the_model_draws_it():
    limits = section("Known limits")
    weight = number_before(limits, r"For a (\d+) kg patient and the pre-filled injection")
    c = PROTOCOL.contrast
    model = ContrastModel(weight, record.REFERENCE_CARDIAC_OUTPUT_L_MIN)
    model.add_segment(InjectionSegment(0.0, c.volume_ml / c.rate_ml_s, c.rate_ml_s, c.concentration_mgi_ml))
    t = np.arange(0.0, 2400.0, 0.5)
    aorta, liver, portal = (model.curve(name, t) for name in ("aorta", "liver", "portal_vein"))
    after_peak = slice(int(aorta.argmax()), int(np.searchsorted(t, 240.0)))
    dip = after_peak.start + int(aorta[after_peak].argmin())
    at = lambda curve, seconds: float(curve[int(np.searchsorted(t, seconds))])
    assert aorta[dip] == pytest.approx(number_before(limits, r"the aorta falls to about (\d+) HU one minute"), abs=3)
    assert t[dip] == pytest.approx(60, abs=6)
    assert at(aorta, 240) == pytest.approx(number_before(limits, r"rises again to about (\d+) HU"), abs=3)
    assert at(aorta, 240) > 1.5 * aorta[dip]                                 # it does rise again: the shape in question
    assert liver.max() == pytest.approx(number_before(limits, r"The liver peaks at about (\d+) HU"), abs=3)
    assert t[liver.argmax()] == pytest.approx(
        number_before(limits, r"The liver peaks at about \d+ HU at (\d+) s"), abs=3)
    assert max(at(liver, s) for s in (150, 240, 600)) == pytest.approx(
        number_before(limits, r"is back to about (\d+) HU from 2.5 minutes on"), abs=2)
    assert t[portal.argmax()] == pytest.approx(number_before(limits, r"peaks \(about (\d+) s and \d+ s\)"), abs=3)
    minutes = number_before(limits, r"Every curve drops to zero (\d+) minutes after the injection")
    assert at(aorta, minutes * 60 - 60) > 10 and at(aorta, minutes * 60 + c.volume_ml / c.rate_ml_s + 5) == 0


def test_the_no_trigger_timing_is_described_as_it_happens(session):
    limits, run = section("Known limits"), section("Run an exam")
    for step_id in ORDER[: ORDER.index("inject_and_arterial")]:               # pre-filled values: the region misses
        if step_id == "review_noncontrast":
            answer = {"type": "set_field", "step_id": step_id, "key": "liver_included", "value": "yes"}
            assert session.dispatch(answer).ok
        do(session, step_id)
    assert session.dispatch({"type": "perform", "step_id": "inject_and_arterial"}).ok
    ended = None
    for _ in range(4000):
        session.advance(0.05)
        snap = session.snapshot()
        if snap.console.tracking.state == "missed":
            ended = snap.clock.contrast_timer_s
            break
    said = number_before(limits, r"about (\d+) s after the injection starts with the pre-filled timing")
    assert ended == pytest.approx(said, abs=1.5)
    assert number_before(run, r"monitoring stops about (\d+) s after the injection starts") == said
    timing = PROTOCOL.contrast.timing
    own_limit = timing.monitoring_delay_s + timing.max_monitoring_s
    assert own_limit - ended == pytest.approx(number_before(limits, r"(\d+) s before monitoring's own limit"), abs=1.5)
    session.run_until_idle()
    snap = session.snapshot()
    venous = {s.id: s for s in snap.console.series}["venous"]
    assert steps(snap)["scan_delayed"].status == "done"
    beam_on = venous.started_at_s - session.ctx.injector.started_at_s
    assert beam_on == pytest.approx(workflow_contrast.FALLBACK_VENOUS_S, abs=0.5)


def test_a_region_on_a_kidney_triggers_later_than_one_on_the_aorta_as_the_readme_says(DATA, pack):
    from helpers import aorta_in_plan_frame, perform_until
    from scansim.session import open_session
    said = "A region on another organ that enhances, such as a kidney or the spleen, can still trigger, later"
    assert said in section("Run an exam")
    kidney_level = (pack.landmarks["kidney_top"] + pack.landmarks["kidney_bottom"]) / 2.0
    triggered = {}
    for organ in ("aorta", "kidney_left"):
        s = open_session(DATA, PROTOCOL.id, "sub-000", seed=1)
        perform_until(s, pack, "review_noncontrast")
        level = round(kidney_level - s.ctx.landmark_z_body_mm)               # a level that shows both
        assert s.dispatch({"type": "set_field", "step_id": "monitoring_slice", "key": "slice_mm", "value": level}).ok
        do(s, "monitoring_slice")
        if organ == "aorta":
            x, y = aorta_in_plan_frame(s, pack)
        else:
            k = pack.slice_index(s.ctx.body_z(level))
            rows, cols = np.nonzero(pack.labels[k] == pack.label_index[organ])
            assert rows.size, "the left kidney is not in the monitoring slice"
            plan = next(x for x in s.snapshot().console.series if x.id == "arterial").plan
            x = (cols.mean() - (pack.labels.shape[2] - 1) / 2.0) * pack.spacing_mm[2] - plan.fov_center_x_mm
            y = (rows.mean() - (pack.labels.shape[1] - 1) / 2.0) * pack.spacing_mm[1] - plan.fov_center_y_mm
        for key, value in (("roi_x_mm", float(x)), ("roi_y_mm", float(y))):
            assert s.dispatch({"type": "set_field", "step_id": "place_roi", "key": key, "value": value}).ok
        for step_id in ("place_roi", "arm_injector", "inject_and_arterial"):
            do(s, step_id)
        tracking = s.snapshot().console.tracking
        assert tracking.state == "triggered", organ
        triggered[organ] = tracking.triggered_at_s - s.ctx.injector.started_at_s
    assert triggered["kidney_left"] > triggered["aorta"] + 3


def test_the_open_defect_the_readme_names_is_still_there(session, pack):
    """An injection at the lowest rate outlives the exam. When this is fixed, the README line goes too."""
    from helpers import perform_until
    perform_until(session, pack, "place_roi")
    slowest = next(f.min for f in steps(session.snapshot())["arm_injector"].fields if f.key == "rate_ml_s")
    assert f"{slowest:g} mL/s" in section("Known limits")
    assert session.dispatch({"type": "set_field", "step_id": "arm_injector", "key": "rate_ml_s", "value": slowest}).ok
    perform_until(session, pack, ORDER[-1])
    snap = session.snapshot()
    assert steps(snap)["close_exam"].status == "done" and snap.injector.state == "injecting"


# ---- the commands the README gives ----

def test_the_launcher_the_readme_calls_can_be_run_as_written():
    assert "./run_sim.sh" in section("Start it")
    assert os.access(ROOT / "run_sim.sh", os.X_OK), "run_sim.sh is not executable: ./run_sim.sh fails after a clone"


def test_the_browser_test_settings_the_readme_names_exist():
    text = section("Run the tests")
    config = (ROOT / "client/playwright.config.ts").read_text(encoding="utf-8")
    launcher = (ROOT / "run_sim.sh").read_text(encoding="utf-8")
    assert "`SIM_CHROME`" in text and "process.env.SIM_CHROME" in config
    assert "`SIM_PYTHON`" in text and "SIM_PYTHON" in launcher
