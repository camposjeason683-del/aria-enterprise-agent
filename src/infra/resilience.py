"""Circuit breaker (M9): fast-fail an external dependency (WooCommerce / Stripe / Gemini)
after repeated failures so an outage degrades gracefully instead of hanging every request.

The state machine is PURE — ``now`` is injected (no wall-clock) so it's deterministic and
unit-testable. closed → (fail_max failures) → open → (after reset_after) → half_open →
(success) → closed, or (failure) → open again."""
from __future__ import annotations

from typing import Optional


class CircuitBreaker:
    def __init__(self, *, fail_max: int = 5, reset_after: float = 30.0):
        self.fail_max = fail_max
        self.reset_after = reset_after
        self.state = "closed"
        self._fails = 0
        self._opened_at: Optional[float] = None

    def allow(self, now: float) -> bool:
        """May a call proceed at time ``now``? Transitions open→half_open when cooled down."""
        if self.state == "open":
            if self._opened_at is not None and now - self._opened_at >= self.reset_after:
                self.state = "half_open"
                return True
            return False
        return True  # closed or half_open

    def record_success(self) -> None:
        self.state = "closed"
        self._fails = 0
        self._opened_at = None

    def record_failure(self, now: float) -> None:
        self._fails += 1
        if self.state == "half_open" or self._fails >= self.fail_max:
            self.state = "open"
            self._opened_at = now
