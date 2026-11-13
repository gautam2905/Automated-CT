import io
import time

import numpy as np
import pytest
from PIL import Image

from scansim.imaging.render import LABEL_COMPARTMENT, axial_png, mpr_png, roi_mean_hu, topogram_png
from scansim.patient.contrast_pk import COMPARTMENTS
from scansim.patient.pack import OutsideAnatomy


def png_array(b):
    return np.asarray(Image.open(io.BytesIO(b)))


def test_axial_shape_and_fov(pack):
    z = pack.landmarks["liver_top"] + 60
    a = png_array(axial_png(pack, z, fov_mm=350))
    assert a.shape[:2] == (512, 512) and a.std() > 10
    wide = png_array(axial_png(pack, z, fov_mm=700))
    assert (wide < 10).mean() > (a < 10).mean()  # more air around the body


def test_enhancement_reaches_the_aorta_only(pack):
    z = pack.landmarks["liver_top"] + 60
    k = pack.slice_index(z)
    ax, ay = pack.metrics.aorta_x_mm[k], pack.metrics.aorta_y_mm[k]
    base = roi_mean_hu(pack, z, ax, ay, 5)
    assert roi_mean_hu(pack, z, ax, ay, 5, {"aorta": 250}) - base == pytest.approx(250, rel=0.15)
    off = roi_mean_hu(pack, z, ax - 80, ay - 60, 5)
    assert roi_mean_hu(pack, z, ax - 80, ay - 60, 5, {"aorta": 250}) == pytest.approx(off, abs=3)


def test_topogram_hides_rows_not_yet_acquired(pack):
    a = png_array(topogram_png(pack, "AP", revealed=(100, 300)))
    assert a[:100].max() == 0 and a[300:].max() == 0 and a[100:300].std() > 5


def test_mpr_has_the_requested_extent(pack):
    L = pack.landmarks
    a = png_array(mpr_png(pack, "coronal", 0.0, z_from_mm=L["liver_top"] - 20, z_to_mm=L["iliac_crest"], fov_mm=400))
    assert a.ndim >= 2 and a.std() > 10


def test_outside_anatomy_is_an_error(pack):
    with pytest.raises(OutsideAnatomy):
        axial_png(pack, pack.data_range_mm[1] + 80, fov_mm=350)


def test_label_compartment_names_exist(pack):
    assert set(LABEL_COMPARTMENT.values()) <= set(COMPARTMENTS)
    assert set(LABEL_COMPARTMENT) <= set(pack.label_index)
    assert LABEL_COMPARTMENT["portal_vein_and_splenic_vein"] == "portal_vein"


def test_roi_mean_matches_stored_values_without_enhancement(pack):
    z = pack.landmarks["liver_top"] + 60
    k = pack.slice_index(z)
    ax, ay = pack.metrics.aorta_x_mm[k], pack.metrics.aorta_y_mm[k]
    assert 20 < roi_mean_hu(pack, z, ax, ay, 5) < 80  # unenhanced blood


def test_axial_enhancement_brightens_the_aorta_pixel(pack):
    z = pack.landmarks["liver_top"] + 60
    k = pack.slice_index(z)
    ax, ay = pack.metrics.aorta_x_mm[k], pack.metrics.aorta_y_mm[k]
    kwargs = dict(fov_mm=400, window=(40, 400))
    before = png_array(axial_png(pack, z, **kwargs))
    after = png_array(axial_png(pack, z, enhancement={"aorta": 300}, **kwargs))
    r, c = int(255.5 + ay * 512 / 400), int(255.5 + ax * 512 / 400)
    assert int(after[r, c]) - int(before[r, c]) > 60
    assert np.array_equal(before[:20], after[:20])  # far from any enhanced organ


def test_sagittal_and_coronal_heights_follow_extent(pack):
    z0, z1 = pack.landmarks["liver_top"], pack.landmarks["iliac_crest"]
    cor = png_array(mpr_png(pack, "coronal", 0.0, z_from_mm=z0, z_to_mm=z1, fov_mm=400))
    sag = png_array(mpr_png(pack, "sagittal", 0.0, z_from_mm=z0, z_to_mm=z1, fov_mm=400))
    expected_h = round((z1 - z0) / (400 / 512))
    assert cor.shape == sag.shape == (expected_h, 512) and sag.std() > 10


def test_mpr_outside_data_is_an_error(pack):
    with pytest.raises(OutsideAnatomy):
        mpr_png(pack, "coronal", 0.0, z_from_mm=100, z_to_mm=pack.data_range_mm[1] + 80, fov_mm=400)


def test_mpr_rejects_bad_plane_and_reversed_extent(pack):
    with pytest.raises(ValueError):
        mpr_png(pack, "oblique", 0.0, z_from_mm=100, z_to_mm=200, fov_mm=400)
    with pytest.raises(ValueError):
        mpr_png(pack, "coronal", 0.0, z_from_mm=200, z_to_mm=100, fov_mm=400)


def test_topogram_rejects_bad_revealed_range(pack):
    with pytest.raises(ValueError):
        topogram_png(pack, "AP", revealed=(300, 100))


def test_roi_is_fast(pack):
    z = pack.landmarks["liver_top"] + 60
    roi_mean_hu(pack, z, 0, 0, 5, {"aorta": 200})
    t0 = time.perf_counter()
    for _ in range(20):
        roi_mean_hu(pack, z, 0, 0, 5, {"aorta": 200})
    assert (time.perf_counter() - t0) / 20 < 0.01
