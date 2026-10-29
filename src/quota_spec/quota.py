"""Aligned fixed windows. Completion and cancellation never refund quota."""

import math
from dataclasses import dataclass, field

from .models import nonnegative, positive_int


@dataclass
class FixedWindowQuota:
    capacity: int
    window_s: float
    window_index: int = 0
    used: int = 0
    _last_time: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.capacity, bool)
            or not isinstance(self.capacity, int)
            or self.capacity < 1
        ):
            raise ValueError("capacity must be a positive integer")
        nonnegative(self.window_s, "window_s")
        if self.window_s <= 0:
            raise ValueError("window_s must be finite and positive")
        positive_int(self.window_index, "window_index", 0)
        positive_int(self.used, "used", 0)
        if self.used > self.capacity:
            raise ValueError("used cannot exceed capacity")
        self._last_time = self.window_index * self.window_s

    def _advance(self, now_s: float) -> None:
        nonnegative(now_s, "time")
        if now_s < self._last_time:
            raise ValueError("quota clock cannot move backwards")
        self._last_time = now_s
        index = math.floor(now_s / self.window_s)
        # Float division can round a computed boundary down (e.g. 4.3 / .1).
        # Compare to the boundaries themselves so refill wakes cannot reschedule
        # forever at the same timestamp. Preserve values just below a boundary.
        if now_s < index * self.window_s:
            index -= 1
        elif now_s >= (index + 1) * self.window_s:
            index += 1
        if index < self.window_index:
            raise ValueError("quota clock cannot move backwards")
        if index > self.window_index:
            self.window_index, self.used = index, 0

    def remaining(self, now_s: float) -> int:
        self._advance(now_s)
        return self.capacity - self.used

    def consume(self, now_s: float) -> bool:
        if not self.remaining(now_s):
            return False
        self.used += 1
        return True

    def next_refill(self, now_s: float) -> float:
        self._advance(now_s)
        return (self.window_index + 1) * self.window_s
