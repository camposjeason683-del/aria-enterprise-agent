"""
ARIA-OS: Deterministic Calculation Tools (FunctionTools)
Pure math — zero LLM involvement. Every number comes from the database
and a deterministic formula. Zero hallucinations possible.
"""
from datetime import datetime, timedelta

from src.infra.db import get_supabase


async def calc_production_detected(
    product_name: str,
    date: str = "",
) -> dict:
    """Calculate detected production for a product on a given date.
    Formula: MAX(0, (Stock_Today - Stock_Yesterday) + Sales_Today)

    Args:
        product_name: Name of the product.
        date: Date in YYYY-MM-DD format. Empty = today.

    Returns:
        Production detected with full calculation breakdown.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    yesterday = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    client = await get_supabase()

    today_data = (
        await client.table("daily_inventory_ledger")
        .select("stock_end_of_day, sales_velocity")
        .ilike("product_name", f"%{product_name}%")
        .eq("date", target_date)
        .limit(1)
        .execute()
    )

    yesterday_data = (
        await client.table("daily_inventory_ledger")
        .select("stock_end_of_day")
        .ilike("product_name", f"%{product_name}%")
        .eq("date", yesterday)
        .limit(1)
        .execute()
    )

    if not today_data.data:
        return {"error": f"No hay datos de '{product_name}' para {target_date}"}

    stock_today = today_data.data[0].get("stock_end_of_day") or 0
    sales_today = today_data.data[0].get("sales_velocity") or 0
    stock_yesterday = (
        yesterday_data.data[0].get("stock_end_of_day")
        if yesterday_data.data
        else stock_today
    )

    production = max(0, (stock_today - stock_yesterday) + sales_today)

    return {
        "product": product_name,
        "date": target_date,
        "stock_today": stock_today,
        "stock_yesterday": stock_yesterday,
        "sales_today": sales_today,
        "production_detected": production,
        "formula": "MAX(0, (Stock_Hoy - Stock_Ayer) + Ventas_Hoy)",
    }


async def calc_days_of_inventory(
    product_name: str,
) -> dict:
    """Calculate how many days of inventory remain for a product.
    Formula: Stock_Current / Daily_Sales_Velocity

    Args:
        product_name: Name of the product.

    Returns:
        Days of inventory remaining with traffic-light status.
    """
    client = await get_supabase()

    latest = (
        await client.table("daily_inventory_ledger")
        .select("stock_end_of_day, sales_velocity, date")
        .ilike("product_name", f"%{product_name}%")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )

    if not latest.data:
        return {"error": f"No hay datos de inventario para '{product_name}'"}

    stock = latest.data[0].get("stock_end_of_day") or 0
    velocity = latest.data[0].get("sales_velocity") or 0
    daily_velocity = velocity / 7 if velocity > 0 else 0

    days_remaining = (
        round(stock / daily_velocity, 1) if daily_velocity > 0 else float("inf")
    )

    if days_remaining == float("inf"):
        status = "⚪ SIN VENTAS"
    elif days_remaining < 3:
        status = "🔴 CRÍTICO"
    elif days_remaining < 7:
        status = "🟡 ALERTA"
    else:
        status = "🟢 NORMAL"

    return {
        "product": product_name,
        "stock_actual": stock,
        "venta_diaria_promedio": round(daily_velocity, 2),
        "dias_de_inventario": days_remaining,
        "status": status,
        "formula": "Stock_Actual / (Velocidad_Semanal / 7)",
    }


async def calc_reorder_point(
    product_name: str,
    lead_time_days: int = 3,
) -> dict:
    """Calculate the reorder point for a product.
    Formula: Daily_Sales_Velocity × Lead_Time

    Args:
        product_name: Name of the product.
        lead_time_days: Supplier delivery time in days.

    Returns:
        Reorder point, current stock, and whether reorder is needed.
    """
    lead_time_days = min(lead_time_days, 30)
    client = await get_supabase()

    latest = (
        await client.table("daily_inventory_ledger")
        .select("stock_end_of_day, sales_velocity")
        .ilike("product_name", f"%{product_name}%")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )

    if not latest.data:
        return {"error": f"No hay datos para '{product_name}'"}

    stock = latest.data[0].get("stock_end_of_day") or 0
    velocity = latest.data[0].get("sales_velocity") or 0
    daily = velocity / 7 if velocity > 0 else 0

    reorder_point = round(daily * lead_time_days, 0)
    needs_reorder = stock <= reorder_point

    return {
        "product": product_name,
        "stock_actual": stock,
        "venta_diaria": round(daily, 2),
        "lead_time_dias": lead_time_days,
        "punto_de_reorden": reorder_point,
        "necesita_reposicion": "⚠️ SÍ - REPONER AHORA" if needs_reorder else "✅ No por ahora",
        "formula": "Venta_Diaria × Lead_Time",
    }


async def calc_sales_forecast(
    product_name: str,
    forecast_days: int = 30,
) -> dict:
    """Quick LINEAR sales projection (Average_Daily_Sales × Forecast_Days).

    NOTE: coarse point estimate only. For a real demand forecast with seasonality
    and confidence intervals, prefer `forecast_sales` (statistical SARIMAX /
    Holt-Winters). Keep this only for a fast back-of-the-envelope number.

    Args:
        product_name: Name of the product.
        forecast_days: Number of days to project (max 90).

    Returns:
        Sales projection with confidence level.
    """
    forecast_days = min(forecast_days, 90)
    client = await get_supabase()

    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    history = (
        await client.table("daily_inventory_ledger")
        .select("sales_velocity, date")
        .ilike("product_name", f"%{product_name}%")
        .gte("date", cutoff)
        .order("date", desc=True)
        .execute()
    )

    if not history.data:
        return {"error": f"No hay historial de ventas para '{product_name}'"}

    velocities = [r.get("sales_velocity") or 0 for r in history.data]
    avg_weekly = sum(velocities) / len(velocities)
    avg_daily = avg_weekly / 7

    forecast = round(avg_daily * forecast_days, 0)
    data_points = len(velocities)
    confidence = (
        "Alta" if data_points >= 14 else "Media" if data_points >= 7 else "Baja"
    )

    return {
        "product": product_name,
        "venta_diaria_promedio": round(avg_daily, 2),
        "dias_proyectados": forecast_days,
        "ventas_proyectadas": forecast,
        "confianza": confidence,
        "datos_historicos_usados": f"{data_points} registros",
        "formula": "Promedio_Ventas_Diarias × Días",
    }
