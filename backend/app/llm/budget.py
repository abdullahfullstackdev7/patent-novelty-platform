"""Local rate-limit accounting: per-minute token bucket and a circuit breaker.

Both take an injectable clock so tests never sleep. They are thread-safe because the API and
worker threads share one gateway per process.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]
WINDOW_SECONDS = 60.0
HEADER_FRESH_SECONDS = 10.0


def estimate_tokens(text: str) -> int:
    """Tokenizer-free estimate: one token per four characters, rounded up."""
    return math.ceil(len(text) / 4)


class TokenBucket:
    """Sliding one-minute window of requests and tokens for one provider.

    `remaining_tokens` and `reset_seconds` from response headers (x-ratelimit-remaining-tokens)
    correct the local estimate: the stricter of the two wins while the header is fresh.
    """

    def __init__(
        self,
        tokens_per_minute: int | None,
        requests_per_minute: int | None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.tpm = tokens_per_minute
        self.rpm = requests_per_minute
        self._clock = clock
        self._events: deque[tuple[float, int]] = deque()  # (time, tokens)
        self._header: tuple[float, int, float] | None = None  # (time, remaining, reset seconds)
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= WINDOW_SECONDS:
            self._events.popleft()

    def used_tokens(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return sum(tokens for _, tokens in self._events)

    def used_requests(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return len(self._events)

    def record(self, tokens: int) -> None:
        """Count a finished request."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._events.append((now, max(tokens, 0)))

    def update_from_headers(self, remaining: int | None, reset_seconds: float | None) -> None:
        if remaining is None:
            return
        with self._lock:
            self._header = (self._clock(), remaining, reset_seconds or WINDOW_SECONDS)

    def wait_needed(self, estimated_tokens: int) -> float:
        """Seconds to wait before a request of this size fits. 0 means it fits now.

        math.inf means it can never fit (larger than a whole minute of budget).
        """
        with self._lock:
            now = self._clock()
            self._prune(now)
            waits = [0.0]

            if self.tpm is not None:
                if estimated_tokens > self.tpm:
                    return math.inf
                used = sum(tokens for _, tokens in self._events)
                if used + estimated_tokens > self.tpm:
                    waits.append(
                        self._time_until_tokens_free(now, used + estimated_tokens - self.tpm)
                    )

            if self.rpm is not None and len(self._events) >= self.rpm:
                excess = len(self._events) - self.rpm + 1
                waits.append(WINDOW_SECONDS - (now - self._events[excess - 1][0]))

            if self._header is not None:
                seen, remaining, reset = self._header
                age = now - seen
                if age < HEADER_FRESH_SECONDS and remaining < estimated_tokens:
                    waits.append(max(reset - age, 0.0))
            return max(waits)

    def _time_until_tokens_free(self, now: float, needed: int) -> float:
        freed = 0
        for stamp, tokens in self._events:
            freed += tokens
            if freed >= needed:
                return max(WINDOW_SECONDS - (now - stamp), 0.0)
        return WINDOW_SECONDS


@dataclass(frozen=True)
class BreakerState:
    state: str  # closed | open | half_open
    failures: int
    retry_in: float | None  # seconds until a trial call is allowed, only while open


class CircuitBreaker:
    """Opens after `threshold` consecutive failures and rejects calls for `open_seconds`.

    After that one trial call is allowed (half open). Success closes the breaker, failure
    reopens it for another full period.
    """

    def __init__(
        self, threshold: int = 3, open_seconds: float = 60.0, clock: Clock = time.monotonic
    ):
        self.threshold = threshold
        self.open_seconds = open_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.open_seconds:
                return False
            if self._trial_in_flight:
                return False
            self._trial_in_flight = True  # half open: exactly one trial call
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._trial_in_flight or self._failures >= self.threshold:
                self._opened_at = self._clock()
            self._trial_in_flight = False

    def release(self) -> None:
        """End a half-open trial that was neither a success nor a breaker-worthy failure."""
        with self._lock:
            self._trial_in_flight = False

    def reset(self) -> None:
        self.record_success()

    def snapshot(self) -> BreakerState:
        with self._lock:
            if self._opened_at is None:
                return BreakerState("closed", self._failures, None)
            remaining = self.open_seconds - (self._clock() - self._opened_at)
            if remaining > 0:
                return BreakerState("open", self._failures, remaining)
            return BreakerState("half_open", self._failures, None)
