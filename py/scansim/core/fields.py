import math
from typing import Any, Optional

from scansim.snapshot import FieldView, OptionView

MAX_TEXT_LEN = 200
_TYPES = ("number", "choice", "bool", "text")


class FieldError(ValueError):
    """A proposed field value was rejected; the message names the field and its limits."""


def _fmt(x: float) -> str:
    return f"{x:g}"


class Field:
    def __init__(self, key: str, label: str, type: str, default: Any, *, source: str, unit: str = "",
                 min: Optional[float] = None, max: Optional[float] = None, step: Optional[float] = None,
                 options=(), help: str = "") -> None:
        if type not in _TYPES:
            raise ValueError(f"Unknown field type {type!r}")
        self.key, self.label, self.type, self.default = key, label, type, default
        self.source, self.unit, self.min, self.max, self.step, self.help = source, unit, min, max, step, help
        self.options: tuple[tuple[str, str], ...] = tuple((str(v), str(lbl)) for v, lbl in options)
        self.value = default

    def set(self, raw: Any) -> None:
        """Validate `raw` and store it; on rejection the stored value is unchanged."""
        parse = {"number": self._parse_number, "choice": self._parse_choice,
                 "bool": self._parse_bool, "text": self._parse_text}[self.type]
        self.value = parse(raw)

    def view(self, editable: bool = True) -> FieldView:
        return FieldView(
            key=self.key, label=self.label, type=self.type, value=self.value, default=self.default,
            unit=self.unit, min=self.min, max=self.max, step=self.step,
            options=[OptionView(value=v, label=lbl) for v, lbl in self.options],
            source=self.source, help=self.help, editable=editable)

    def _limits_text(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        if self.min is not None and self.max is not None:
            return f"between {_fmt(self.min)} and {_fmt(self.max)}{unit}"
        if self.min is not None:
            return f"at least {_fmt(self.min)}{unit}"
        if self.max is not None:
            return f"at most {_fmt(self.max)}{unit}"
        return "a finite number"

    def _parse_number(self, raw: Any) -> float:
        bad = FieldError(f"{self.label} must be a number {self._limits_text()}")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise bad
        try:
            number = float(raw.strip()) if isinstance(raw, str) else float(raw)
        except ValueError:
            raise bad from None
        if not math.isfinite(number):
            raise bad
        if (self.min is not None and number < self.min) or (self.max is not None and number > self.max):
            raise FieldError(f"{self.label} must be {self._limits_text()} (got {_fmt(number)})")
        return number

    def _parse_choice(self, raw: Any) -> str:
        values = [v for v, _ in self.options]
        if not isinstance(raw, str) or raw not in values:
            raise FieldError(f"{self.label} must be one of: {', '.join(values)}")
        return raw

    def _parse_bool(self, raw: Any) -> bool:
        if not isinstance(raw, bool):
            raise FieldError(f"{self.label} must be true or false")
        return raw

    def _parse_text(self, raw: Any) -> str:
        if not isinstance(raw, str):
            raise FieldError(f"{self.label} must be text")
        text = raw.strip()
        if len(text) > MAX_TEXT_LEN:
            raise FieldError(f"{self.label} must be at most {MAX_TEXT_LEN} characters")
        return text
