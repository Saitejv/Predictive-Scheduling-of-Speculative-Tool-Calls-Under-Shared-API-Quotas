"""Baseline admission policies; required calls always retain FIFO priority."""

from typing import Protocol

from .models import Observation


class Policy(Protocol):
    def admit(self, state: Observation) -> bool: ...


class NoSpeculation:
    def admit(self, state: Observation) -> bool:
        return False


class FixedReserve:
    def __init__(self, reserve: int = 1):
        if isinstance(reserve, bool) or not isinstance(reserve, int) or reserve < 0:
            raise ValueError("reserve must be a nonnegative integer")
        self.reserve = reserve

    def admit(self, state: Observation) -> bool:
        return state.queued_required == 0 and state.quota_remaining > self.reserve


class CurrentCapacity(FixedReserve):
    """Lightweight current-capacity baseline, not a reproduction of PASTE."""

    def __init__(self):
        super().__init__(reserve=0)


class UsageForecastReserve:
    """Reserve observed required-call rate times time remaining in this window."""

    def __init__(self, minimum=0):
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
            raise ValueError("minimum must be a nonnegative integer")
        self.minimum = minimum
        self.last_decision = {}

    def admit(self, state):
        import math

        from .quota import FixedWindowQuota

        if state.snapshot is None:
            return False
        window = state.snapshot.window_s
        history = state.snapshot.recent_required_s
        lookback = min(window, max(state.now_s, 1e-9))
        rate = sum(t >= state.now_s - window for t in history) / lookback
        remaining_s = (
            FixedWindowQuota(state.snapshot.capacity, window).next_refill(state.now_s) - state.now_s
        )
        reserve = max(self.minimum, math.ceil(rate * remaining_s))
        self.last_decision = {"forecast_reserve": reserve}
        return state.queued_required == 0 and state.quota_remaining > reserve
