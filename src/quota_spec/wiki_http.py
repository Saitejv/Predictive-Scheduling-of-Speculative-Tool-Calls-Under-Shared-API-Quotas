"""Identified, paced Wikipedia client; retries honor shared server backoff."""

import math
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime

USER_AGENT = (
    "quota-spec-research-bot/0.1 "
    "(https://github.com/Saitejv/Predictive-Scheduling-of-Speculative-Tool-Calls-Under-Shared-API-Quotas)"
)


class WikiHTTP:
    def __init__(self, get, *, interval_s=0, retries=2, clock=None, sleep=None):
        if not math.isfinite(interval_s) or interval_s < 0:
            raise ValueError("Wikipedia interval must be finite and nonnegative")
        self.get_impl, self.interval_s, self.retries = get, interval_s, retries
        self.clock, self.sleep = clock or time.perf_counter, sleep or time.sleep
        self.lock, self.local = threading.Lock(), threading.local()
        self.next_submit = self.cooldown = 0.0

    def begin(self):
        self.local.pacing_s = self.local.backoff_s = 0.0
        self.local.mutex_s = self.local.network_s = 0.0
        self.local.attempts = 0

    def get(self, *args, **kwargs):
        kwargs.setdefault("timeout", 30)
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("User-Agent", USER_AGENT)
        kwargs["headers"] = headers
        for attempt in range(self.retries + 1):
            queued_at = self.clock()
            with self.lock:
                now = self.clock()
                mutex_wait = now - queued_at
                self.local.mutex_s = getattr(self.local, "mutex_s", 0) + mutex_wait
                delay = max(0.0, self.next_submit - now, self.cooldown - now)
                backoff = min(delay, max(0.0, self.cooldown - now))
                if delay:
                    self.sleep(delay)
                self.local.pacing_s = (
                    getattr(self.local, "pacing_s", 0) + mutex_wait + delay - backoff
                )
                self.local.backoff_s = getattr(self.local, "backoff_s", 0) + backoff
                self.next_submit = self.clock() + self.interval_s
            self.local.attempts = getattr(self.local, "attempts", 0) + 1
            network_started = self.clock()
            try:
                response = self.get_impl(*args, **kwargs)
            finally:
                self.local.network_s = (
                    getattr(self.local, "network_s", 0) + self.clock() - network_started
                )
            if response.status_code not in (429, 503) or attempt == self.retries:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                try:
                    stamp = parsedate_to_datetime(retry_after)
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    delay = stamp.timestamp() - time.time()
                except (TypeError, ValueError, AttributeError):
                    delay = 5 * 2**attempt
            if not math.isfinite(delay) or delay < 0:
                delay = 5 * 2**attempt
            with self.lock:
                self.cooldown = max(self.cooldown, self.clock() + delay)
            # Do not occupy the caller indefinitely on a long server rejection.
            # Future requests retain the shared cooldown and cannot dispatch early.
            if delay > 60:
                response.raise_for_status()
        raise AssertionError("Unreachable retry state")
