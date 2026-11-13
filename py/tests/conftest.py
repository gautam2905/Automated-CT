from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROTOCOL_ID = "ohsu.ct.multiphase_liver"


@pytest.fixture(scope="session")
def DATA():
    return DATA_DIR


@pytest.fixture(scope="session")
def pack():
    path = DATA_DIR / "patients" / "sub-000"
    if not (path / "meta.json").exists():
        pytest.fail(
            f"patient pack {path} is missing: build it first with "
            "PYTHONPATH=/mnt/CT_SCAN/work/python-libs:py $PY tools/build_patient_pack.py --subject sub-000"
        )
    from scansim.patient.pack import PatientPack

    return PatientPack.load(path)


@pytest.fixture
def session(DATA):
    from scansim.session import open_session

    return open_session(DATA, PROTOCOL_ID, "sub-000", seed=1)


@pytest.fixture
def positioned(session):
    from helpers import PRESCAN, do

    for step_id in PRESCAN:
        do(session, step_id)
    return session


@pytest.fixture
def planned_base(positioned):
    from helpers import do

    for step_id in ("topogram_ap", "topogram_lat", "check_centring"):
        do(positioned, step_id)
    return positioned


@pytest.fixture
def tracking_ready(session, pack):
    """Session up to the armed injector, with the region placed off the aorta (it will never trigger)."""
    from helpers import perform_until

    perform_until(session, pack, "arm_injector", roi_on_aorta=False)
    return session
