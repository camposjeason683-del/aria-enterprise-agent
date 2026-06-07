"""
ARIA-OS: WooCommerce Sync Worker (Non-LLM)
Department: Inventory & Operations

Pulls the tenant's WooCommerce orders into ``wc_orders_cache``, reads current product
stock, then compiles the daily ledger via ``compile_ledger_for_tenant`` (the M1
keystone). Purely deterministic, no LLM. Degrades to cached history if the live sync
fails — never crashes the parent flow.

M1b fixes the prior cache-write bug (wrote ``id`` into the UUID PK instead of
``order_id``, set a non-existent ``currency`` column, and omitted ``tenant_id``) and
removes the dead call to a Next.js ``/api/sync-stock`` endpoint that never existed.
"""
import os
from typing import AsyncGenerator

import httpx
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from src.infra.db import get_supabase
from src.infra.logger import log_error, log_info
from src.infra.tenant_context import current
from src.tools.ledger_common import latest_ledger_date
from src.tools.ledger_etl import _norm, compile_ledger_for_tenant


def _order_to_cache_row(o: dict, tenant_id: str) -> dict:
    """Map a WooCommerce order → a ``wc_orders_cache`` row. Pure / unit-tested.

    Writes ``order_id`` (BIGINT) — not ``id`` (the UUID PK) — sets ``tenant_id``, and
    omits the non-existent ``currency`` column (the three bugs that kept the cache
    from populating against the real schema)."""
    billing = o.get("billing") or {}
    name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
    return {
        "tenant_id": tenant_id,
        "order_id": o.get("id"),
        "status": o.get("status"),
        "total": o.get("total"),
        "customer_name": name or None,
        "date_created": o.get("date_created"),
        "line_items": o.get("line_items") or [],
    }


def _wc_products_to_stock_map(products: list) -> dict:
    """Build ``{normalised_name: stock_quantity}`` from WooCommerce products. Pure.

    Only products that actually manage stock (``stock_quantity`` not None) are
    included so the ETL leaves the rest unknown (NULL) rather than a misleading 0.
    Keys use the SAME normalisation as the ETL so they line up with ledger names."""
    out: dict[str, float] = {}
    for p in products or []:
        if not isinstance(p, dict):
            continue
        name, sq = p.get("name"), p.get("stock_quantity")
        if name and sq is not None:
            try:
                out[_norm(str(name))] = float(sq)
            except (TypeError, ValueError):
                continue
    return out


async def _fetch_wc(http, base, key, secret, path, params=None):
    r = await http.get(f"{base}{path}", auth=(key, secret), params=params or {})
    r.raise_for_status()
    return r.json()


class SyncWorker(BaseAgent):
    """Deterministic WooCommerce → cache → ledger sync with a cached-history fallback."""

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        client = await get_supabase()
        cctx = current()
        tenant_id = cctx.tenant_id if cctx else None

        yield Event(author=self.name, content=types.Content(parts=[
            types.Part(text="🔄 Sincronizando órdenes y stock de WooCommerce...")]))

        wc_url = os.environ.get("WOOCOMMERCE_API_URL")
        wc_key = os.environ.get("WOOCOMMERCE_API_KEY")
        wc_secret = os.environ.get("WOOCOMMERCE_API_SECRET")
        sync_ok, err = False, ""

        if not tenant_id:
            err = "Sin contexto de tenant — no se puede sincronizar."
        elif not all([wc_url, wc_key, wc_secret]):
            err = "Faltan credenciales WooCommerce (WOOCOMMERCE_API_*) en el entorno."
        else:
            base = wc_url.rstrip("/")
            try:
                async with httpx.AsyncClient(timeout=45.0) as http:
                    all_orders, page, max_pages = [], 1, 20
                    while page <= max_pages:
                        orders = await _fetch_wc(http, base, wc_key, wc_secret,
                            "/wp-json/wc/v3/orders",
                            {"per_page": 100, "page": page, "orderby": "date", "order": "desc"})
                        if not orders:
                            break
                        all_orders.extend(orders)
                        if len(orders) < 100:
                            break
                        page += 1
                    stock_map = {}
                    try:  # stock is best-effort — orders sync + ledger still proceed if it fails
                        prods = await _fetch_wc(http, base, wc_key, wc_secret,
                            "/wp-json/wc/v3/products", {"per_page": 100})
                        stock_map = _wc_products_to_stock_map(prods)
                    except Exception as e:  # noqa: BLE001
                        log_info(f"WC products fetch failed (stock best-effort): {e!r}", agent="sync_worker")

                if all_orders:
                    rows = [_order_to_cache_row(o, tenant_id) for o in all_orders]
                    await client.table("wc_orders_cache").upsert(
                        rows, on_conflict="tenant_id,order_id").execute()
                result = await compile_ledger_for_tenant(stock_map=stock_map or None)
                sync_ok = True
                msg = (f"✅ Sync OK: {len(all_orders)} órdenes → ledger "
                       f"({result.get('rows', 0)} filas, {result.get('products_added', 0)} productos nuevos).")
                log_info(msg, agent="sync_worker")
                yield Event(author=self.name, content=types.Content(parts=[types.Part(text=msg)]))
            except Exception as e:  # noqa: BLE001
                err = f"Falló el sync en vivo: {e!r}"
                log_error(err, agent="sync_worker")

        if not sync_ok:  # degrade gracefully — never crash the parent flow
            latest = None
            try:
                latest = await latest_ledger_date(client)
            except Exception as e:  # noqa: BLE001
                err += f" | error leyendo histórico: {e!r}"
            if latest:
                yield Event(author=self.name, content=types.Content(parts=[types.Part(text=(
                    f"⚠️ Sin sync fresco ({err}). Continúo con los últimos datos "
                    f"disponibles (fecha {latest})."))]))
            else:
                msg = f"❌ Sin datos frescos ni histórico disponible. {err}"
                log_error(msg, agent="sync_worker")
                yield Event(author=self.name, content=types.Content(parts=[types.Part(text=msg)]))
                raise RuntimeError(msg)
