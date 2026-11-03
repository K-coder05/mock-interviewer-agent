"""Monotonic time source. The backend owns all event timestamps; tests inject a fake clock."""

import time
from typing import Protocol


class Clock(Protocol):
    def monotonic_ms(self) -> int:
        """Milliseconds from an arbitrary fixed origin; never goes backwards."""
        ...


class SystemClock:
    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000
