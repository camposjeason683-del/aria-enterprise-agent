"""WooCommerce write-back: apply an APPROVED price / liquidation decision to the store.

Closes the half of the action loop that used to no-op. Reads the tenant's encrypted WC
creds (``load_tenant_integration``), resolves the product by name (we key products by
name, not the WC id), and PUTs the new ``regular_price`` / ``sale_price``. Naturally
idempotent — setting a price to X twice yields the same store state. Degrades to a
``skipped`` result when the tenant has no WooCommerce integration (e.g. a CSV-only
tenant), so the proposal still completes without a store to write to.
"""
from __future__ import annotations

from typing import Optional

import httpx

from src.tools.integrations import load_tenant_integration


def _price_payload(new_price) -> dict:
    return {"regular_price": str(new_price)}


def _sale_payload(sale_price) -> dict:
    return {"sale_price": str(sale_price)}


async def _find_product_id(http, creds: dict, name: str) -> Optional[int]:
    """Resolve a WooCommerce product id by name (exact match preferred, else first hit)."""
    base = creds["woo_url"].rstrip("/")
    r = await http.get(f"{base}/wp-json/wc/v3/products",
                       auth=(creds["woo_consumer_key"], creds["woo_consumer_secret"]),
                       params={"search": name, "per_page": 10})
    r.raise_for_status()
    data = r.json() or []
    target = name.strip().lower()
    for p in data:
        if (p.get("name") or "").strip().lower() == target:
            return p.get("id")
    return data[0].get("id") if data else None


async def _apply(tenant_id: str, product_name: str, payload: dict, field: str, value) -> dict:
    creds = await load_tenant_integration(tenant_id)
    if not creds or not creds.get("woo_url"):
        return {"status": "skipped", "reason": "sin integración WooCommerce", "product": product_name}
    base = creds["woo_url"].rstrip("/")
    auth = (creds["woo_consumer_key"], creds["woo_consumer_secret"])
    async with httpx.AsyncClient(timeout=30.0) as http:
        pid = await _find_product_id(http, creds, product_name)
        if not pid:
            return {"status": "not_found", "product": product_name}
        r = await http.put(f"{base}/wp-json/wc/v3/products/{pid}", auth=auth, json=payload)
        r.raise_for_status()
    return {"status": "applied", "product": product_name, "product_id": pid, field: value}


async def woo_update_price(tenant_id: str, product_name: str, new_price) -> dict:
    """Set the product's regular price in WooCommerce."""
    return await _apply(tenant_id, product_name, _price_payload(new_price), "new_price", new_price)


async def woo_set_sale(tenant_id: str, product_name: str, sale_price) -> dict:
    """Put the product on sale at ``sale_price`` (liquidation)."""
    return await _apply(tenant_id, product_name, _sale_payload(sale_price), "sale_price", sale_price)
