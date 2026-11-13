import numpy as np
import pytest

from scansim.patient.pack import OutsideAnatomy


def test_orientation(pack):
    k = pack.slice_index(pack.landmarks["liver_top"] + 60)
    ys, xs = np.nonzero(pack.labels[k] == pack.label_index["liver"])
    assert xs.mean() < pack.ct.shape[2] / 2                       # liver on the image left
    spine_ids = [v for n, v in pack.label_index.items() if n.startswith("vertebrae_")]
    assert np.nonzero(np.isin(pack.labels[k], spine_ids))[0].mean() > ys.mean()   # spine behind the liver centre
    assert pack.slice_index(pack.landmarks["vertex"] + 40) < k    # head before abdomen


def test_landmark_order(pack):
    L = pack.landmarks
    assert L["vertex"] == 0 < L["sternal_notch"] < L["xiphoid"] < L["liver_bottom"]
    assert L["lung_apex"] < L["liver_top"] < L["liver_bottom"]
    assert L["iliac_crest_high"] <= L["iliac_crest"] < L["femoral_head"] < L["lesser_trochanter"] <= L["data_bottom"]


def test_agrees_with_dataset_reference(pack):
    L = pack.landmarks                                            # reference_anatomy/sub-000.json: liver -525 to -693, hips -761 and -769
    assert abs((L["liver_bottom"] - L["liver_top"]) - 168.0) <= 2.0
    assert abs((L["iliac_crest"] - L["liver_top"]) - 244.0) <= 2.0
    assert abs((L["iliac_crest"] - L["iliac_crest_high"]) - 8.0) <= 2.0


def test_topogram_rows_match_dataset_label(pack):
    t = pack.topogram("AP")                                       # samples.jsonl: top_row 228.5 is liver top + 10 mm margin
    row = (pack.landmarks["liver_top"] - t.z_body_of_row0) / t.row_mm
    assert t.pixels.shape == (512, 512) and t.row_mm == 3.0
    assert abs(row - (228.5 + 10.0 / 3.0)) < 1.0


def test_estimates_and_metrics(pack):
    assert 1450 <= pack.stature_mm <= 2050 and 40 <= pack.weight_kg <= 150
    k = pack.slice_index(pack.landmarks["liver_top"] + 60)
    m = pack.metrics
    assert 150 < m.ap_mm[k] < 400 and 250 < m.lat_mm[k] < 600 and 200 < m.dw_mm[k] < 450
    assert np.isfinite(m.aorta_x_mm[k]) and np.isnan(m.aorta_x_mm[pack.slice_index(40)])


def test_outside_anatomy(pack):
    with pytest.raises(OutsideAnatomy):
        pack.slice_index(pack.data_range_mm[1] + 50)
