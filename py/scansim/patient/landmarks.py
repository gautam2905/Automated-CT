"""Anatomical landmarks and per-slice body measurements from a patient's CT and organ labels.

All arrays follow the pack orientation: ``[k, j, i]`` = head to feet, front to back,
patient right to patient left. ``z_body_mm`` is measured from the vertex toward the feet.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

BODY_THRESHOLD_HU = -300.0
MIDLINE_WINDOW_MM = 15.0
FEMORAL_HEAD_BELOW_TOP_MM = 25.0
LESSER_TROCHANTER_BELOW_TOP_MM = 75.0
WEIGHT_MASS_FRACTION = 0.80
STATURE_FRACTION_AT_FEMORAL_HEAD = 0.47
STATURE_LIMITS_MM = (1450.0, 2050.0)

_STRUCTURE_8 = ndimage.generate_binary_structure(2, 2)


def _label_ids(label_index: dict[str, int], names: list[str]) -> list[int]:
    missing = [n for n in names if n not in label_index]
    if missing:
        raise ValueError(f"label(s) not in segmentation: {missing}")
    return [label_index[n] for n in names]


def _presence_by_slice(labels: np.ndarray) -> np.ndarray:
    """Boolean ``[nz, 256]``: which label ids occur in each slice."""
    present = np.zeros((labels.shape[0], 256), dtype=bool)
    for k in range(labels.shape[0]):
        present[k] = np.bincount(labels[k].ravel(), minlength=256)[:256] > 0
    return present


def _extent_mm(present: np.ndarray, ids: list[int], z_body_mm: np.ndarray, dz: float, what: str) -> tuple[float, float]:
    """Outer top and bottom edges (mm from the vertex) of the slices containing any of ``ids``."""
    ks = np.flatnonzero(present[:, ids].any(axis=1))
    if ks.size == 0:
        raise ValueError(f"no voxels of {what} in the volume")
    return float(z_body_mm[ks[0]] - dz / 2.0), float(z_body_mm[ks[-1]] + dz / 2.0)


def _pubic_symphysis_mm(
    labels: np.ndarray, hip_ids: list[int], z_body_mm: np.ndarray, spacing_mm: tuple[float, float, float]
) -> float:
    """Bottom edge of the lowest slice where both hip bones come within 15 mm of the midline."""
    dz, _, dx = spacing_mm
    nx = labels.shape[2]
    columns = np.arange(nx)
    marginals = np.zeros((2, labels.shape[0], nx), dtype=np.int64)
    for n, hip in enumerate(hip_ids):
        marginals[n] = (labels == hip).sum(axis=1)
    centroids = [(m.sum(axis=0) * columns).sum() / m.sum() for m in marginals]
    midline_col = float(np.mean(centroids))
    near = np.abs(columns - midline_col) * dx <= MIDLINE_WINDOW_MM
    both = (marginals[:, :, near] > 0).any(axis=2).all(axis=0)
    ks = np.flatnonzero(both)
    if ks.size == 0:
        raise ValueError("hip bones never come within 15 mm of the midline")
    return float(z_body_mm[ks[-1]] + dz / 2.0)


def compute_landmarks(
    labels: np.ndarray,
    label_index: dict[str, int],
    z_body_mm: np.ndarray,
    spacing_mm: tuple[float, float, float],
) -> dict[str, float]:
    """Landmark positions in ``z_body_mm`` (vertex = 0, positive toward the feet).

    ``z_body_mm`` holds the slice centres; positions are re-referenced to the top edge of the
    first slice containing ``skull``, so ``vertex`` is exactly 0.
    """
    dz = spacing_mm[0]
    present = _presence_by_slice(labels)

    def extent(names: list[str]) -> tuple[float, float]:
        return _extent_mm(present, _label_ids(label_index, names), z_body_mm, dz, "/".join(names))

    skull_top, _ = extent(["skull"])
    notch, xiphoid = extent(["sternum"])
    lung_names = sorted(n for n in label_index if n.startswith("lung_"))
    apex, base = extent(lung_names)
    liver_top, liver_bottom = extent(["liver"])
    kidney_top, kidney_bottom = extent(["kidney_left", "kidney_right"])
    hip_tops = sorted(extent([h])[0] for h in ("hip_left", "hip_right"))
    femur_top, _ = extent(["femur_left", "femur_right"])
    symphysis = _pubic_symphysis_mm(labels, _label_ids(label_index, ["hip_left", "hip_right"]), z_body_mm, spacing_mm)
    raw = {
        "vertex": skull_top, "sternal_notch": notch, "xiphoid": xiphoid, "lung_apex": apex, "lung_base": base,
        "liver_top": liver_top, "liver_bottom": liver_bottom, "kidney_top": kidney_top,
        "kidney_bottom": kidney_bottom, "iliac_crest_high": hip_tops[0], "iliac_crest": hip_tops[1],
        "femoral_head": femur_top + FEMORAL_HEAD_BELOW_TOP_MM,
        "lesser_trochanter": femur_top + LESSER_TROCHANTER_BELOW_TOP_MM,
        "pubic_symphysis": symphysis,
        "data_top": float(z_body_mm[0] - dz / 2.0), "data_bottom": float(z_body_mm[-1] + dz / 2.0),
    }
    return {name: float(value - skull_top) for name, value in raw.items()}


def body_mask(hu_slice: np.ndarray) -> np.ndarray:
    """Largest connected component of tissue (> -300 HU) with holes filled; empty if no tissue."""
    tissue = hu_slice > BODY_THRESHOLD_HU
    components, count = ndimage.label(tissue, structure=_STRUCTURE_8)
    if count == 0:
        return tissue
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    return ndimage.binary_fill_holes(components == sizes.argmax())


def _centroid_mm(mask: np.ndarray, dy: float, dx: float) -> tuple[float, float]:
    """(x, y) centroid in mm from the image centre; x toward patient left, y toward the back."""
    rows, cols = np.nonzero(mask)
    ny, nx = mask.shape
    return (float(cols.mean() + 0.5 - nx / 2.0) * dx, float(rows.mean() + 0.5 - ny / 2.0) * dy)


def slice_metrics(
    ct: np.ndarray,
    labels: np.ndarray,
    label_index: dict[str, int],
    spacing_mm: tuple[float, float, float],
) -> dict[str, np.ndarray]:
    """Per-slice body size, centre, water-equivalent diameter and aorta position.

    Slices without tissue and slices without aorta give NaN. ``body_mass_kg`` is the tissue
    mass of each slice (density 1 + HU/1000 g/cm3, floored at 0).
    """
    dz, dy, dx = spacing_mm
    aorta = _label_ids(label_index, ["aorta"])[0]
    nz = ct.shape[0]
    keys = ("ap_mm", "lat_mm", "center_x_mm", "center_y_mm", "dw_mm", "aorta_x_mm", "aorta_y_mm")
    out = {key: np.full(nz, np.nan) for key in keys}
    out["body_mass_kg"] = np.zeros(nz)
    voxel_cm3 = dz * dy * dx / 1000.0
    for k in range(nz):
        hu = np.asarray(ct[k], dtype=np.float32)
        mask = body_mask(hu)
        if mask.any():
            _fill_body_metrics(out, k, hu, mask, dy, dx, voxel_cm3)
        rows, cols = np.nonzero(labels[k] == aorta)
        if rows.size:
            ny, nx = labels[k].shape
            out["aorta_x_mm"][k] = (cols.mean() + 0.5 - nx / 2.0) * dx
            out["aorta_y_mm"][k] = (rows.mean() + 0.5 - ny / 2.0) * dy
    return out


def _fill_body_metrics(out, k, hu, mask, dy, dx, voxel_cm3) -> None:
    rows, cols = np.nonzero(mask)
    out["ap_mm"][k] = (rows.max() - rows.min() + 1) * dy
    out["lat_mm"][k] = (cols.max() - cols.min() + 1) * dx
    out["center_x_mm"][k], out["center_y_mm"][k] = _centroid_mm(mask, dy, dx)
    inside = hu[mask]
    area_mm2 = rows.size * dy * dx
    out["dw_mm"][k] = 2.0 * np.sqrt(max(inside.mean() / 1000.0 + 1.0, 0.0) * area_mm2 / np.pi)
    out["body_mass_kg"][k] = np.maximum(1.0 + inside / 1000.0, 0.0).sum() * voxel_cm3 / 1000.0


def estimate_stature_mm(landmarks: dict[str, float]) -> float:
    """Stature from the femoral head depth (head sits at about 47 % of stature), clipped."""
    raw = landmarks["femoral_head"] / STATURE_FRACTION_AT_FEMORAL_HEAD
    return float(np.clip(raw, *STATURE_LIMITS_MM))


def estimate_weight_kg(body_mass_kg: np.ndarray) -> float:
    """Whole-body weight: mass inside the scan divided by the scanned fraction (0.80)."""
    return float(np.nansum(body_mass_kg) / WEIGHT_MASS_FRACTION)
