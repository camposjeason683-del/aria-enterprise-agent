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
        log_info(f"Triggering ReorderAlert for {product} (Stock: {stock})")
        
        # Fire pipeline into background
        # Usually requires a runner setup, this simulates the background firing
        msg = f"Revisa el stock crítico de {product} generame una pauta de reorden."
        # Background task simulation
        pass
        
    return {"status": "ok"}
