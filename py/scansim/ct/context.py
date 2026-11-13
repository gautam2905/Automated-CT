"""The shared state every CT step reads and changes, plus the small helpers steps use."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from scansim.core.clock import SimClock
from scansim.core.events import EventLog
from scansim.core.fields import Field, FieldError
from scansim.core.process import Scheduler
from scansim.core.steps import StepError
from scansim.devices.injector import Injector
from scansim.patient.breathing import Breathing
from scansim.patient.contrast_pk import ContrastModel
from scansim.patient.pack import PatientPack
from scansim.patient.record import PatientRecord
from scansim.protocols.schema import CTProtocol
from scansim.room.placement import Placement
from scansim.room.room import Room
from scansim.room.table import Table
from scansim.scanner_spec import CTScannerSpec
from scansim.snapshot import FieldView

if TYPE_CHECKING:
    from scansim.ct.console import ConsoleState


class ReadOnlyField(Field):
    """A field the user can see but not change (a value fixed by the protocol or computed)."""

    def set(self, raw: Any) -> None:
        raise FieldError(f"{self.label} cannot be edited")

    def view(self, editable: bool = True) -> FieldView:
        return super().view(editable=False)


@dataclass
class CTContext:
    clock: SimClock
    scheduler: Scheduler
    log: EventLog
    room: Room
    table: Table
    placement: Optional[Placement]
    pack: PatientPack
    record: PatientRecord
    breathing: Breathing
    injector: Injector
    contrast: ContrastModel
    spec: CTScannerSpec
    protocol: CTProtocol
    console: "ConsoleState"
    rng: np.random.Generator
    tube_angle_deg: float = 0.0
    rotor_rps: float = 0.0
    beam_on: bool = False
    kv: int = 120
    ma: float = 0.0
    pose_stage: str = "away"
    iv_connected: bool = False
    busy_text: Optional[str] = None
    landmark_z_body_mm: Optional[float] = None
    show_reference: bool = False
    auto_next: Optional[str] = None          # step the session performs by itself once nothing is running
    manual_start_requested: bool = False     # set by the `manual_start` action while bolus monitoring runs
    # How the patient is to lie. Set from the protocol, changed at registration; `placement` takes over
    # these values once the patient is on the table.
    entry: str = field(init=False)
    orientation: str = field(init=False)
    arms: str = field(init=False)

    def __post_init__(self) -> None:
        pos = self.protocol.positioning
        self.entry, self.orientation, self.arms = pos.entry, pos.orientation, pos.arms

    def anchor_t_mm(self) -> float:
        """Where the body end nearest the gantry lies on the tabletop, for the chosen entry."""
        table = self.spec.table
        return table.feet_first_anchor_mm if self.entry == "feet_first" else table.head_first_anchor_mm

    # ---- planning coordinates ----

    def body_z(self, from_landmark_mm: float) -> float:
        """Distance from the vertex of the point `from_landmark_mm` from the landmark set at the laser."""
        if self.landmark_z_body_mm is None:
            raise StepError("Set the landmark first: positions are measured from it")
        return self.landmark_z_body_mm + from_landmark_mm

    def long_for(self, from_landmark_mm: float, room_z_mm: float = 0.0) -> float:
        """Table travel that puts that planning position at `room_z_mm` (0 is the scan plane)."""
        if self.placement is None:
            raise StepError("The patient is not on the table yet")
        return self.placement.long_for_body_at(
            self.body_z(from_landmark_mm), room_z_mm, self.spec.front_clearance_mm)

    def scan_plane_from_landmark_mm(self) -> Optional[float]:
        """Planning coordinate of the body point in the scan plane; None until zero and landmark are set."""
        if self.placement is None or self.landmark_z_body_mm is None or self.table.zero_long_mm is None:
            return None
        t = self.table.long_mm - self.spec.front_clearance_mm      # tabletop position at room z = 0
        p = self.placement
        z_body = p.anchor_t_mm + p.stature_mm - t if p.entry == "feet_first" else t - p.anchor_t_mm
        return z_body - self.landmark_z_body_mm

    # ---- time and voice ----

    def say(self, text: str) -> None:
        self.log.add("voice", text)
        self.busy_text = text

    def jump(self, seconds: float) -> None:
        """Paperwork time: the clock moves forward at once and no process is stepped."""
        self.clock.advance(seconds)
