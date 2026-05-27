"""
ARIA-OS: Skill Retriever
Centralized registry mapping each routing node to its specific toolset.
This ensures each agent only receives the tools it needs, preventing token
overload (28+ tools) and reducing Gemini API costs.

Usage:
    from src.graph.skill_retriever import get_tools_for_node
    tools = get_tools_for_node("finance")
"""
from typing import List, Callable

from src.tools.sales import (
    calc_avg_order_value,
    query_order_details,
    query_orders,
    query_revenue_summary,
    query_top_customers,
    query_customer_churn,
)
from src.tools.finance import (
    calc_break_even,
    calc_gross_margin,
    calc_profit_loss,
    compare_financial_periods,
    query_price_history,
)
from src.tools.calculations import (
    calc_days_of_inventory,
    calc_production_detected,
    calc_reorder_point,
    calc_sales_forecast,
)
from src.tools.database import (
    compare_stock_periods,
    get_stock_alerts,
    query_inventory_ledger,
    query_product_details,
)
from src.tools.procurement import (
    calc_supplier_dependency,
    query_purchase_history,
    query_supplier_catalog,
    suggest_reorder_batch,
)
from src.tools.strategic import (
    analyze_trends_cross_department,
    estimate_decision_impact,
    execute_approved_proposal,
    gather_full_business_snapshot,
    list_pending_proposals,
    submit_proposal,
    analyze_supply_chain_bottlenecks,
    predict_stockouts_and_repurchase,
    detect_dead_stock_and_rebalance,
    batch_purchase_orders,
    dynamic_pricing_for_scarcity,
    audit_supplier_performance,
    execute_proactive_sweep_auto,
)
from src.tools.analytics import (
    rank_products_by_real_profitability,
    estimate_demand_elasticity,
    optimize_restock_with_budget,
    classify_products_bcg,
    analyze_market_basket,
    classify_product_lifecycle,
    calculate_stockout_risk_scores,
)
from src.tools.dynamic_execution import (
    execute_safe_read_query,
    execute_python_script,
)
from src.tools.ham_memory import manage_ham_memory
from src.tools.skills_loader import load_dynamic_skills

# Load hot-plug dynamic skills once (shared)
_dynamic_skills: List[Callable] = []

def _get_dynamic_skills() -> List[Callable]:
    global _dynamic_skills
    if not _dynamic_skills:
        _dynamic_skills = load_dynamic_skills("c:/dashboard/intelligence-agent/skills")
    return _dynamic_skills


# ─── Canonical tool registry per node ────────────────────────────────────────
# Each key matches the routing intent in kernel.py
_NODE_TOOLS: dict[str, List[Callable]] = {
    "sales": [
        query_orders,
        query_revenue_summary,
        query_top_customers,
        query_order_details,
        calc_avg_order_value,
        query_customer_churn,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "finance": [
        calc_gross_margin,
        calc_profit_loss,
        query_price_history,
        calc_break_even,
        compare_financial_periods,
        rank_products_by_real_profitability,
        estimate_demand_elasticity,
        optimize_restock_with_budget,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "inventory": [
        query_inventory_ledger,
        query_product_details,
        calc_production_detected,
        calc_days_of_inventory,
        get_stock_alerts,
        compare_stock_periods,
        classify_products_bcg,
        analyze_market_basket,
        classify_product_lifecycle,
        calculate_stockout_risk_scores,
        optimize_restock_with_budget,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "demand": [
        calc_sales_forecast,
        calc_reorder_point,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "procurement": [
        query_supplier_catalog,
        query_purchase_history,
        calc_supplier_dependency,
        suggest_reorder_batch,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "strategic": [
        gather_full_business_snapshot,
        analyze_trends_cross_department,
        estimate_decision_impact,
        submit_proposal,
        list_pending_proposals,
        execute_approved_proposal,
        execute_proactive_sweep_auto,
        analyze_supply_chain_bottlenecks,
        predict_stockouts_and_repurchase,
        detect_dead_stock_and_rebalance,
        batch_purchase_orders,
        dynamic_pricing_for_scarcity,
        audit_supplier_performance,
        classify_products_bcg,
        analyze_market_basket,
        estimate_demand_elasticity,
        rank_products_by_real_profitability,
        classify_product_lifecycle,
        calculate_stockout_risk_scores,
        optimize_restock_with_budget,
        execute_safe_read_query,
        execute_python_script,
        manage_ham_memory,
    ],
    "coordinator": [
        execute_safe_read_query,
        execute_python_script,
    ],
}


def get_tools_for_node(node_name: str, include_dynamic: bool = True) -> List[Callable]:
    """
    Returns the specific, curated subset of tools for a given routing node.

    Args:
        node_name: One of 'sales', 'finance', 'inventory', 'demand',
                   'procurement', 'strategic', 'coordinator'.
        include_dynamic: If True, appends hot-plug dynamic skills loaded from
                         the skills/ directory (default: True).

    Returns:
        List of callable tools ready to be passed to an LlmAgent.
    """
    base = _NODE_TOOLS.get(node_name, []).copy()
    if include_dynamic and node_name not in ("coordinator",):
        base += _get_dynamic_skills()
    return base
