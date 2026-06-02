"""
ARIA-OS: Multi-Level Authentication
Level 1: API Key  (X-API-Key header)  — external integrations
Level 2: JWT      (Authorization: Bearer) — dashboard
Level 3: Webhook  (X-Webhook-Signature)   — automated systems

Tenant auth (InsForge SaaS): verify_insforge_jwt + resolve_tenant_membership +
require_tenant turn a verified InsForge access token into a TenantContext and
seed the per-request contextvar. See specs/auth/tenant-auth.spec.md.
"""
import hashlib
import hmac
import os

from fastapi import HTTPException, Request

from src.infra.tenant_context import TenantContext, set_current


# ─── Level 1: API Key ───────────────────────────────────────────────
async def verify_api_key(request: Request) -> str:
    """Validate an API key passed in the X-API-Key header."""
    key = request.headers.get("X-API-Key", "")
    if not key:
        raise HTTPException(401, "API Key required in X-API-Key header")

    # Legacy API-key path: a SYSTEM lookup (no tenant context), so use the admin
    # client. The primary SaaS path is JWT via require_tenant.
    from src.infra.db import get_system_client

    client = get_system_client()
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    res = (
        await client.table("api_keys")
        .select("user_id, name, active")
        .eq("key_hash", key_hash)
        .eq("active", True)
        .limit(1)
        .execute()
    )

    if not res.data:
        raise HTTPException(403, "Invalid or deactivated API Key")

    return res.data[0]["user_id"]


# ─── Level 2: JWT ────────────────────────────────────────────────────
async def verify_jwt(request: Request) -> str:
    """Validate a Supabase Auth JWT from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Bearer JWT token required")

    token = auth.removeprefix("Bearer ")
    from jose import JWTError, jwt

    try:
        payload = jwt.decode(
            token,
            os.environ["SUPABASE_JWT_SECRET"],
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload.get("sub", "anonymous")
    except JWTError:
        raise HTTPException(403, "Invalid or expired JWT token")


# ─── Level 3: Webhook Signature ─────────────────────────────────────
async def verify_webhook(request: Request) -> str:
    """Validate HMAC-SHA256 webhook signatures."""
    signature = request.headers.get("X-Webhook-Signature", "")
    body = await request.body()
    secret = os.environ.get("WEBHOOK_SECRET", "")

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403, "Invalid webhook signature")

    return "webhook_system"


# ─── Tenant auth (InsForge SaaS) ────────────────────────────────────
def verify_insforge_jwt(token: str) -> dict:
    """Verify an InsForge access token (HS256, shared JWT_SECRET) and return its
    claims. ``sub`` is the user id (== auth.uid() in RLS). Audience is not
    enforced because InsForge tokens are not minted with a fixed ARIA audience."""
    from jose import JWTError, jwt

    secret = os.environ.get("INSFORGE_JWT_SECRET", "")
    if not secret:
        raise HTTPException(500, "INSFORGE_JWT_SECRET is not configured")
    try:
        return jwt.decode(
            token, secret, algorithms=["HS256"], options={"verify_aud": False}
        )
    except JWTError:
        raise HTTPException(403, "Invalid or expired token")


async def resolve_tenant_membership(user_id: str, admin=None) -> dict:
    """Resolve {tenant_id, role} for a user from tenant_users.

    Uses the admin client (a SYSTEM lookup): we must know the tenant before we
    can build an RLS-scoped client, so this one read runs with the admin key.
    ``admin`` is injectable for tests. Rejects users with no membership — there
    is no implicit "default" tenant (I3)."""
    from src.infra.insforge import get_admin_client

    client = admin or get_admin_client()
    res = (
        await client.table("tenant_users")
        .select("tenant_id, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(403, "User is not a member of any tenant")
    row = res.data[0]
    return {"tenant_id": row["tenant_id"], "role": row.get("role", "employee")}


async def require_tenant(request: Request) -> TenantContext:
    """FastAPI dependency: verify the InsForge JWT, resolve the tenant, seed the
    per-request contextvar, and return the TenantContext. Identity always comes
    from the JWT — never from a client-supplied form field (I2)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Bearer access token required")
    token = auth.removeprefix("Bearer ").strip()

    claims = verify_insforge_jwt(token)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(403, "Token is missing a subject (sub) claim")

    membership = await resolve_tenant_membership(user_id)
    ctx = TenantContext(
        user_id=user_id,
        tenant_id=membership["tenant_id"],
        role=membership["role"],
        jwt=token,
    )
    set_current(ctx)
    return ctx


# ─── Auto-detect authentication method ──────────────────────────────
async def authenticate(request: Request) -> str:
    """Detect and validate auth automatically by inspecting headers."""
    if request.headers.get("X-Webhook-Signature"):
        return await verify_webhook(request)
    elif request.headers.get("X-API-Key"):
        return await verify_api_key(request)
    elif request.headers.get("Authorization"):
        return await verify_jwt(request)
    else:
        raise HTTPException(401, "Authentication required")
