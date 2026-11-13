"""Patient pack loader: memory-mapped CT and labels, topograms, landmarks and body metrics.

Pack layout (written by ``tools/build_patient_pack.py``): ``ct.npy`` (int16), ``labels.npy``
(uint8), ``topo_AP.npy``, ``topo_LAT.npy``, ``metrics.npz`` and ``meta.json``.
Volume arrays are ``[k, j, i]`` = head to feet, front to back, patient right to patient left.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

PACK_VERSION = 1
METRIC_NAMES = (
    "ap_mm", "lat_mm", "center_x_mm", "center_y_mm", "dw_mm", "aorta_x_mm", "aorta_y_mm", "body_mass_kg",
)


class OutsideAnatomy(ValueError):
    """Requested position lies outside the patient's CT data."""


@dataclass(frozen=True)
class Topogram:
    """A scout image. ``pixels`` is float32 ``[rows, cols]``, rows head to feet."""

    pixels: np.ndarray
    row_mm: float
    col_mm: float
    z_body_of_row0: float


@dataclass(frozen=True)
class SliceMetrics:
    """Per-slice body measurements (NaN where the body or aorta is absent)."""

    ap_mm: np.ndarray
    lat_mm: np.ndarray
    center_x_mm: np.ndarray
    center_y_mm: np.ndarray
    dw_mm: np.ndarray
    aorta_x_mm: np.ndarray
    aorta_y_mm: np.ndarray
    body_mass_kg: np.ndarray


@dataclass(frozen=True)
class PatientPack:
    id: str
    ct: np.ndarray
    labels: np.ndarray
    spacing_mm: tuple[float, float, float]
    z_body_mm: np.ndarray
    label_index: dict[str, int]
    landmarks: dict[str, float]
    stature_mm: float
    weight_kg: float
    data_range_mm: tuple[float, float]
    metrics: SliceMetrics
    _topograms: dict[str, Topogram]

    @classmethod
    def load(cls, dir: Path) -> "PatientPack":
        dir = Path(dir)
        meta = json.loads((dir / "meta.json").read_text())
        if meta["pack_version"] != PACK_VERSION:
            raise ValueError(f"{dir}: pack version {meta['pack_version']}, expected {PACK_VERSION}; rebuild it")
        ct = np.load(dir / "ct.npy", mmap_mode="r")
        labels = np.load(dir / "labels.npy", mmap_mode="r")
        dz, dy, dx = (float(v) for v in meta["spacing_mm"])
        z_body = meta["z_body_first_slice_mm"] + dz * np.arange(ct.shape[0])
        with np.load(dir / "metrics.npz") as arrays:
            metrics = SliceMetrics(**{name: arrays[name] for name in METRIC_NAMES})
        topograms = {view: _load_topogram(dir, view, meta["topograms"][view]) for view in ("AP", "LAT")}
        return cls(
            id=meta["id"], ct=ct, labels=labels, spacing_mm=(dz, dy, dx), z_body_mm=z_body,
            label_index={name: int(v) for name, v in meta["label_index"].items()},
            landmarks={name: float(v) for name, v in meta["landmarks"].items()},
            stature_mm=float(meta["estimated"]["stature_mm"]), weight_kg=float(meta["estimated"]["weight_kg"]),
            data_range_mm=(float(meta["data_range_mm"][0]), float(meta["data_range_mm"][1])),
            metrics=metrics, _topograms=topograms,
        )

    def slice_index(self, z_body_mm: float) -> int:
        """Nearest slice to ``z_body_mm``; refuses positions beyond the data by over half a slice."""
        dz = self.spacing_mm[0]
        top, bottom = self.data_range_mm
        if not top - dz / 2.0 <= z_body_mm <= bottom + dz / 2.0:
            raise OutsideAnatomy(
                f"z {z_body_mm:.1f} mm is outside the patient's CT data ({top:.1f} to {bottom:.1f} mm from the vertex)"
            )
        k = int(round((z_body_mm - self.z_body_mm[0]) / dz))
        return min(max(k, 0), self.ct.shape[0] - 1)

    def topogram(self, view: Literal["AP", "LAT"]) -> Topogram:
        if view not in self._topograms:
            raise ValueError(f"unknown topogram view {view!r}; expected 'AP' or 'LAT'")
        return self._topograms[view]


def _load_topogram(dir: Path, view: str, geometry: dict) -> Topogram:
    pixels = np.load(dir / f"topo_{view}.npy", mmap_mode="r")
    return Topogram(
        pixels=pixels, row_mm=float(geometry["row_mm"]), col_mm=float(geometry["col_mm"]),
        z_body_of_row0=float(geometry["z_body_of_row0"]),
    )
