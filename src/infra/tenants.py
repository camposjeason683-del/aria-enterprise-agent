"""
ARIA-OS: tenant metadata lookups.

resolve_tenant_tier reads the subscription tier (free/pro/enterprise) that drives
rate-limit quotas. Uses the system client (a non-tenant lookup). Defaults to the
strictest tier ("free") if the tenant is missing or has no tier set.

# spec: specs/infra/rate-limiting.spec.md
"""
from __future__ import annotations

from typing import Any


async def resolve_tenant_tier(tenant_id: str, *, client: Any = None) -> str:
    if client is None:
        from src.infra.db import get_system_client

        client = get_system_client()
    res = (
        await client.table("tenants")
        .select("subscription_tier")
        .eq("id", tenant_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0].get("subscription_tier") or "free"
    return "free"
