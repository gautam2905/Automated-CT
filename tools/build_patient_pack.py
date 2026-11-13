#!/usr/bin/env python
"""Build a patient pack from a dataset subject.

    PYTHONPATH=/mnt/CT_SCAN/work/python-libs:py $PY tools/build_patient_pack.py --subject sub-000

Reads the CT, organ labels and topograms (read-only) and writes ``<out>/<subject>/`` with the
volumes re-oriented to ``[k, j, i]`` = head to feet, front to back, patient right to left.

The tool removes and replaces folders, so its arguments are checked before anything is read or written:
the subject is a plain name, the output folder is not inside the dataset, and a folder that already
exists is replaced only if it is a patient pack (``check_arguments``).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from scansim.patient.landmarks import compute_landmarks, estimate_stature_mm, estimate_weight_kg, slice_metrics
from scansim.patient.pack import PACK_VERSION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path("/mnt/CT_SCAN/DATASET")
SUBJECT_NAME = re.compile(r"[A-Za-z0-9_-]+")
# Axis codes name the direction in which each array axis (i, j, k) increases.
PACK_AXCODES = ("L", "P", "I")
NOTES = [
    "Volunteers were scanned with arms down beside the body, so the body mask, lat_mm and the "
    "water-equivalent diameter include the arms at chest and abdomen level.",
    "lesser_trochanter is an approximation: top of the femur labels plus 75 mm.",
    "femoral_head is the top of the femur labels plus 25 mm.",
    "pubic_symphysis is the bottom edge of the lowest slice where both hip bones lie within 15 mm of "
    "the hip-bone midline.",
    "Landmarks are outer slice edges in mm from the vertex (top edge of the first slice containing skull), "
    "positive toward the feet.",
    "weight_kg is the CT tissue mass inside the scan divided by 0.80 (fraction of body mass scanned); "
    "stature_mm is femoral_head / 0.47 clipped to 1450-2050 mm.",
    "Topogram AP columns increase toward the patient's left; LAT columns increase toward the back.",
    "Body mask per slice: CT > -300 HU, largest connected component, holes filled (the table is not removed "
    "if it touches the body).",
]


def find_one(folder: Path, pattern: str) -> Path:
    matches = sorted(folder.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {pattern} in {folder}, found {len(matches)}")
    return matches[0]


def read_label_index(tsv: Path) -> dict[str, int]:
    rows = [line.split("\t") for line in tsv.read_text().splitlines()[1:] if line.strip()]
    return {name.strip(): int(index) for index, name in rows}


def is_pack(folder: Path) -> bool:
    """A folder this tool wrote: it holds a ``meta.json`` with a ``pack_version``."""
    try:
        meta = json.loads((folder / "meta.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(meta, dict) and "pack_version" in meta


def check_arguments(subject: str, dataset: Path, out: Path) -> None:
    """Refuse, before anything is read or written, arguments that could make the tool delete or replace
    something that is not a patient pack."""
    if not SUBJECT_NAME.fullmatch(subject):
        raise SystemExit(f"--subject {subject!r} is not a subject name: use letters, digits, '_' and '-' only")
    out_dir, dataset_dir = out.resolve(), dataset.resolve()
    if out_dir == dataset_dir or dataset_dir in out_dir.parents:
        raise SystemExit(f"--out {out} is inside the dataset {dataset}: the dataset is never written to")
    final = out / subject
    if final.exists() and not is_pack(final):
        raise SystemExit(f"{final} exists and is not a patient pack (no meta.json with a pack_version): "
                         "it is not replaced; remove it yourself or choose another --out")


def reorient(image) -> tuple[np.ndarray, np.ndarray]:
    """Return the data as ``[k, j, i]`` in pack orientation and the affine of the ``[i, j, k]`` grid."""
    from nibabel import orientations        # only this tool needs nibabel, and only once it really builds

    current = orientations.io_orientation(image.affine)
    step = orientations.ornt_transform(current, orientations.axcodes2ornt(PACK_AXCODES))
    data = orientations.apply_orientation(np.asanyarray(image.dataobj), step)
    affine = image.affine @ orientations.inv_ornt_aff(step, image.shape)
    return np.ascontiguousarray(np.transpose(data, (2, 1, 0))), affine


def load_volumes(src: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import nibabel as nib

    ct_img = nib.load(find_one(src, "*LOWDOSE*ct.nii.gz"))
    seg_img = nib.load(find_one(src, "*dseg.nii.gz"))
    ct, affine = reorient(ct_img)
    labels, label_affine = reorient(seg_img)
    if ct.shape != labels.shape or not np.allclose(affine, label_affine, atol=1e-3):
        raise SystemExit("CT and label volumes are not on the same grid")
    if labels.max() > 255 or labels.min() < 0:
        raise SystemExit("label values do not fit uint8")
    return ct.astype(np.int16), labels.astype(np.uint8), affine


def topogram_geometry(geometry_dir: Path, subject: str, view: str, z_top_ras: float) -> dict:
    geo = json.loads((geometry_dir / f"{subject}_{view}.json").read_text())
    row0_ras = geo["center_ras_mm"][2] + geo["pixel_center_index"] * geo["row_spacing_mm"]
    return {"row_mm": geo["row_spacing_mm"], "col_mm": geo["isocenter_column_spacing_mm"],
            "z_body_of_row0": z_top_ras - row0_ras}


def skull_top_ras(labels: np.ndarray, label_index: dict[str, int], affine: np.ndarray, dz: float) -> float:
    """RAS z of the top edge of the first (most superior) slice containing skull."""
    present = (labels == label_index["skull"]).any(axis=(1, 2))
    k = int(np.flatnonzero(present)[0])
    return float(affine[2, 2] * k + affine[2, 3] + dz / 2.0)


def build(subject: str, dataset: Path, out: Path) -> Path:
    check_arguments(subject, dataset, out)
    src = dataset / "source_cache" / "multimodal_hc" / subject
    arrays, geometry = dataset / "short_abdominal_v1" / "arrays", dataset / "short_abdominal_v1" / "geometry"
    label_index = read_label_index(find_one(src, "*dseg.tsv"))
    ct, labels, affine = load_volumes(src)
    spacing = (float(abs(affine[2, 2])), float(abs(affine[1, 1])), float(abs(affine[0, 0])))
    z_top_ras = skull_top_ras(labels, label_index, affine, spacing[0])
    z_first = z_top_ras - float(affine[2, 3])  # centre of slice k=0: z_ras = affine[2, 3]
    z_body = z_first + spacing[0] * np.arange(ct.shape[0])
    landmarks = compute_landmarks(labels, label_index, z_body, spacing)
    metrics = slice_metrics(ct, labels, label_index, spacing)
    estimated = {"stature_mm": estimate_stature_mm(landmarks), "weight_kg": estimate_weight_kg(metrics["body_mass_kg"])}
    meta = {
        "pack_version": PACK_VERSION, "id": subject, "shape_kji": list(ct.shape), "spacing_mm": list(spacing),
        "z_body_first_slice_mm": z_first, "z_vertex_ras_mm": z_top_ras, "label_index": label_index,
        "landmarks": landmarks, "estimated": estimated, "notes": NOTES,
        "data_range_mm": [landmarks["data_top"], landmarks["data_bottom"]],
        "topograms": {"AP": topogram_geometry(geometry, subject, "AP", z_top_ras),
                      "LAT": topogram_geometry(geometry, subject, "LATERAL", z_top_ras)},
    }
    tmp = out / f".{subject}.building"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    np.save(tmp / "ct.npy", ct)
    np.save(tmp / "labels.npy", labels)
    np.savez(tmp / "metrics.npz", **metrics)
    np.save(tmp / "topo_AP.npy", np.load(arrays / f"{subject}_AP.npy").astype(np.float32))
    np.save(tmp / "topo_LAT.npy", np.load(arrays / f"{subject}_LATERAL.npy").astype(np.float32))
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2))
    final = out / subject
    if final.exists():
        if not is_pack(final):          # checked at the start; checked again because the build takes minutes
            raise SystemExit(f"{final} exists and is not a patient pack: it is not replaced (the new pack is "
                             f"left in {tmp})")
        shutil.rmtree(final)
    tmp.rename(final)
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "patients")
    args = parser.parse_args(argv)
    started = time.monotonic()
    final = build(args.subject, args.dataset, args.out)
    sys.stdout.write(f"built {final} in {time.monotonic() - started:.1f} s\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
