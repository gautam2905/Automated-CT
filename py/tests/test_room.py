from pathlib import Path

import pytest

from scansim.core.clock import SimClock
from scansim.core.process import Scheduler
from scansim.room.placement import Placement
from scansim.room.room import Room
from scansim.room.table import Table, TableLimit
from scansim.scanner_spec import load_scanner

SCANNER = Path(__file__).resolve().parents[2] / "data" / "scanners" / "siemens_somatom_force.json"


@pytest.fixture
def spec():
    return load_scanner(SCANNER)


@pytest.fixture
def run():
    def _run(gen, limit_s=600.0):
        sch = Scheduler(SimClock())
        handle = sch.start(gen, name="test")
        waited = 0.0
        while not handle.done and waited < limit_s:
            sch.advance(0.5)
            waited += 0.5
        assert handle.done, "generator did not finish"
        if handle.error is not None:
            raise handle.error
    return _run


def test_feet_first_puts_feet_nearest_the_gantry():
    p = Placement("feet_first", "supine", "up", anchor_t_mm=120, stature_mm=1720)
    assert p.t_of_body(1720) == 120 and p.t_of_body(0) == 1840
    assert p.room_z_of_body(1720, long_mm=0, front_clearance_mm=550) < p.room_z_of_body(400, 0, 550)


def test_head_first_is_reversed():
    p = Placement("head_first", "supine", "down", anchor_t_mm=550, stature_mm=1720)
    assert p.t_of_body(0) == 550 and p.t_of_body(1720) == 2270


def test_long_for_body_at_inverts_room_z():
    p = Placement("feet_first", "supine", "up", 120, 1720)
    long_mm = p.long_for_body_at(464, room_z_mm=0, front_clearance_mm=550)
    assert p.room_z_of_body(464, long_mm, 550) == pytest.approx(0)


def test_long_for_body_at_inverts_room_z_head_first():
    p = Placement("head_first", "supine", "up", 300, 1720)
    long_mm = p.long_for_body_at(200, room_z_mm=0, front_clearance_mm=550)
    assert p.room_z_of_body(200, long_mm, 550) == pytest.approx(0)


def test_unknown_entry_is_rejected():
    with pytest.raises(ValueError):
        Placement("sideways", "supine", "up", 120, 1720)


def test_table_refuses_to_enter_bore_when_too_low(spec, run):
    t = Table(spec.table); t.height_mm = spec.table.height_min_mm
    with pytest.raises(TableLimit) as e: run(t.move_long(800))
    assert str(int(spec.table.height_min_in_bore_mm)) in str(e.value) and t.long_mm == 0


def test_table_refuses_travel_past_its_limit(spec, run):
    t = Table(spec.table); t.height_mm = spec.table.height_max_mm
    with pytest.raises(TableLimit) as e: run(t.move_long(spec.table.long_max_mm + 1))
    assert str(int(spec.table.long_max_mm)) in str(e.value)


def test_zero(spec, run):
    t = Table(spec.table); t.height_mm = spec.table.height_max_mm
    run(t.move_long(900)); t.set_zero(); assert t.zero_long_mm == 900


def test_table_refuses_to_lower_while_in_bore(spec, run):
    t = Table(spec.table); t.height_mm = spec.table.height_max_mm
    run(t.move_long(900))
    with pytest.raises(TableLimit) as e: run(t.move_height(spec.table.height_min_mm))
    assert str(int(spec.table.height_min_in_bore_mm)) in str(e.value)
    assert t.height_mm == spec.table.height_max_mm


def test_table_refuses_height_outside_limits(spec, run):
    t = Table(spec.table)
    with pytest.raises(TableLimit) as e: run(t.move_height(spec.table.height_max_mm + 1))
    assert str(int(spec.table.height_max_mm)) in str(e.value)
    with pytest.raises(TableLimit) as e: run(t.move_height(spec.table.height_min_mm - 1))
    assert str(int(spec.table.height_min_mm)) in str(e.value)


def test_table_height_moves_and_view_reports_state(spec, run):
    t = Table(spec.table)
    assert t.height_mm == spec.table.height_min_mm and t.long_mm == 0 and t.zero_long_mm is None
    run(t.move_height(800))
    v = t.view(12.5)
    assert v.height_mm == 800 and v.long_mm == 0 and v.position_mm == 12.5
    assert v.long_max_mm == spec.table.long_max_mm and v.height_min_mm == spec.table.height_min_mm
    assert v.height_max_mm == spec.table.height_max_mm and v.zero_long_mm is None


def test_room_defaults_and_view():
    r = Room()
    assert (r.door_open, r.warning_light_on, r.lasers_on, r.technologist_at) == (True, False, False, "reception")
    r.door_open = False; r.technologist_at = "console"
    v = r.view()
    assert v.door_open is False and v.technologist_at == "console" and v.lasers_on is False
