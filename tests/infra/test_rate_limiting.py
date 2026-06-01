# spec: specs/infra/rate-limiting.spec.md
"""TDD for tenant-aware rate limiting (S5). A fake client emulates the shared
rate_limit_counters table; day_key is injected for determinism."""
import pytest

from src.infra.insforge import InsForgeResponse
from src.infra.rate_limiter import check_rate_limit, quota_for_tier


class _CounterStore:
    """Emulates rate_limit_counters shared across instances."""

    def __init__(self):
        self.counts: dict[tuple, int] = {}


class _Query:
    def __init__(self, store):
        self._store = store
        self._op = None
        self._row = None
        self._filters: dict = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def upsert(self, row, on_conflict=None):
        self._op, self._row = "upsert", row
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, n):
        return self

    async def execute(self):
        key = (
            self._filters.get("tenant_id"),
            self._filters.get("user_id"),
            self._filters.get("window_key"),
        )
        if self._op == "select":
            if key in self._store.counts:
                return InsForgeResponse([{"count": self._store.counts[key]}])
            return InsForgeResponse([])
        if self._op == "upsert":
            k = (self._row["tenant_id"], self._row["user_id"], self._row["window_key"])
            self._store.counts[k] = self._row["count"]
            return InsForgeResponse([self._row])
        return InsForgeResponse([])


class _FakeClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        assert name == "rate_limit_counters"
        return _Query(self._store)


def test_quota_mapping():
    assert quota_for_tier("free") == 20
    assert quota_for_tier("pro") is None
    assert quota_for_tier("enterprise") is None
    assert quota_for_tier("nonsense") == 20  # unknown => strictest


async def test_free_tier_blocks_at_quota():
    store = _CounterStore()
    store.counts[("A", "u1", "2026-06-01")] = 20  # already at cap
    res = await check_rate_limit(
        "A", "u1", "free", client=_FakeClient(store), day_key="2026-06-01"
    )
    assert res.allowed is False
    assert res.remaining == 0


async def test_under_quota_consumes_and_reports_remaining():
    store = _CounterStore()
    store.counts[("A", "u1", "2026-06-01")] = 5
    res = await check_rate_limit(
        "A", "u1", "free", client=_FakeClient(store), day_key="2026-06-01"
    )
    assert res.allowed is True
    assert res.remaining == 14
    assert store.counts[("A", "u1", "2026-06-01")] == 6  # consumed one


async def test_first_request_of_day():
    store = _CounterStore()
    res = await check_rate_limit(
        "A", "u1", "free", client=_FakeClient(store), day_key="2026-06-01"
    )
    assert res.allowed is True
    assert res.remaining == 19
    assert store.counts[("A", "u1", "2026-06-01")] == 1


async def test_pro_tier_unlimited_and_untouched():
    store = _CounterStore()
    res = await check_rate_limit(
        "B", "u9", "pro", client=_FakeClient(store), day_key="2026-06-01"
    )
    assert res.allowed is True
    assert res.remaining is None
    assert store.counts == {}  # unlimited tier never touches the counter


async def test_shared_counter_blocks_across_instances():
    # Persisted state (== written by instance 1) blocks instance 2.
    store = _CounterStore()
    store.counts[("A", "u1", "2026-06-01")] = 20
    res = await check_rate_limit(
        "A", "u1", "free", client=_FakeClient(store), day_key="2026-06-01"
    )
    assert res.allowed is False
