"""The pack build tool removes and replaces folders, so its arguments are checked before it touches anything."""
import importlib.util
import json
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "build_patient_pack.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("build_patient_pack", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)              # must not need nibabel just to check its arguments
    return module


@pytest.fixture
def folders(tmp_path):
    dataset, out = tmp_path / "dataset", tmp_path / "out"
    (dataset / "source_cache" / "multimodal_hc" / "sub-006").mkdir(parents=True)
    out.mkdir()
    return dataset, out


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.mark.parametrize("subject", ["../x", "sub-006/..", "/etc", "..", "sub 006", "", "sub.006", "a\\b"])
def test_a_subject_that_is_not_a_plain_name_is_refused_and_nothing_is_touched(tool, folders, tmp_path, subject):
    dataset, out = folders
    victim = tmp_path / "x"; victim.mkdir(); (victim / "keep.txt").write_text("keep")
    before = _files(tmp_path)
    with pytest.raises(SystemExit, match="is not a subject name"):     # not "subject": the test folder's name has it
        tool.main(["--subject", subject, "--dataset", str(dataset), "--out", str(out)])
    assert _files(tmp_path) == before and (victim / "keep.txt").read_text() == "keep"


def test_an_out_folder_inside_the_dataset_is_refused(tool, folders):
    dataset, _ = folders
    source = dataset / "source_cache" / "multimodal_hc"
    (source / "sub-006" / "scan.nii.gz").write_text("source data")
    for out in (source, dataset, dataset / "new" / "folder"):
        with pytest.raises(SystemExit, match="inside the dataset"):
            tool.main(["--subject", "sub-006", "--dataset", str(dataset), "--out", str(out)])
    assert (source / "sub-006" / "scan.nii.gz").read_text() == "source data"
    assert not (dataset / "new").exists()


def test_an_existing_folder_that_is_not_a_pack_is_not_replaced(tool, folders):
    dataset, out = folders
    other = out / "sub-006"; other.mkdir(); (other / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit, match="not a patient pack"):
        tool.main(["--subject", "sub-006", "--dataset", str(dataset), "--out", str(out)])
    assert (other / "notes.txt").read_text() == "mine"
    (other / "meta.json").write_text("not json")
    with pytest.raises(SystemExit, match="not a patient pack"):
        tool.check_arguments("sub-006", dataset, out)
    (other / "meta.json").write_text(json.dumps({"id": "sub-006"}))        # no pack_version
    assert not tool.is_pack(other)


def test_a_plain_subject_a_separate_out_folder_and_an_existing_pack_are_accepted(tool, folders):
    dataset, out = folders
    tool.check_arguments("sub-006", dataset, out)                          # nothing there yet
    pack = out / "sub-006"; pack.mkdir(); (pack / "meta.json").write_text(json.dumps({"pack_version": 1}))
    assert tool.is_pack(pack)
    tool.check_arguments("sub-006", dataset, out)                          # an old pack may be replaced


def test_the_built_packs_are_packs(tool):
    patients = TOOL.parents[1] / "data" / "patients"
    assert all(tool.is_pack(p) for p in patients.iterdir() if p.is_dir())
