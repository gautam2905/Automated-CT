"""Console images from a patient's CT volume: topogram, axial slice, MPR reformat and ROI mean.

All images are 8-bit greyscale PNG bytes (no noise, no randomness). Frames follow the project
conventions: ``x_mm`` positive toward patient left, ``y_mm`` positive toward the back, both
measured from the centre of the stored slice; ``z_body_mm`` runs from the vertex toward the feet.
Enhancement is added HU per organ compartment, blurred with a 0.7-stored-pixel Gaussian first.
"""
from __future__ import annotations

import io
import math
from typing import Literal, Mapping

import numpy as np
from PIL import Image
from scipy.ndimage import affine_transform, gaussian_filter

from scansim.patient.contrast_pk import COMPARTMENTS
from scansim.patient.pack import PatientPack

AIR_HU = -1000.0
TOPOGRAM_WINDOW = (0.0, 12.0)
ENHANCEMENT_BLUR_PX = 0.7
MPR_WIDTH_PX = 512
_BLUR_PAD_PX = 4
_PNG_COMPRESS_LEVEL = 1

_ARTERIES = (
    "aorta", "brachiocephalic_trunk", "common_carotid_artery_left", "common_carotid_artery_right",
    "subclavian_artery_left", "subclavian_artery_right", "iliac_artery_left", "iliac_artery_right",
)
_VEINS = (
    "inferior_vena_cava", "superior_vena_cava", "iliac_vena_left", "iliac_vena_right",
    "brachiocephalic_vein_left", "brachiocephalic_vein_right",
)
_OWN = ("liver", "spleen", "pancreas", "heart")
_SOFT = ("adrenal_gland_left", "adrenal_gland_right", "stomach", "small_bowel", "duodenum", "colon")

LABEL_COMPARTMENT: dict[str, str] = {
    **{name: "aorta" for name in _ARTERIES},
    "portal_vein_and_splenic_vein": "portal_vein",
    **{name: "veins" for name in _VEINS},
    **{name: name for name in _OWN},
    "kidney_left": "kidney",
    "kidney_right": "kidney",
    **{name: "soft_tissue" for name in _SOFT},
}

Enhancement = Mapping[str, float] | None


# ---------------------------------------------------------------- helpers

def _png(grey: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(grey).save(buffer, format="PNG", compress_level=_PNG_COMPRESS_LEVEL)
    return buffer.getvalue()


def _to_grey(values: np.ndarray, centre: float, width: float) -> np.ndarray:
    if width <= 0:
        raise ValueError(f"window width must be positive, got {width}")
    scaled = (values - (centre - width / 2.0)) * (255.0 / width)
    return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)


def _label_lut(pack: PatientPack, enhancement: Enhancement) -> np.ndarray | None:
    """256-entry table: label value -> added HU. None when nothing would be added."""
    if not enhancement:
        return None
    unknown = set(enhancement) - set(COMPARTMENTS)
    if unknown:
        raise ValueError(f"unknown enhancement compartment(s) {sorted(unknown)}; expected from {list(COMPARTMENTS)}")
    lut = np.zeros(256, dtype=np.float32)
    for label, compartment in LABEL_COMPARTMENT.items():
        if compartment in enhancement and label in pack.label_index:
            lut[pack.label_index[label]] = float(enhancement[compartment])
    return lut if lut.any() else None


def _added_hu(labels: np.ndarray, lut: np.ndarray, axis: int | None) -> np.ndarray:
    """Added-HU map of ``labels`` (averaged over ``axis`` if given) blurred at stored resolution."""
    added = lut[np.asarray(labels)]
    if axis is not None:
        added = added.mean(axis=axis)
    return gaussian_filter(added, ENHANCEMENT_BLUR_PX)


def _slab(centres_mm: np.ndarray, position_mm: float, thickness_mm: float) -> tuple[int, int] | None:
    """Half-open index range of samples within the thickness; nearest sample if none. None if outside."""
    step = float(centres_mm[1] - centres_mm[0]) if len(centres_mm) > 1 else 1.0
    if not centres_mm[0] - step / 2 <= position_mm <= centres_mm[-1] + step / 2:
        return None
    half = max(thickness_mm, 0.0) / 2.0
    lo = int(np.searchsorted(centres_mm, position_mm - half - 1e-6, side="left"))
    hi = int(np.searchsorted(centres_mm, position_mm + half + 1e-6, side="right"))
    if hi <= lo:
        lo = min(max(int(np.argmin(np.abs(centres_mm - position_mm))), 0), len(centres_mm) - 1)
        hi = lo + 1
    return lo, hi


