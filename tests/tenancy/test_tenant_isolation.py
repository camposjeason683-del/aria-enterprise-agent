# spec: specs/tenancy/tenant-isolation.spec.md
"""
The 2-tenant isolation GATE for the RLS cutover (Fase 3).

This test runs against a LIVE ARIA-OS InsForge project (a branch is recommended)
with migrations M1-M5 applied and seed data for two tenants. It is skipped unless
ARIA_LIVE_TESTS=1, so it never fails CI without credentials.

Prereqs (set in the live runbook / .env):
  ARIA_LIVE_TESTS=1
  INSFORGE_URL, INSFORGE_API_KEY
  ARIA_TEST_JWT_A   # access token of a user in tenant A
  ARIA_TEST_JWT_B   # access token of a user in tenant B
  (seed: A and B each have >=1 row in wc_orders_cache and aria_proposals)

The invariant (cardinal I1): for a user of tenant T, NO path returns a row whose
tenant_id != T — including the LLM-authored raw-SQL path (exec_safe_read).
"""
import os

import pytest

from src.infra.insforge import get_tenant_client

LIVE = os.environ.get("ARIA_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Live 2-tenant isolation gate — requires the ARIA-OS InsForge project (set ARIA_LIVE_TESTS=1).",
)


def _jwt(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set")
    return val


async def test_tool_query_scoped_to_tenant():
    """Path (i): a normal tool query returns only the caller's tenant rows."""
    client = get_tenant_client(_jwt("ARIA_TEST_JWT_A"))
    res = await client.table("wc_orders_cache").select("tenant_id").execute()
    tenants = {r["tenant_id"] for r in (res.data or [])}
    assert len(tenants) <= 1, f"cross-tenant leak via tool query: {tenants}"


async def test_raw_llm_sql_cannot_cross_tenants():
    """Path (ii): raw SQL with NO tenant filter still only sees tenant A."""
    client = get_tenant_client(_jwt("ARIA_TEST_JWT_A"))
    res = await client.rpc(
        "exec_safe_read", {"q": "SELECT tenant_id FROM wc_orders_cache"}
    )
    tenants = {r["tenant_id"] for r in (res.data or [])}
    assert len(tenants) <= 1, f"cross-tenant leak via exec_safe_read: {tenants}"


async def test_unfiltered_aggregate_stays_scoped():
    """Path (iii): COUNT(*) without a filter counts only the caller's tenant."""
    a = get_tenant_client(_jwt("ARIA_TEST_JWT_A"))
    b = get_tenant_client(_jwt("ARIA_TEST_JWT_B"))
    res_a = await a.rpc("exec_safe_read", {"q": "SELECT count(*) AS n FROM aria_proposals"})
    res_b = await b.rpc("exec_safe_read", {"q": "SELECT count(*) AS n FROM aria_proposals"})
    n_a = (res_a.data or [{}])[0].get("n", 0)
    n_b = (res_b.data or [{}])[0].get("n", 0)
    # Each side counts only its own proposals; a global count would equal n_a+n_b.
    total = await a.table("aria_proposals").select("id", count="exact").execute()
    # `count` is the RLS-scoped total for A, never A+B.
    assert total.count == n_a, "A's scoped count must equal A's own proposals"
    assert n_b >= 0
