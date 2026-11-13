import math


class SimClock:
    """Simulation time in seconds. Only the scheduler moves it; nothing reads the wall clock."""

    def __init__(self) -> None:
        self.now_s: float = 0.0

    def advance(self, dt_s: float) -> None:
        if not math.isfinite(dt_s) or dt_s < 0:
            raise ValueError("The clock can only advance by a finite, non-negative time")
        self.now_s += dt_s