def _in_plane_centres(pack: PatientPack, axis: Literal["j", "i"]) -> np.ndarray:
    n = pack.ct.shape[1 if axis == "j" else 2]
    step = pack.spacing_mm[1 if axis == "j" else 2]
    return (np.arange(n) - (n - 1) / 2.0) * step


def _axis_map(start_mm: float, px_mm: float, src_origin_mm: float, src_step_mm: float) -> tuple[float, float]:
    """(origin, step) mapping output index -> fractional source index, for pixel centres at start+(r+0.5)px."""
    return (start_mm + 0.5 * px_mm - src_origin_mm) / src_step_mm, px_mm / src_step_mm


def _resample(img: np.ndarray, out_shape: tuple[int, int], rows: tuple[float, float], cols: tuple[float, float]):
    return affine_transform(
        img.astype(np.float32, copy=False), (rows[1], cols[1]), offset=(rows[0], cols[0]),
        output_shape=out_shape, order=1, mode="constant", cval=AIR_HU,
    )


def _check_extent(pack: PatientPack, z_from_mm: float, z_to_mm: float) -> None:
    if not z_to_mm > z_from_mm:
        raise ValueError(f"z_to_mm ({z_to_mm}) must be greater than z_from_mm ({z_from_mm})")
    pack.slice_index(z_from_mm)  # raises OutsideAnatomy
    pack.slice_index(z_to_mm)


# ---------------------------------------------------------------- topogram

def topogram_png(pack: PatientPack, view: Literal["AP", "LAT"], *, revealed: tuple[int, int]) -> bytes:
    """Topogram with only rows ``[from, to)`` visible; the rest is black."""
    topo = pack.topogram(view)
    rows = topo.pixels.shape[0]
    first, last = revealed
    if not 0 <= first <= last <= rows:
        raise ValueError(f"revealed rows {revealed} must satisfy 0 <= from <= to <= {rows}")
    grey = np.zeros(topo.pixels.shape, dtype=np.uint8)
    lo, hi = TOPOGRAM_WINDOW
    grey[first:last] = _to_grey(np.asarray(topo.pixels[first:last]), (lo + hi) / 2.0, hi - lo)
    return _png(grey)


# ---------------------------------------------------------------- axial

def _axial_hu(pack: PatientPack, z_body_mm: float, thickness_mm: float, enhancement: Enhancement) -> np.ndarray:
    k = pack.slice_index(z_body_mm)
    lo, hi = _slab(pack.z_body_mm, z_body_mm, thickness_mm) or (k, k + 1)
    hu = np.asarray(pack.ct[lo:hi], dtype=np.float32).mean(axis=0)
    lut = _label_lut(pack, enhancement)
    if lut is not None:
        hu += _added_hu(pack.labels[lo:hi], lut, axis=0)
    return hu


def axial_png(
    pack: PatientPack, z_body_mm: float, *, fov_mm: float, center_x_mm: float = 0.0, center_y_mm: float = 0.0,
    enhancement: Enhancement = None, window=(40, 400), size_px: int = 512, thickness_mm: float = 3.0,
) -> bytes:
    """Axial slice cropped to a square field of view, resampled to ``size_px`` (bilinear)."""
    if fov_mm <= 0 or size_px <= 0:
        raise ValueError(f"fov_mm and size_px must be positive, got {fov_mm} and {size_px}")
    hu = _axial_hu(pack, z_body_mm, thickness_mm, enhancement)
    px = fov_mm / size_px
    rows = _axis_map(center_y_mm - fov_mm / 2, px, _in_plane_centres(pack, "j")[0], pack.spacing_mm[1])
    cols = _axis_map(center_x_mm - fov_mm / 2, px, _in_plane_centres(pack, "i")[0], pack.spacing_mm[2])
    return _png(_to_grey(_resample(hu, (size_px, size_px), rows, cols), *window))


# ---------------------------------------------------------------- MPR

