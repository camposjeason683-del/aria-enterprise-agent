"""
ARIA-OS: Rate Limiting

- RateLimiter: legacy in-memory sliding window per user_id (single-instance only;
  superseded by the tenant-aware, DB-backed limiter below for the SaaS path).
- check_rate_limit: tenant-aware daily quota by subscription tier, backed by the
  shared `rate_limit_counters` table so the count is consistent across instances.

# spec: specs/infra/rate-limiting.spec.md
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


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


# ─── Tenant-aware DB-backed limiter (SaaS) ──────────────────────────────────
# Daily request quota per subscription tier. None = unlimited.
TIER_DAILY_QUOTA: dict[str, Optional[int]] = {
    "free": 20,
    "pro": None,
    "enterprise": None,
}


def quota_for_tier(tier: str) -> Optional[int]:
    """Daily quota for a tier; unknown tiers fall back to the strictest (free)."""
    return TIER_DAILY_QUOTA.get((tier or "free").lower(), TIER_DAILY_QUOTA["free"])


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: Optional[int]  # None = unlimited


def _utc_day_key(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


async def check_rate_limit(
    tenant_id: str,
    user_id: str,
    tier: str,
    *,
    client: Any = None,
    day_key: Optional[str] = None,
) -> RateLimitResult:
    """Consume one request from the (tenant, user) daily quota.

    Reads today's counter, denies if at/over quota, otherwise increments and
    allows. ``client``/``day_key`` are injectable for tests. NOTE: the
    read-then-write is not atomic; at this scale the race is negligible, but a
    SECURITY DEFINER RPC (migration M4) can make it atomic if needed.
    """
    quota = quota_for_tier(tier)
    if quota is None:
        return RateLimitResult(allowed=True, remaining=None)  # unlimited tier

    if client is None:
        from src.infra.insforge import get_admin_client

        client = get_admin_client()
    window = day_key or _utc_day_key()

    res = (
        await client.table("rate_limit_counters")
        .select("count")
        .eq("tenant_id", tenant_id)
        .eq("user_id", user_id)
        .eq("window_key", window)
        .limit(1)
        .execute()
    )
    current = res.data[0]["count"] if res.data else 0

    if current >= quota:
        return RateLimitResult(allowed=False, remaining=0)

    await (
        client.table("rate_limit_counters")
        .upsert(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "window_key": window,
                "count": current + 1,
            },
            on_conflict="tenant_id,user_id,window_key",
        )
        .execute()
    )
    return RateLimitResult(allowed=True, remaining=quota - (current + 1))
