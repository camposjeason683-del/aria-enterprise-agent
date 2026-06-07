"""Purchase-order lifecycle on ``purchase_order_drafts``.

State machine: ``pending_audit → confirmed → dispatched → delivered``. A draft is created
by ``execute_approved_proposal`` at ``pending_audit``; the buyer drives it forward. On
``delivered`` we best-effort bump the product's latest ledger ``stock_end_of_day`` by the
ordered quantity (the goods physically arrived). Idempotent: re-issuing the same
transition is a no-op, an out-of-order one is rejected."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.infra.db import get_supabase
from src.infra.logger import log_error
from src.tools.ledger_etl import _norm

# (current_status, action) → next_status. Pure transition table.
_NEXT = {
    ("pending_audit", "confirm"): "confirmed",
    ("confirmed", "dispatch"): "dispatched",
    ("dispatched", "deliver"): "delivered",
}
_TIMESTAMP = {"confirmed": "confirmed_at", "delivered": "delivered_at"}


def _next_state(current: str, action: str) -> Optional[str]:
    """Pure: the resulting status for (current, action), or None if not allowed."""
    return _NEXT.get((current, action))


def _item_qty(it: dict) -> float:
    for k in ("quantity", "qty", "cantidad"):
        v = it.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _item_name(it: dict):
    return it.get("product_name") or it.get("product") or it.get("name")


async def _bump_stock_on_delivery(client, items: list) -> int:
    """Best-effort: add delivered quantities to each product's latest ledger stock."""
    bumped = 0
    for it in items or []:
        name, qty = _item_name(it), _item_qty(it)
        if not name or qty <= 0:
            continue
        try:
            rows = (await client.table("daily_inventory_ledger")
                    .select("id, stock_end_of_day, product_name, date")
                    .ilike("product_name", name).order("date", desc=True).limit(1).execute()).data or []
            if rows:
                cur = rows[0].get("stock_end_of_day") or 0
                await client.table("daily_inventory_ledger").update(
                    {"stock_end_of_day": float(cur) + qty}).eq("id", rows[0]["id"]).execute()
                bumped += 1
        except Exception as e:  # noqa: BLE001 — non-fatal
            log_error("PO stock bump failed", error=str(e))
    return bumped


async def transition_po(po_id: str, action: str) -> dict:
    """Move a purchase order through its lifecycle. Idempotent / order-checked."""
    client = await get_supabase()
    res = await client.table("purchase_order_drafts").select("*").eq("id", po_id).limit(1).execute()
    if not res.data:
        return {"error": "Orden de compra no encontrada."}
    po = res.data[0]
    cur = po.get("status") or "draft"

    nxt = _next_state(cur, action)
    if nxt is None:
        # Idempotent no-op if it's already past this action; otherwise an invalid order.
        already = {"confirm": "confirmed", "dispatch": "dispatched", "deliver": "delivered"}.get(action)
        if already and cur in ("confirmed", "dispatched", "delivered") and \
                _ORDER.index(cur) >= _ORDER.index(already):
            return {"status": "noop", "idempotent": True, "po_status": cur}
        return {"error": f"Transición inválida: '{action}' desde estado '{cur}'."}

    update = {"status": nxt}
    if nxt in _TIMESTAMP:
        update[_TIMESTAMP[nxt]] = datetime.now().isoformat()
    await client.table("purchase_order_drafts").update(update).eq("id", po_id).execute()

    bumped = 0
    if nxt == "delivered":
        bumped = await _bump_stock_on_delivery(client, po.get("items") or [])
    return {"status": "success", "po_id": po_id, "po_status": nxt, "stock_bumped": bumped}


_ORDER = ["pending_audit", "confirmed", "dispatched", "delivered"]
