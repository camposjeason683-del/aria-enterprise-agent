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

import os
import time

import httpx

from src.infra.insforge import InsForgeClient, close_http, get_admin_client, get_tenant_client
from src.infra.tenant_context import current as _current_ctx
from src.infra.tenant_context import current_jwt

# Demo-tenant fallback for the CopilotKit / sandbox path. That path auto-signs-in
# as the demo tenant, but its JWT does not reach the tools via the request
# contextvar (ag_ui_adk mounts the endpoint outside the app middleware), so the
# data layer falls back to a cached demo session there. The proper /api/v1/chat
# path always has a tenant context and never hits this fallback.
_DEMO_EMAIL = "demo@aria.os"
_DEMO_PW = "AriaDemo2026!"
_demo_cache: dict = {"jwt": None, "exp": 0.0}


async def _demo_jwt() -> str:
    now = time.time()
    if _demo_cache["jwt"] and _demo_cache["exp"] > now + 30:
        return _demo_cache["jwt"]
    url = os.environ["INSFORGE_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as http:
        r = await http.post(
            f"{url}/api/auth/sessions?client_type=server",
            json={"email": _DEMO_EMAIL, "password": _DEMO_PW},
        )
    r.raise_for_status()
    token = r.json()["accessToken"]
    _demo_cache["jwt"] = token
    _demo_cache["exp"] = now + 800
    return token


async def get_supabase() -> InsForgeClient:
    """Tenant-scoped InsForge client (RLS via the user's JWT).

    Compatibility name for the tools: the fluent API matches the old client, so
    `client = await get_supabase()` + `client.table(...)...execute()` is unchanged.
    Falls back to the demo tenant only when there's no tenant context in scope
    (the CopilotKit/sandbox path); the chat path always has one.
    """
    if _current_ctx() is not None:
        return get_tenant_client(current_jwt())
    return get_tenant_client(await _demo_jwt())


def get_system_client() -> InsForgeClient:
    """Admin InsForge client for non-tenant system tables. Bypasses RLS."""
    return get_admin_client()


async def close_supabase() -> None:
    """Close the shared InsForge HTTP client during server shutdown."""
    await close_http()
