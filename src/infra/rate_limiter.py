"""
ARIA-OS: In-Memory Rate Limiter
Sliding window rate limiter per user_id.
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    max_requests: int = 30
    window_seconds: int = 60
    _store: dict = field(default_factory=lambda: defaultdict(list))

    def is_allowed(self, user_id: str) -> bool:
        """Check if user_id is within rate limit."""
        now = time.time()
        window_start = now - self.window_seconds

        # Purge old entries
        self._store[user_id] = [
            t for t in self._store[user_id] if t > window_start
        ]

        if len(self._store[user_id]) >= self.max_requests:
            return False

        self._store[user_id].append(now)
        return True

    def remaining(self, user_id: str) -> int:
        """How many requests remain in the current window."""
        now = time.time()
        window_start = now - self.window_seconds
        active = [t for t in self._store[user_id] if t > window_start]
        return max(0, self.max_requests - len(active))


rate_limiter = RateLimiter()
