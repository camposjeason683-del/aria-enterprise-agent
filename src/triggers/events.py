"""
ARIA-OS: Event Triggers
Receives external hooks (e.g. Supabase webhooks) to trigger pipelines.
"""
from fastapi import APIRouter, Request
from google.genai import types
from src.agents.pipelines import reorder_alert
from src.infra.logger import log_info

router = APIRouter()

@router.post("/api/v1/webhook/database-trigger")
async def handle_db_trigger(req: Request):
    """
    Listens to Postgres triggers (e.g. when daily_inventory_ledger stock < threshold).
    If triggered, fire the reorder_alert pipeline asynchronously.
    """
    payload = await req.json()
    record = payload.get("record", {})
    
    stock = record.get("stock_end_of_day", 0)
    product = record.get("product_name", "Unknown")
    
    if stock <= 15:
        # M3: the reorder_alert pipeline is NOT wired to a Runner here and this router
        # is not mounted in main.py. Return 501 instead of a false 200 so the caller
        # (Postgres trigger) does not believe an alert was produced (explicit disable
        # over silent breakage — CLAUDE.md). TODO: wire `reorder_alert` to the Runner.
        from fastapi import HTTPException

        log_info(f"ReorderAlert trigger received for {product} (Stock: {stock}) — pipeline not wired")
        raise HTTPException(501, "Automatización de reorden no implementada todavía.")

    return {"status": "ok"}
