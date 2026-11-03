"""Time sources. The backend owns all event timestamps (monotonic); the wall clock only places
a Session in real time, so its timer survives a backend restart. Tests inject a fake clock."""

import time
from typing import Protocol


class Clock(Protocol):
    def monotonic_ms(self) -> int:
        """Milliseconds from an arbitrary fixed origin; never goes backwards."""
        ...

    def wall_ms(self) -> int:
        """Milliseconds since the Unix epoch."""
        ...


class SystemClock:
    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def wall_ms(self) -> int:
        return time.time_ns() // 1_000_000
