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


# A clock that keeps counting while the laptop sleeps, so a timer spanning a sleep stays on the
# wall clock (macOS CLOCK_MONOTONIC and Linux CLOCK_BOOTTIME do; time.monotonic() may not).
_MONOTONIC_ID = getattr(time, "CLOCK_BOOTTIME", None) or getattr(time, "CLOCK_MONOTONIC", None)


class SystemClock:
    def monotonic_ms(self) -> int:
        if _MONOTONIC_ID is None:
            return time.monotonic_ns() // 1_000_000
        return time.clock_gettime_ns(_MONOTONIC_ID) // 1_000_000

    def wall_ms(self) -> int:
        return time.time_ns() // 1_000_000
