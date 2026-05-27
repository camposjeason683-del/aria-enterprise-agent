"""
ARIA-OS: Database Query Tools (FunctionTools)
Each function becomes a tool that LLM agents can invoke.
All functions are async and return dicts for ADK compatibility.
"""
import os
from datetime import datetime, timedelta

from src.infra.db import get_supabase


async def query_inventory_ledger(
    product_name: str = "",
    days: int = 7,
) -> dict:
    """Query the Universal Inventory Ledger for daily stock history.

    Args:
        product_name: Partial product name filter. Empty = all products.
        days: How many days back to query (max 90).

    Returns:
        Records with product_name, snapshot_date, stock_end_of_day,
        sales_velocity, and production_detected.
    """
    days = min(days, 90)
    client = await get_supabase()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    q = (
        client.table("daily_inventory_ledger")
        .select(
            "product_name, date, stock_end_of_day, "
            "sales_velocity, production_detected"
        )
        .gte("date", cutoff)
        .order("date", desc=True)
        .limit(200)
    )

    if product_name:
        q = q.ilike("product_name", f"%{product_name}%")

    res = await q.execute()
    return {"records": res.data, "count": len(res.data)}


async def query_product_details(
    product_name: str,
) -> dict:
    """Get full details of a specific product including supplier info.

    Args:
        product_name: Exact or partial product name to search.

    Returns:
        Latest ledger snapshot and supplier catalog mapping.
    """
    client = await get_supabase()

    # Latest snapshot from ledger
    ledger = (
        await client.table("daily_inventory_ledger")
        .select("*")
        .ilike("product_name", f"%{product_name}%")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )

    # Supplier info
    supplier = (
        await client.table("supplier_catalog")
        .select("proveedor, marca, submarca")
        .ilike("nombre_original", f"%{product_name}%")
        .limit(1)
        .execute()
    )

    return {
        "ledger": ledger.data[0] if ledger.data else None,
        "supplier": supplier.data[0] if supplier.data else None,
    }


async def get_stock_alerts(
    threshold: int = 10,
) -> dict:
    """Get products with stock below a critical threshold.

    Args:
        threshold: Stock level below which a product is considered critical.

    Returns:
        List of products with critically low stock.
    """
    client = await get_supabase()
    # Fetch the latest available date in daily_inventory_ledger to handle stale data
    date_res = await client.table("daily_inventory_ledger").select("date").order("date", desc=True).limit(1).execute()
    if date_res.data:
        target_date_str = date_res.data[0]["date"]
        from datetime import datetime as dt
        target_date = dt.strptime(target_date_str, "%Y-%m-%d").date()
        prev_date_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
        prev_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    res = (
        await client.table("daily_inventory_ledger")
        .select("product_name, stock_end_of_day, sales_velocity")
        .eq("date", target_date_str)
        .lte("stock_end_of_day", threshold)
        .order("stock_end_of_day", desc=False)
        .limit(50)
        .execute()
    )

    # If no data for today, try yesterday
    if not res.data:
        res = (
            await client.table("daily_inventory_ledger")
            .select("product_name, stock_end_of_day, sales_velocity")
            .eq("date", prev_date_str)
            .lte("stock_end_of_day", threshold)
            .order("stock_end_of_day", desc=False)
            .limit(50)
            .execute()
        )

    return {"alerts": res.data, "threshold": threshold, "count": len(res.data), "date_used": target_date_str}


async def compare_stock_periods(
    product_name: str = "",
    period_1_days_ago: int = 7,
    period_2_days_ago: int = 14,
) -> dict:
    """Compare stock levels between two time periods.

    Args:
        product_name: Product to compare. Empty = top movers.
        period_1_days_ago: Start of recent period (e.g., 7 = one week ago).
        period_2_days_ago: Start of older period (e.g., 14 = two weeks ago).

    Returns:
        Comparison showing stock delta and velocity change.
    """
    client = await get_supabase()

    date_1 = (datetime.now() - timedelta(days=period_1_days_ago)).strftime("%Y-%m-%d")
    date_2 = (datetime.now() - timedelta(days=period_2_days_ago)).strftime("%Y-%m-%d")

    q1 = (
        client.table("daily_inventory_ledger")
        .select("product_name, stock_end_of_day, sales_velocity")
        .eq("date", date_1)
        .limit(50)
    )
    q2 = (
        client.table("daily_inventory_ledger")
        .select("product_name, stock_end_of_day, sales_velocity")
        .eq("date", date_2)
        .limit(50)
    )

    if product_name:
        q1 = q1.ilike("product_name", f"%{product_name}%")
        q2 = q2.ilike("product_name", f"%{product_name}%")

    res_1 = await q1.execute()
    res_2 = await q2.execute()

    # Build comparison
    p1_map = {r["product_name"]: r for r in (res_1.data or [])}
    comparisons = []
    for r2 in (res_2.data or []):
        name = r2["product_name"]
        if name in p1_map:
            r1 = p1_map[name]
            stock_delta = (r1.get("stock_end_of_day") or 0) - (r2.get("stock_end_of_day") or 0)
            vel_delta = (r1.get("sales_velocity") or 0) - (r2.get("sales_velocity") or 0)
            comparisons.append({
                "product": name,
                "stock_recent": r1.get("stock_end_of_day"),
                "stock_older": r2.get("stock_end_of_day"),
                "stock_delta": stock_delta,
                "velocity_recent": r1.get("sales_velocity"),
                "velocity_older": r2.get("sales_velocity"),
                "velocity_delta": round(vel_delta, 2),
            })

    return {
        "period_recent": date_1,
        "period_older": date_2,
        "comparisons": comparisons[:20],
    }
