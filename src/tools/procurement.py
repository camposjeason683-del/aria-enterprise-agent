"""
ARIA-OS: Procurement Database Tools (FunctionTools)
Queries the supplier_catalog and purchase_order_drafts locally.
"""
from typing import Optional
from datetime import datetime
from src.infra.db import get_supabase

async def query_supplier_catalog(product_name: str = "") -> dict:
    """Search for products and their corresponding suppliers and brands."""
    client = await get_supabase()
    q = client.table("supplier_catalog").select("*")
    if product_name:
        q = q.ilike("nombre_original", f"%{product_name}%")
    
    res = await q.limit(50).execute()
    return {"catalog": res.data, "count": len(res.data or [])}

async def query_purchase_history(supplier_name: str = "", limit: int = 10) -> dict:
    """Fetch recent purchase orders, optionally filtered by supplier."""
    client = await get_supabase()
    # Currently, drafts have items formatted as JSONB which would need to be parsed
    # to filter by supplier per item. For simplicity in this demo, we fetch all
    # drafts and filter in-memory if a supplier is provided.
    res = (
        await client.table("purchase_order_drafts")
        .select("id, status, created_at, items")
        .order("created_at", desc=True)
        .limit(limit * 2) # Fetch extra in case we filter out
        .execute()
    )
    
    orders = res.data or []
    if supplier_name:
        filtered = []
        supplier_lower = supplier_name.lower()
        for o in orders:
            items = o.get("items", [])
            has_supplier = any(supplier_lower in (i.get("proveedor") or "").lower() for i in items)
            if has_supplier:
                filtered.append(o)
        orders = filtered[:limit]
        
    return {"purchase_orders": orders, "count": len(orders)}

async def calc_supplier_dependency() -> dict:
    """Calculate the percentage of products supplied by each supplier."""
    client = await get_supabase()
    res = await client.table("supplier_catalog").select("proveedor").execute()
    
    total = len(res.data or [])
    if total == 0:
        return {"error": "No catalog data found."}
        
    counts = {}
    for r in res.data:
        prov = r.get("proveedor") or "Desconocido"
        counts[prov] = counts.get(prov, 0) + 1
        
    dependency = [
        {"proveedor": k, "porcentaje": round((v / total) * 100, 2), "productos": v}
        for k, v in counts.items()
    ]
    dependency.sort(key=lambda x: x["productos"], reverse=True)
    
    return {"supplier_dependency": dependency[:10], "total_products_mapped": total}

async def suggest_reorder_batch(supplier_name: str) -> dict:
    """Suggest an optimal shopping cart for a specific supplier
    based on items currently critically low in stock."""
    
    client = await get_supabase()
    
    # 1. Get all products for this supplier
    cat_res = await client.table("supplier_catalog").select("product_id, nombre_original").ilike("proveedor", f"%{supplier_name}%").execute()
    supplier_products = cat_res.data or []
    if not supplier_products:
        return {"error": f"No products found for supplier {supplier_name}"}
        
    # 2. Get stock alerts (under 15 units) for today
    today = datetime.now().strftime("%Y-%m-%d")
    stock_res = (
        await client.table("daily_inventory_ledger")
        .select("product_id, product_name, stock_end_of_day, sales_velocity")
        .eq("date", today)
        .lte("stock_end_of_day", 15)
        .execute()
    )
    
    alerts = stock_res.data or []
    if not alerts:
        # Fallback to yesterday if today's ledger hasn't generated
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        stock_res = (
            await client.table("daily_inventory_ledger")
            .select("product_id, product_name, stock_end_of_day, sales_velocity")
            .eq("date", yesterday)
            .lte("stock_end_of_day", 15)
            .execute()
        )
        alerts = stock_res.data or []
        
    # 3. Intersect
    suggested = []
    supplier_pids = {p["product_id"]: p["nombre_original"] for p in supplier_products if p.get("product_id")}
    
    for alert in alerts:
        pid = alert.get("product_id")
        if pid and pid in supplier_pids:
            # Reorder calculation: cover 14 days of velocity
            daily_vel = (alert.get("sales_velocity") or 0) / 7
            reorder_qty = max(20, int(daily_vel * 14)) # Minimum 20 units
            suggested.append({
                "product": supplier_pids[pid],
                "stock_actual": alert.get("stock_end_of_day"),
                "sugerencia_compra": reorder_qty
            })
            
    suggested.sort(key=lambda x: x["stock_actual"])
    return {"supplier": supplier_name, "suggested_batch": suggested, "count": len(suggested)}
