"""
ARIA-OS: Sales Database Tools (FunctionTools)
Queries the wc_orders_cache locally.
"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from src.infra.db import get_supabase

async def query_orders(status: str = "processing", limit: int = 10) -> dict:
    """Fetch orders matching a specific status."""
    client = await get_supabase()
    res = (
        await client.table("wc_orders_cache")
        .select("id, total, currency, customer_name, date_created")
        .eq("status", status)
        .order("date_created", desc=True)
        .limit(limit)
        .execute()
    )
    return {"orders": res.data, "count": len(res.data or [])}

async def query_revenue_summary(days: int = 7) -> dict:
    """Calculate total revenue over the last N days."""
    client = await get_supabase()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    
    # P2: aggregate (SUM/COUNT) in the DB instead of transferring every order row
    # to sum in Python. exec_safe_read is SECURITY INVOKER → RLS still scopes the
    # rows to the caller's tenant. `cutoff` is a computed ISO string (derived from
    # the int `days`); no user-controlled text reaches the SQL.
    sql = (
        "SELECT COALESCE(SUM((total)::numeric), 0) AS revenue, COUNT(*) AS n "
        "FROM wc_orders_cache "
        f"WHERE date_created >= '{cutoff}' "
        "AND status IN ('completed', 'processing')"
    )
    res = await client.rpc("exec_safe_read", {"q": sql})
    row = (res.data or [{}])[0]

    return {
        "revenue": round(float(row.get("revenue") or 0), 2),
        "days": days,
        "orders_counted": int(row.get("n") or 0),
    }

async def query_top_customers(days: int = 30, limit: int = 5) -> dict:
    """Find customers who bought the most in the last N days."""
    client = await get_supabase()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    
    # P2: GROUP BY + ORDER BY + LIMIT in the DB instead of fetching every order and
    # ranking the top-N in Python (fetch-all anti-pattern). RLS-scoped via
    # exec_safe_read (SECURITY INVOKER). `limit` is coerced to int; `cutoff` is a
    # computed ISO string — no user-controlled text reaches the SQL. The name guard
    # mirrors the old `if name:` (skip NULL and empty string).
    sql = (
        "SELECT customer_name, COALESCE(SUM((total)::numeric), 0) AS total_spent "
        "FROM wc_orders_cache "
        f"WHERE date_created >= '{cutoff}' "
        "AND status IN ('completed', 'processing') "
        "AND customer_name IS NOT NULL AND customer_name <> '' "
        "GROUP BY customer_name "
        "ORDER BY total_spent DESC "
        f"LIMIT {int(limit)}"
    )
    res = await client.rpc("exec_safe_read", {"q": sql})

    return {
        "top_customers": [
            {"name": r.get("customer_name"), "total_spent": round(float(r.get("total_spent") or 0), 2)}
            for r in (res.data or [])
        ]
    }

async def calc_avg_order_value(days: int = 30) -> dict:
    """Calculate the average ticket size (AOV)."""
    rev = await query_revenue_summary(days=days)
    count = rev["orders_counted"]
    total = rev["revenue"]
    
    aov = round(total / count, 2) if count > 0 else 0
    return {"avg_order_value": aov, "based_on_orders": count, "days": days}

async def query_order_details(order_id: int) -> dict:
    """Get full details of a specific order including line items."""
    client = await get_supabase()
    res = (
        await client.table("wc_orders_cache")
        .select("*")
        .eq("id", order_id)
        .limit(1)
        .execute()
    )
    return {"order": res.data[0] if res.data else None}

async def query_customer_churn(months: int = 3, reference_date: str = "2026-05-22") -> dict:
    """
    Calculates detailed customer metrics and churn rate for a given period of months 
    relative to a reference date.
    
    This is the recommended tool for all customer acquisition, retention, and churn questions.
    
    Args:
        months: Length of the analysis period in months (default 3).
        reference_date: Reference date as YYYY-MM-DD (default "2026-05-22").
        
    Returns:
        dict with customer metrics:
          - analysis_period: Date range of target period
          - baseline_period: Date range of baseline period
          - base_activa: Customers active at the start of the period (baseline)
          - clientes_retenidos: Customers who purchased in both baseline and target periods
          - clientes_perdidos: Customers who purchased in baseline but not in target
          - clientes_nuevos: Customers whose first purchase ever occurred in the target period
          - total_activos_periodo: Total unique customers with active sales in target period
          - tasa_churn: Percentage of lost customers relative to active base
    """
    # Parse reference date
    try:
        ref_dt = datetime.fromisoformat(reference_date)
    except ValueError:
        try:
            ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
        except ValueError:
            ref_dt = datetime.now()
            
    ref_dt = ref_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Calculate periods
    target_start_dt = ref_dt - relativedelta(months=months)
    target_start_dt = target_start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    baseline_start_dt = target_start_dt - relativedelta(months=months)
    baseline_start_dt = baseline_start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    ref_str = ref_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    target_start_str = target_start_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    baseline_start_str = baseline_start_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    
    client = await get_supabase()
    status_filter = "status NOT IN ('cancelled', 'failed', 'trash', 'draft')"
    
    query = f"""
    WITH Baseline AS (
      SELECT DISTINCT customer_name 
      FROM wc_orders_cache 
      WHERE date_created >= '{baseline_start_str}' 
        AND date_created < '{target_start_str}'
        AND customer_name IS NOT NULL AND customer_name != ''
        AND {status_filter}
    ),
    Target AS (
      SELECT DISTINCT customer_name
      FROM wc_orders_cache
      WHERE date_created >= '{target_start_str}'
        AND date_created <= '{ref_str}'
        AND {status_filter}
    )
    SELECT 
      (SELECT COUNT(*) FROM Baseline) as base_activa,
      (
        SELECT COUNT(*) 
        FROM Baseline b
        JOIN Target t ON b.customer_name = t.customer_name
      ) as clientes_retenidos,
      (
        SELECT COUNT(*)
        FROM Target tc
        LEFT JOIN wc_orders_cache p ON tc.customer_name = p.customer_name 
          AND p.date_created < '{target_start_str}'
          AND {status_filter}
        WHERE p.customer_name IS NULL
      ) as clientes_nuevos,
      (SELECT COUNT(*) FROM Target) as total_activos_periodo
    """
    
    res = await client.rpc("exec_safe_read", {"q": query})  # F5: real RPC (was undefined execute_read_query)
    if not res.data:
        return {"error": "No data returned from database."}
        
    data = res.data[0]
    base_activa = data.get("base_activa", 0)
    retained = data.get("clientes_retenidos", 0)
    new_customers = data.get("clientes_nuevos", 0)
    total_activos = data.get("total_activos_periodo", 0)
    
    lost = base_activa - retained
    churn_rate = round((lost / base_activa * 100), 2) if base_activa > 0 else 0.0
    
    return {
        "analysis_period": f"{target_start_dt.strftime('%Y-%m-%d')} to {ref_dt.strftime('%Y-%m-%d')}",
        "baseline_period": f"{baseline_start_dt.strftime('%Y-%m-%d')} to {target_start_dt.strftime('%Y-%m-%d')}",
        "base_activa": base_activa,
        "clientes_retenidos": retained,
        "clientes_perdidos": lost,
        "clientes_nuevos": new_customers,
        "total_activos_periodo": total_activos,
        "tasa_churn": churn_rate
    }
