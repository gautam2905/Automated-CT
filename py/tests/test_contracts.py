from pathlib import Path

import pytest
from pydantic import ValidationError

from scansim.actions import parse_action
from scansim.examples import sample_snapshot
from scansim.protocols.library import load_protocol
from scansim.scanner_spec import load_scanner
from scansim.snapshot import Snapshot

SHEET = Path("/mnt/CT_SCAN/PROTOCOLS/extracted_text/ct-multiphase-liver-and-ct-multiphase-liver-with-pelvis-07.02.26.txt")
DATA = Path(__file__).resolve().parents[2] / "data"
norm = lambda s: " ".join(s.split()).lower()


def test_liver_protocol_matches_sheet():
    p = load_protocol(DATA / "protocols/ct/ohsu_ct_multiphase_liver.json")
    assert (p.positioning.orientation, p.positioning.entry, p.positioning.arms) == ("supine", "feet_first", "up")
    assert [s.id for s in p.series] == ["noncontrast", "arterial", "venous", "delayed"]
    assert (p.contrast.volume_ml, p.contrast.rate_ml_s, p.contrast.concentration_mgi_ml) == (125, 4.0, 350)
    assert p.scan_defaults.quality_ref_mas == 147 and p.scan_defaults.kv == 120
    s = {x.id: x for x in p.series}
    assert s["noncontrast"].timing.type == "before_contrast"
    assert s["arterial"].timing.type == "at_trigger"
    assert (s["venous"].timing.type, s["venous"].timing.delay_s) == ("after_trigger", 55)
    assert (s["delayed"].timing.type, s["delayed"].timing.delay_s) == ("after_injection_start", 240)
    assert [r.plane for r in s["arterial"].recons] == ["axial", "coronal", "sagittal"]
    assert [r.plane for r in s["noncontrast"].recons] == ["axial"]
    assert (s["venous"].recons[0].thickness_mm, s["venous"].recons[0].increment_mm) == (3, 1.5)
    assert all(x.breath_hold == "inspiration" for x in p.series)


def test_every_quote_is_in_the_sheet():
    p = load_protocol(DATA / "protocols/ct/ohsu_ct_multiphase_liver.json")
    sheet = norm(SHEET.read_text())
    assert len(p.quotes) >= 12
    for path, quote in p.quotes.items():
        assert norm(quote) in sheet, path


def test_values_not_in_the_sheet_are_declared():
    p = load_protocol(DATA / "protocols/ct/ohsu_ct_multiphase_liver.json")
    for path in ["contrast.saline_ml", "contrast.timing.threshold_hu", "contrast.timing.post_trigger_delay_s",
                 "topogram.length_mm", "series.noncontrast.default_start_mm", "scan_defaults.pitch",
                 "positioning.landmark_fraction_of_height"]:
        assert path in p.assumptions


def test_scanner_numbers_have_a_source_or_are_declared():
    spec = load_scanner(DATA / "scanners/siemens_somatom_force.json")
    for path in ["bore_diameter_mm", "table.long_max_mm", "table.max_load_kg", "max_pitch", "laser_z_mm",
                 "iso_height_mm", "ctdi_mgy_per_100mas", "dose_alert_ctdi_mgy"]:
        assert path in spec.sources or path in spec.assumptions
    assert spec.bore_diameter_mm == 780 and spec.table.max_load_kg == 307
    assert 120 in spec.kv_options and spec.table.height_min_mm < spec.table.height_min_in_bore_mm < spec.table.height_max_mm


def test_sample_snapshot_round_trips():
    s = sample_snapshot()
    assert Snapshot.model_validate_json(s.model_dump_json()) == s
    assert s.modality == "CT" and len(s.stages) == 11 and len(s.console.series) == 4


def test_unknown_action_is_rejected():
    with pytest.raises(ValidationError):
        parse_action({"type": "explode"})
    assert parse_action({"type": "perform", "step_id": "x"}).step_id == "x"
