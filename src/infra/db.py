"""
ARIA-OS: data-layer entrypoint (InsForge).

This module keeps the historical name `get_supabase()` that the ~50 tool
functions already call, but it now returns a **tenant-scoped InsForge client**
(RLS enforced via the request's user JWT). Because the InsForge adapter
(src/infra/insforge.py) mimics the supabase-py fluent API
(`.table().select().eq()...execute() -> .data`), those tools keep working
unchanged — the migration is isolated here.

- get_supabase()       → TENANT client (business data; RLS). Requires a tenant
                         context in scope (set by auth.require_tenant).
- get_system_client()  → ADMIN client (system tables: system_config,
                         aria_usage_log, agent_sessions). Bypasses RLS — never
                         use for tenant business data.

Rollback: the previous Supabase singleton lives in git history; revert this file
to restore it.
"""
from __future__ import annotations

from src.infra.insforge import InsForgeClient, close_http, get_admin_client, get_tenant_client
from src.infra.tenant_context import current_jwt


async def get_supabase() -> InsForgeClient:
    """Tenant-scoped InsForge client (RLS via the user's JWT).

    Compatibility name for the tools: the fluent API matches the old client, so
    `client = await get_supabase()` + `client.table(...)...execute()` is unchanged.
    Raises if called outside a tenant request context (no implicit global access).
    """
    return get_tenant_client(current_jwt())


def get_system_client() -> InsForgeClient:
    """Admin InsForge client for non-tenant system tables. Bypasses RLS."""
    return get_admin_client()


async def close_supabase() -> None:
    """Close the shared InsForge HTTP client during server shutdown."""
    await close_http()
