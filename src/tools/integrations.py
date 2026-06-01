"""
ARIA-OS: per-tenant integration credentials (WooCommerce), encrypted at rest.

- save_tenant_integration: writes via the TENANT client by default, so RLS
  (ti_write → is_tenant_admin) enforces that only an admin can store creds (I2);
  the API endpoint also checks role == "admin" (defense in depth).
- load_tenant_integration: reads via the SYSTEM (admin) client by default,
  because the cron sync runs with no user JWT and must fetch a given tenant's
  creds to sync its store (I3). Returns decrypted values.

Credentials are encrypted with src.infra.crypto before insert and never logged.
# spec: specs/integrations/tenant-woocommerce.spec.md
"""
from __future__ import annotations

from typing import Any, Optional

from src.infra.crypto import decrypt, encrypt


async def save_tenant_integration(
    tenant_id: str,
    woo_url: str,
    consumer_key: str,
    consumer_secret: str,
    *,
    client: Any = None,
) -> dict:
    if client is None:
        from src.infra.db import get_supabase

        client = await get_supabase()  # tenant-scoped → RLS enforces admin-only
    row = {
        "tenant_id": tenant_id,
        "woo_url": woo_url,
        "woo_consumer_key": encrypt(consumer_key),
        "woo_consumer_secret": encrypt(consumer_secret),
    }
    await client.table("tenant_integrations").upsert(row, on_conflict="tenant_id").execute()
    return {"status": "ok", "tenant_id": tenant_id}


async def load_tenant_integration(
    tenant_id: str, *, client: Any = None
) -> Optional[dict]:
    if client is None:
        from src.infra.db import get_system_client

        client = get_system_client()  # cron has no user JWT → admin read
    res = (
        await client.table("tenant_integrations")
        .select("*")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    return {
        "woo_url": row.get("woo_url"),
        "woo_consumer_key": decrypt(row.get("woo_consumer_key")),
        "woo_consumer_secret": decrypt(row.get("woo_consumer_secret")),
    }
