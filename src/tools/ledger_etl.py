"""ETL: compile cached WooCommerce orders into the daily inventory ledger.

KEYSTONE of the whole intelligence layer. ``forecast_sales`` / the proactive sweep /
anomaly detection all read ``daily_inventory_ledger`` — but in production that table
was only ever filled by the demo seed. The WooCommerce sync writes orders to
``wc_orders_cache`` and *nothing* compiled them into the ledger (the only compile
path called a Next.js ``/api/sync-stock`` endpoint that does not exist). A real
customer connected a store and the brain stayed starved. This module is that
missing compile step.

Design (mirrors the repo convention — a pure core + a thin I/O wrapper, like
``_fit_forecast`` / ``_evaluate`` / ``_cusum``):
- ``_aggregate`` is a PURE function (no I/O, no RNG, no wall-clock) so the
  order→ledger math is unit-tested in isolation.
- ``compile_ledger_for_tenant`` wraps it with tenant-scoped reads/writes and an
  IDEMPOTENT upsert keyed on ``(tenant_id, date, product_id)`` — re-running over the
  same orders yields the same ledger (migration 0010 adds the UNIQUE constraint).

Product identity: orders reference products by NAME (the WooCommerce line-item id is
an int while the ledger.product_id / products.id columns are TEXT/UUID). We key a
product by its normalised name and derive a DETERMINISTIC uuid5, reusing an existing
``products.id`` when the name already exists so ``ledger.product_id == products.id``
(the sweep joins ``products`` on that id, and skips ledger rows with no product_id).
New names get a ``products`` row so the join resolves.

Stock: orders carry no stock. ``stock_end_of_day`` is preserved from any prior ledger
row and only set fresh from ``stock_map`` (current WooCommerce stock, latest date
only — wired by the per-tenant sync in a follow-up). Unknown stock stays NULL rather
than a misleading 0.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from src.infra.db import get_supabase
from src.infra.tenant_context import current

# WooCommerce order statuses that represent realised demand (counted as sales).
# Excludes cancelled / refunded / failed / pending (unpaid). Tunable in one place.
SOLD_STATUSES = frozenset({"completed", "processing", "on-hold"})

_UPSERT_CHUNK = 400


def _norm(name: str) -> str:
    """Canonical product key: trimmed, lower-cased, internal whitespace collapsed."""
    return " ".join((name or "").strip().lower().split())


def _product_id(tenant_id: str, norm_name: str) -> str:
    """Deterministic, tenant-scoped product UUID derived from the normalised name.

    Same name → same id across runs (idempotency) and across tenants stays distinct
    (the tenant_id is in the seed string)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"aria-prod::{tenant_id}::{norm_name}"))


