"""Field kinds the scan steps need: a numeric pick-list and ranges whose edits are copied to their peers."""
import math
from typing import Any, Optional

from scansim.core.fields import Field
from scansim.protocols.schema import CTProtocol
from scansim.scanner_spec import CTScannerSpec

RANGE_LIMIT_MM = 1500.0     # wide on purpose: a bad range is refused by the step, with the reason


def source_for(protocol: CTProtocol, path: str) -> str:
    """`assumption` when the protocol file lists the value among its assumptions, else `protocol`."""
    return "assumption" if path in protocol.assumptions else "protocol"


def scanner_source(spec: CTScannerSpec, path: str) -> str:
    """`assumption` when the scanner file lists the value among its assumptions, else `scanner`."""
    return "assumption" if path in spec.assumptions else "scanner"


def _label(value: float, unit: str) -> str:
    return f"{value:g} {unit}".strip()


class NumericChoiceField(Field):
    """A pick-list of numbers. The client sends the option text; the stored value is a number."""

    def __init__(self, key: str, label: str, default: float, options, *, source: str, unit: str = "",
                 help: str = "") -> None:
        numbers = [float(v) for v in options]
        if float(default) not in numbers:
            raise ValueError(f"{key}: default {default:g} is not among the options {numbers}")
        super().__init__(key, label, "choice", float(default), source=source, unit=unit, help=help,
                         options=[(f"{v:g}", _label(v, unit)) for v in numbers])

    def set(self, raw: Any) -> None:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw):
            raw = f"{raw:g}"
        self.value = float(self._parse_choice(raw))


class LinkedRangeField(Field):
    """A range edge. While the group's link field is on, an edit is copied to the same edge of every series.

    `group` holds the real fields. The session checks a value on a copy of the field first; a copy is not
    in the group, so checking never touches the other fields.
    """

    def __init__(self, key: str, label: str, edge: str, default: float, *, source: str,
                 group: dict[str, Field], link_key: str, help: str = "") -> None:
        super().__init__(key, label, "number", float(default), source=source, unit="mm", step=1.0,
                         min=-RANGE_LIMIT_MM, max=RANGE_LIMIT_MM, help=help)
        self.edge, self.group, self.link_key = edge, group, link_key

    def set(self, raw: Any) -> None:
        super().set(raw)
        if self.group.get(self.key) is not self or not self.group[self.link_key].value:
            return
        for peer in self.group.values():
            if isinstance(peer, LinkedRangeField) and peer.edge == self.edge:
                peer.value = self.value


def number_field(key: str, label: str, value: float, source: str, *, unit: str = "", lo: Optional[float] = None,
                 hi: Optional[float] = None, step: float = 1.0, help: str = "") -> Field:
    return Field(key, label, "number", value, source=source, unit=unit, min=lo, max=hi, step=step, help=help)
