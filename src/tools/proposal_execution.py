"""Apply the real-world effects of an APPROVED proposal — the action loop's close.

The ``/execute`` endpoint delegates here. Reabastecimiento keeps the existing PO-draft
path (``strategic.execute_approved_proposal`` — untouched, owned elsewhere); price and
liquidation proposals now actually write back to WooCommerce instead of silently marking
themselves executed. Idempotent via the proposal status (``executed`` → no-op)."""
from __future__ import annotations

from datetime import datetime

from src.infra.db import get_supabase
from src.infra.logger import log_error
from src.infra.tenant_context import current
from src.tools import writeback

_REORDER = {"reabastecimiento", "abastecimiento", "compra", "orden de compra"}
_PRICE = {"ajuste de precios", "pricing", "precio", "dynamic pricing", "ajuste de precio"}
_LIQUID = {"liquidación", "liquidacion", "dead stock", "liquidación de stock", "liquidacion de stock"}


def _item_name(it: dict):
    return it.get("product_name") or it.get("product") or it.get("name")


def _item_value(it: dict, *keys):
    for k in keys:
        v = it.get(k)
        if v is not None:
            return v
    return None


async def apply_proposal_effects(proposal_id: str) -> dict:
    """Execute an approved proposal's side effects. Idempotent on proposal status."""
    client = await get_supabase()
    res = await client.table("aria_proposals").select("*").eq("id", proposal_id).limit(1).execute()
    if not res.data:
        return {"error": "Propuesta no encontrada."}
    p = res.data[0]
    if p["status"] == "executed":
        return {"status": "noop", "idempotent": True, "message": "La propuesta ya fue ejecutada."}
    if p["status"] != "approved":
        return {"error": f"Requiere aprobación humana. Estado actual: {p['status']}."}

    category = (p.get("category") or "").strip().lower()

    # Reabastecimiento → keep the existing PO-draft path (it also marks executed).
    if category in _REORDER:
        from src.tools.strategic import execute_approved_proposal
        return await execute_approved_proposal(proposal_id)

    # Price / liquidation → write back to the store per item.
    ctx = current()
    tid = ctx.tenant_id if ctx else None
    effects = []
    for it in (p.get("items") or []):
        name = _item_name(it)
        if not name or not tid:
            continue
        try:
            if category in _LIQUID:
                price = _item_value(it, "sale_price", "new_price", "price")
                if price is not None:
                    effects.append(await writeback.woo_set_sale(tid, name, price))
            elif category in _PRICE:
                price = _item_value(it, "new_price", "price")
                if price is not None:
                    effects.append(await writeback.woo_update_price(tid, name, price))
        except Exception as e:  # noqa: BLE001 — a store error must not block the state update
            log_error("apply_proposal_effects writeback failed", error=str(e))
            effects.append({"status": "error", "product": name, "detail": str(e)})

    await client.table("aria_proposals").update(
        {"status": "executed", "executed_at": datetime.now().isoformat()}
    ).eq("id", proposal_id).execute()
    return {"status": "success", "category": category, "effects": effects,
            "message": f"Propuesta ejecutada. {len(effects)} efecto(s) aplicado(s)."}