def _num(v: Any) -> Optional[float]:
    """Best-effort numeric coercion; None on non-numeric / NaN / inf (data-quality guard)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _aggregate(
    orders: list[dict],
    *,
    tenant_id: str,
    existing_by_name: dict[str, str],
    existing_stock: dict[tuple[str, str], Any],
    stock_map: Optional[dict[str, Any]] = None,
    sold_statuses: frozenset[str] = SOLD_STATUSES,
) -> tuple[list[dict], list[dict]]:
    """PURE: cached orders → (ledger_rows, new_products). No I/O.

    ``orders``           : ``[{order_id, date_created, status, line_items}]`` where
                           line_items is ``[{product_name|name, qty|quantity, price}]``.
    ``existing_by_name`` : ``{norm_name: product_id}`` from the products table.
    ``existing_stock``   : ``{(product_id, date): stock}`` to preserve across runs.
    ``stock_map``        : optional ``{norm_name: stock}`` applied to the LATEST date only.

    Returns:
      ledger_rows  : idempotent upsert payloads (one per (product, date)).
      new_products : ``{tenant_id, id, name, price}`` for names not already in products.
    """
    # agg[(norm, date)] = {qty, rev, priced_qty}
    agg: dict[tuple[str, str], dict[str, float]] = {}
    name_display: dict[str, str] = {}

    for o in orders:
        if (o.get("status") or "").strip().lower() not in sold_statuses:
            continue
        dc = o.get("date_created")
        if not dc or not isinstance(dc, str) or len(dc) < 10:
            continue
        date = dc[:10]  # YYYY-MM-DD
        items = o.get("line_items")
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_name = it.get("product_name") or it.get("name")
            if not raw_name or not str(raw_name).strip():
                continue
            norm = _norm(str(raw_name))
            qty = _num(it.get("qty") if it.get("qty") is not None else it.get("quantity"))
            if qty is None or qty <= 0:
                continue
            price = _num(it.get("price"))  # per-unit; may be absent
            cell = agg.get((norm, date))
            if cell is None:
                cell = {"qty": 0.0, "rev": 0.0, "priced_qty": 0.0}
                agg[(norm, date)] = cell
            cell["qty"] += qty
            if price is not None and price >= 0:
                cell["rev"] += qty * price
                cell["priced_qty"] += qty
            name_display.setdefault(norm, str(raw_name).strip())

    # Resolve a stable product_id per name (reuse existing, else deterministic mint).
    norm_to_id: dict[str, str] = dict(existing_by_name)
    for (norm, _date) in agg:
        if norm not in norm_to_id:
            norm_to_id[norm] = _product_id(tenant_id, norm)

    latest_date = max((d for (_, d) in agg), default=None)

    ledger_rows: list[dict] = []
    for (norm, date), cell in agg.items():
        pid = norm_to_id[norm]
        price = round(cell["rev"] / cell["priced_qty"], 4) if cell["priced_qty"] > 0 else None
        if stock_map is not None and date == latest_date and norm in stock_map:
            stock = stock_map[norm]
        else:
            stock = existing_stock.get((pid, date))  # preserve; None if unknown
        ledger_rows.append({
            "tenant_id": tenant_id,
            "date": date,
            "product_id": pid,
            "product_name": name_display[norm],
            "sales_velocity": round(cell["qty"], 4),
            "price": price,
            "stock_end_of_day": stock,
            "production_detected": 0,
        })

    # New products (names not previously in the catalog) → a row so the sweep's
    # `products.in_("id", ledger_product_ids)` join resolves. Price = latest seen.
    price_by_norm: dict[str, float] = {}
    for (norm, _date), cell in sorted(agg.items(), key=lambda kv: kv[0][1]):
        if cell["priced_qty"] > 0:
            price_by_norm[norm] = round(cell["rev"] / cell["priced_qty"], 4)
    new_products: list[dict] = [
        {"tenant_id": tenant_id, "id": norm_to_id[norm], "name": name_display[norm],
         "price": price_by_norm.get(norm)}
        for norm in name_display
        if norm not in existing_by_name
    ]

    return ledger_rows, new_products


async def compile_ledger_for_tenant(
    *, since: Optional[str] = None, stock_map: Optional[dict[str, Any]] = None
) -> dict:
    """Compile the current tenant's cached orders into ``daily_inventory_ledger``.

    Runs under whatever tenant context is in scope: the headless cron client
    (admin key pinned to tenant_id) or an interactive RLS client — both constrain
    reads to the tenant and accept writes carrying an explicit ``tenant_id``.
    Idempotent: safe to re-run (upsert on (tenant_id, date, product_id))."""
    ctx = current()
    if ctx is None:
        raise RuntimeError("compile_ledger_for_tenant requires a tenant context in scope")
    tid = ctx.tenant_id
    client = await get_supabase()

    oq = client.table("wc_orders_cache").select("order_id, date_created, status, line_items")
    if since:
        oq = oq.gte("date_created", since)
    orders = (await oq.execute()).data or []
    if not orders:
        return {"status": "empty", "tenant_id": tid, "orders": 0, "rows": 0, "products_added": 0}

    prods = (await client.table("products").select("id, name").execute()).data or []
    existing_by_name = {
        _norm(p["name"]): str(p["id"]) for p in prods if p.get("name") and p.get("id")
    }

    lq = client.table("daily_inventory_ledger").select("product_id, date, stock_end_of_day")
    if since:
        lq = lq.gte("date", since[:10])
    existing_stock = {
        (str(r["product_id"]), r["date"]): r.get("stock_end_of_day")
        for r in ((await lq.execute()).data or [])
        if r.get("product_id") and r.get("date")
    }

    ledger_rows, new_products = _aggregate(
        orders,
        tenant_id=tid,
        existing_by_name=existing_by_name,
        existing_stock=existing_stock,
        stock_map=stock_map,
    )

    if new_products:
        await client.table("products").insert(new_products).execute()

    for i in range(0, len(ledger_rows), _UPSERT_CHUNK):
        await client.table("daily_inventory_ledger").upsert(
            ledger_rows[i:i + _UPSERT_CHUNK], on_conflict="tenant_id,date,product_id"
        ).execute()

    return {
        "status": "success",
        "tenant_id": tid,
        "orders": len(orders),
        "rows": len(ledger_rows),
        "products_added": len(new_products),
        "dates": sorted({r["date"] for r in ledger_rows}),
    }
