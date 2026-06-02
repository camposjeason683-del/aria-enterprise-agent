# spec: specs/infra/rate-limiting.spec.md
"""TDD for tier resolution (drives rate-limit quotas)."""
from src.infra.insforge import InsForgeResponse
from src.infra.tenants import resolve_tenant_tier


class _Client:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "tenants"
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, n):
        return self

    async def execute(self):
        return InsForgeResponse(self._rows)


async def test_tier_from_tenant():
    assert await resolve_tenant_tier("A", client=_Client([{"subscription_tier": "pro"}])) == "pro"


async def test_tier_defaults_free_when_missing():
    assert await resolve_tenant_tier("A", client=_Client([])) == "free"


async def test_tier_defaults_free_when_null():
    assert await resolve_tenant_tier("A", client=_Client([{"subscription_tier": None}])) == "free"
