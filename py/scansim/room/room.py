"""Simple state of the scan room."""
from dataclasses import dataclass

from scansim.snapshot import RoomView


@dataclass
class Room:
    door_open: bool = True
    warning_light_on: bool = False
    lasers_on: bool = False
    technologist_at: str = "reception"   # reception | preparation | gantry | console

    def view(self) -> RoomView:
        return RoomView(door_open=self.door_open, warning_light_on=self.warning_light_on,
                        lasers_on=self.lasers_on, technologist_at=self.technologist_at)
