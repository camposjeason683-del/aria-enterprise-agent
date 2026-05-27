"""
ARIA-OS: Multi-Level Authentication
Level 1: API Key  (X-API-Key header)  — external integrations
Level 2: JWT      (Authorization: Bearer) — dashboard
Level 3: Webhook  (X-Webhook-Signature)   — automated systems
"""
import hashlib
import hmac
import os

from fastapi import HTTPException, Request


# ─── Level 1: API Key ───────────────────────────────────────────────
async def verify_api_key(request: Request) -> str:
    """Validate an API key passed in the X-API-Key header."""
    key = request.headers.get("X-API-Key", "")
    if not key:
        raise HTTPException(401, "API Key required in X-API-Key header")

    from src.infra.db import get_supabase

    client = await get_supabase()
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
