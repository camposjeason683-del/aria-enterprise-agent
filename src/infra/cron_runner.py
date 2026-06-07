"""Headless per-tenant execution for the cron loops.

A scheduled job has no user JWT; ``run_for_tenant`` seeds a HEADLESS TenantContext
so ``get_supabase()`` returns the tenant-scoped admin client (RLS bypassed but every
table pinned to this tenant_id), runs the coroutine, and clears the context in a
``finally`` so it never leaks into the next tenant of the loop.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from src.infra.tenant_context import TenantContext, clear_current, set_current


async def run_for_tenant(
    tenant_id: str, coro_factory: Callable[[], Awaitable[Any]]
) -> Any:
    """Run ``coro_factory()`` under a headless context scoped to ``tenant_id``."""
    set_current(
        TenantContext(
            user_id="system_cron",
            tenant_id=tenant_id,
            role="admin",
            jwt="",
            headless=True,
        )
    )
    try:
        return await coro_factory()
    finally:
        clear_current()
