"""Where a patient lies on the table, and the arithmetic from body point to room position."""
from dataclasses import dataclass

ENTRIES = ("feet_first", "head_first")


@dataclass
class Placement:
    entry: str
    orientation: str
    arms: str
    anchor_t_mm: float
    stature_mm: float
    lateral_offset_mm: float = 0.0
    yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        if self.entry not in ENTRIES:
            raise ValueError(f"Unknown entry {self.entry!r}; expected one of {', '.join(ENTRIES)}")

    def t_of_body(self, z_body_mm: float) -> float:
        """Position along the tabletop, from its gantry-side end, of a body point."""
        if self.entry == "feet_first":
            return self.anchor_t_mm + (self.stature_mm - z_body_mm)
        return self.anchor_t_mm + z_body_mm

    def room_z_of_body(self, z_body_mm: float, long_mm: float, front_clearance_mm: float) -> float:
        return front_clearance_mm + self.t_of_body(z_body_mm) - long_mm

    def long_for_body_at(self, z_body_mm: float, room_z_mm: float, front_clearance_mm: float) -> float:
        """Table travel that puts the body point at `room_z_mm`."""
        return front_clearance_mm + self.t_of_body(z_body_mm) - room_z_mm
