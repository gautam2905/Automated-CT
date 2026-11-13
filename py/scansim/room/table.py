"""The patient table: height and travel, with the limits the real table enforces."""
from typing import Generator, Optional

from scansim.core.process import move_linear
from scansim.core.steps import StepError
from scansim.scanner_spec import TableSpec
from scansim.snapshot import TableView

OUT_OF_BORE_MM = 50.0   # travel up to this counts as still outside the bore


class TableLimit(StepError):
    """A table move would pass a limit; the message is shown to the user."""


class Table:
    def __init__(self, spec: TableSpec) -> None:
        self.spec = spec
        self.height_mm: float = spec.height_min_mm
        self.long_mm: float = 0.0
        self.zero_long_mm: Optional[float] = None

    def move_height(self, target_mm: float) -> Generator:
        s = self.spec
        if not s.height_min_mm <= target_mm <= s.height_max_mm:
            raise TableLimit(f"Table height must stay between {s.height_min_mm:.0f} and "
                             f"{s.height_max_mm:.0f} mm; {target_mm:.0f} mm is out of range")
        if self.long_mm > OUT_OF_BORE_MM and target_mm < s.height_min_in_bore_mm:
            raise TableLimit(f"The table cannot go below {s.height_min_in_bore_mm:.0f} mm "
                             "while it is inside the bore; move it out first")
        yield from move_linear(lambda: self.height_mm, self._set_height, target_mm, s.vertical_speed_mm_s)

    def move_long(self, target_mm: float) -> Generator:
        s = self.spec
        if not 0 <= target_mm <= s.long_max_mm:
            raise TableLimit(f"Table travel must stay between 0 and {s.long_max_mm:.0f} mm; "
                             f"{target_mm:.0f} mm is out of range")
        if target_mm > OUT_OF_BORE_MM and self.height_mm < s.height_min_in_bore_mm:
            raise TableLimit(f"Raise the table to at least {s.height_min_in_bore_mm:.0f} mm "
                             "before moving it into the bore")
        yield from move_linear(lambda: self.long_mm, self._set_long, target_mm, s.long_speed_mm_s)

    def set_zero(self) -> None:
        self.zero_long_mm = self.long_mm

    def view(self, position_mm: Optional[float]) -> TableView:
        s = self.spec
        return TableView(height_mm=self.height_mm, long_mm=self.long_mm, long_max_mm=s.long_max_mm,
                         height_min_mm=s.height_min_mm, height_max_mm=s.height_max_mm,
                         zero_long_mm=self.zero_long_mm, position_mm=position_mm)

    def _set_height(self, value: float) -> None:
        self.height_mm = value

    def _set_long(self, value: float) -> None:
        self.long_mm = value