def _mpr_block(pack, plane, plane_mm, thickness_mm, ka, kb, enhancement) -> np.ndarray | None:
    """Slab-averaged ``[k, h]`` image (h = x for coronal, y for sagittal) for slices ``ka:kb``; None if outside."""
    coronal = plane == "coronal"
    span = _slab(_in_plane_centres(pack, "j" if coronal else "i"), plane_mm, thickness_mm)
    if span is None:
        return None
    lo, hi = span
    sel = (slice(ka, kb), slice(lo, hi), slice(None)) if coronal else (slice(ka, kb), slice(None), slice(lo, hi))
    axis = 1 if coronal else 2
    image = np.asarray(pack.ct[sel], dtype=np.float32).mean(axis=axis)
    lut = _label_lut(pack, enhancement)
    if lut is not None:
        image += _added_hu(pack.labels[sel], lut, axis=axis)
    return image


def mpr_png(
    pack: PatientPack, plane: Literal["coronal", "sagittal"], offset_mm: float, *, z_from_mm: float, z_to_mm: float,
    fov_mm: float, center_x_mm: float = 0.0, center_y_mm: float = 0.0, enhancement: Enhancement = None,
    window=(40, 400), thickness_mm: float = 5.0,
) -> bytes:
    """Coronal (right at image left) or sagittal (front at image left) reformat, head at the top."""
    if plane not in ("coronal", "sagittal"):
        raise ValueError(f"unknown plane {plane!r}; expected 'coronal' or 'sagittal'")
    if fov_mm <= 0:
        raise ValueError(f"fov_mm must be positive, got {fov_mm}")
    _check_extent(pack, z_from_mm, z_to_mm)
    px = fov_mm / MPR_WIDTH_PX
    height = max(1, round((z_to_mm - z_from_mm) / px))
    dz = pack.spacing_mm[0]
    ka = max(int(math.floor((z_from_mm - pack.z_body_mm[0]) / dz)) - 1, 0)
    kb = min(int(math.ceil((z_to_mm - pack.z_body_mm[0]) / dz)) + 2, pack.ct.shape[0])
    coronal = plane == "coronal"
    plane_mm = (center_y_mm if coronal else center_x_mm) + offset_mm
    block = _mpr_block(pack, plane, plane_mm, thickness_mm, ka, kb, enhancement)
    if block is None:
        return _png(_to_grey(np.full((height, MPR_WIDTH_PX), AIR_HU, dtype=np.float32), *window))
    rows_origin, rows_step = _axis_map(z_from_mm, px, pack.z_body_mm[ka], dz)
    h_axis = "i" if coronal else "j"
    h_centre = center_x_mm if coronal else center_y_mm
    h_step = pack.spacing_mm[2 if coronal else 1]
    cols = _axis_map(h_centre - fov_mm / 2, px, _in_plane_centres(pack, h_axis)[0], h_step)
    out = _resample(block, (height, MPR_WIDTH_PX), (rows_origin, rows_step), cols)
    return _png(_to_grey(out, *window))


# ---------------------------------------------------------------- ROI

def roi_mean_hu(
    pack: PatientPack, z_body_mm: float, x_mm: float, y_mm: float, r_mm: float, enhancement: Enhancement = None,
) -> float:
    """Mean HU inside a circle on the single slice nearest ``z_body_mm`` (air if wholly outside the slice)."""
    if r_mm < 0:
        raise ValueError(f"r_mm must be non-negative, got {r_mm}")
    k = pack.slice_index(z_body_mm)
    _, nj, ni = pack.ct.shape
    dy, dx = pack.spacing_mm[1], pack.spacing_mm[2]
    ci, cj = x_mm / dx + (ni - 1) / 2.0, y_mm / dy + (nj - 1) / 2.0
    reach_i, reach_j = r_mm / dx + _BLUR_PAD_PX, r_mm / dy + _BLUR_PAD_PX
    i0, i1 = max(int(math.floor(ci - reach_i)), 0), min(int(math.ceil(ci + reach_i)) + 1, ni)
    j0, j1 = max(int(math.floor(cj - reach_j)), 0), min(int(math.ceil(cj + reach_j)) + 1, nj)
    if i0 >= i1 or j0 >= j1:
        return AIR_HU
    hu = np.asarray(pack.ct[k, j0:j1, i0:i1], dtype=np.float32)
    lut = _label_lut(pack, enhancement)
    if lut is not None:
        hu = hu + _added_hu(pack.labels[k, j0:j1, i0:i1], lut, axis=None)
    jj, ii = np.mgrid[j0:j1, i0:i1]
    dist2 = ((ii - ci) * dx) ** 2 + ((jj - cj) * dy) ** 2
    inside = dist2 <= r_mm * r_mm
    if not inside.any():
        inside = dist2 == dist2.min()
    return float(hu[inside].mean())
