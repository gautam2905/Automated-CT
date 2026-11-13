from collections import deque

from scansim.core.clock import SimClock
from scansim.snapshot import LogEntry

MAX_ENTRIES = 2000


class EventLog:
    """Time-stamped log of what happened, stamped with simulation time."""

    def __init__(self, clock: SimClock) -> None:
        self._clock = clock
        self._entries: deque[LogEntry] = deque(maxlen=MAX_ENTRIES)

    def add(self, kind: str, text: str) -> None:
        self._entries.append(LogEntry(t_s=self._clock.now_s, kind=kind, text=text))

    def tail(self, n: int = 50) -> list[LogEntry]:
        if n <= 0:
            return []
        return list(self._entries)[-n:]
