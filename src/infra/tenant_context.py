"""
ARIA-OS: per-request tenant context (contextvars).

A request authenticates once (see auth.require_tenant); the resolved identity is
stashed in a ContextVar so the data layer and tools can scope every query to the
tenant WITHOUT threading tenant_id through ~50 tool signatures — and crucially
WITHOUT exposing tenant_id as an LLM-visible tool parameter (which would be a
security hole).

# spec: specs/auth/tenant-auth.spec.md
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TenantContext:
    user_id: str
    tenant_id: str
    role: str  # "admin" | "employee"
    # The user's InsForge access token, used to build RLS-scoped data clients.
    # repr=False so it never lands in logs/tracebacks (I2 of insforge-adapter).
    jwt: str = field(repr=False)
    # Headless cron path: no user JWT; the data layer uses the admin client pinned
    # to tenant_id (RLS bypassed but every table explicitly scoped). Default False
    # keeps the normal request path unchanged.
    headless: bool = False


_current: ContextVar[TenantContext | None] = ContextVar(
    "aria_tenant_context", default=None
)


def set_current(ctx: TenantContext) -> None:
    _current.set(ctx)


def current() -> TenantContext | None:
    return _current.get()


def clear_current() -> None:
    """Reset the contextvar — used between tenants in the headless cron loop so one
    tenant's context never leaks into the next iteration."""
    _current.set(None)


def current_jwt() -> str:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError(
            "No tenant context in scope — require_tenant must run before any "
            "tenant-scoped data access."
        )
    return ctx.jwt
