"""
ARIA-OS: Finance Database Tools (FunctionTools)
Queries focusing on profitability, margins, and financial comparisons.
"""
from datetime import datetime, timedelta
from src.infra.db import get_supabase
from src.tools.sales import query_revenue_summary

async def calc_gross_margin(product_name: str) -> dict:
    """Calculate the theoretical gross margin for a given product."""
    client = await get_supabase()
    # Ideally, products table would have a cost column.
    # We will simulate the cost as 60% of price for this enterprise demo
    res = (
        await client.table("products")
        .select("name, price")
        .ilike("name", f"%{product_name}%")
        .limit(1)
        .execute()
    )
    
    if not res.data:
        return {"error": f"No product found matching {product_name}"}
        
    p = res.data[0]
    price = float(p.get("price") or 0)
    cost = round(price * 0.6, 2)
    margin = price - cost
    margin_percent = round((margin / price) * 100, 2) if price > 0 else 0
    
    return {
        "product": p["name"],
        "precio_venta": price,
        "costo_estimado": cost,
        "margen_bruto_monto": round(margin, 2),
        "margen_bruto_porcentaje": margin_percent,
        "formula": "(Precio - Costo) / Precio × 100"
    }

async def calc_profit_loss(days: int = 30) -> dict:
    """Estimate P&L over a given period."""
    # This queries sales revenue and applies an estimated global cost and opex.
    rev_data = await query_revenue_summary(days=days)
    revenue = rev_data.get("revenue", 0)
    
    # Simulating enterprise global metrics
    cogs = round(revenue * 0.58, 2)  # 58% Cost of Goods Sold
    opex = round(revenue * 0.20, 2)  # 20% Operational Expenses
    net_profit = round(revenue - cogs - opex, 2)
    net_margin = round((net_profit / revenue) * 100, 2) if revenue > 0 else 0
    
    return {
        "periodo_dias": days,
        "ingresos_totales_revenue": revenue,
        "cogs_estimado": cogs,
        "gastos_operativos_estimados": opex,
        "beneficio_neto": net_profit,
        "margen_neto_porcentaje": net_margin
    }

async def query_price_history(product_name: str) -> dict:
    """Mock query for price changes."""
    # Since we lack a price history table, we return the current price
    client = await get_supabase()
    res = await client.table("products").select("name, price").ilike("name", f"%{product_name}%").limit(1).execute()
    
    if not res.data:
        return {"error": "Product not found"}
        
    p = res.data[0]
    price = float(p.get("price") or 0)
    
    return {
        "product": p["name"],
        "precio_actual": price,
        "ultima_actualizacion": datetime.now().strftime("%Y-%m-%d"),
        "historial": [
            {"fecha": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), "precio": round(price * 0.95, 2)},
            {"fecha": (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"), "precio": round(price * 0.90, 2)}
        ]
    }

async def calc_break_even(fixed_costs: float, product_name: str) -> dict:
    """Calculate break-even point for a specific product context."""
    margin_data = await calc_gross_margin(product_name)
    if "error" in margin_data:
        return margin_data
        
    margin_amount = margin_data.get("margen_bruto_monto", 0)
    if margin_amount <= 0:
        return {"error": "El margen del producto es cero o negativo no se puede calcular break even."}
        
    units_needed = round(fixed_costs / margin_amount)
    
    return {
        "costos_fijos_ingresados": fixed_costs,
        "producto": margin_data["product"],
        "margen_unitario": margin_amount,
        "unidades_para_break_even": units_needed,
        "revenue_break_even": round(units_needed * margin_data["precio_venta"], 2),
        "formula": "Costos Fijos / Margen Unitario"
    }

async def compare_financial_periods(period_1_days_ago: int = 30, period_2_days_ago: int = 60) -> dict:
    """Compare revenue between two rolling periods."""
    p1 = await query_revenue_summary(days=period_1_days_ago) # Last 30 days
    p2 = await query_revenue_summary(days=period_2_days_ago) # Last 60 days
    
    # Calculate older period (e.g. day 60 to day 30)
    rev_older = p2["revenue"] - p1["revenue"]
    rev_recent = p1["revenue"]
    
    delta = rev_recent - rev_older
    delta_percent = round((delta / rev_older) * 100, 2) if rev_older > 0 else 0
    
    return {
        "periodo_reciente_dias": period_1_days_ago,
        "periodo_pasado_dias": period_2_days_ago - period_1_days_ago,
        "revenue_reciente": round(rev_recent, 2),
        "revenue_pasado": round(rev_older, 2),
        "diferencia": round(delta, 2),
        "crecimiento_porcentaje": delta_percent
    }
