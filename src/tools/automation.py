"""ARIA-OS: reglas de automatización declarativas ("si métrica X cruza umbral → Y").

Una tabla per-tenant `automation_rules` (migración 0008) guarda las reglas;
`evaluate_rules` corre en cada cron tick (bajo el contexto headless per-tenant),
computa SOLO las métricas que sus reglas referencian (reusando las tools analíticas
existentes, sin SQL duplicado), y dispara la acción que matchea — hoy
`create_proposal` vía el surface HITL existente.

El core de matching `_evaluate(rules, metrics)` es PURO → testeado como truth table.
"""
from __future__ import annotations

from typing import Any

from src.infra.db import get_supabase

_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}

# Catálogo de métricas soportadas → etiqueta legible (lo que la UI/reglas referencian).
SUPPORTED_METRICS = {
    "stockout_risk_max": "Riesgo de quiebre máximo (0-100)",
    "stockout_risk_critical_count": "Productos en riesgo crítico",
    "net_margin_pct": "Margen neto %",
    "revenue_30d": "Revenue últimos 30 días",
}


def _compare(value: float, op: str, threshold: float) -> bool:
    fn = _OPS.get(op)
    return bool(fn(value, threshold)) if fn else False


def _evaluate(rules: list[dict], metrics: dict) -> list[dict]:
    """PURO: devuelve las reglas que disparan dado un mapa {metric: value}.
    Saltea reglas cuya métrica falta/None o cuyo threshold no es numérico."""
    fired = []
    for rule in rules:
        val = metrics.get(rule.get("metric"))
        if val is None:
            continue
        try:
            if _compare(float(val), rule.get("op"), float(rule.get("threshold"))):
                fired.append(rule)
        except (TypeError, ValueError):
            continue
    return fired


async def _metric_value(metric: str, cache: dict) -> float | None:
    """Computa una métrica lazily (cacheada por llamada a evaluate_rules), reusando
    las tools existentes. Cualquier fallo → None (no aborta el loop de reglas)."""
    if metric in cache:
        return cache[metric]
    value: float | None = None
    try:
        if metric in ("stockout_risk_max", "stockout_risk_critical_count"):
            from src.tools.analytics import calculate_stockout_risk_scores

            r = await calculate_stockout_risk_scores()
            if r.get("status") == "success":
                if metric == "stockout_risk_max":
                    ranking = r.get("ranking_completo") or r.get("top_riesgo_critico") or []
                    value = float(max((x.get("risk_score", 0) for x in ranking), default=0))
                else:
                    value = float(r.get("resumen", {}).get("criticos", 0))
        elif metric == "net_margin_pct":
            from src.tools.finance import calc_profit_loss

            r = await calc_profit_loss(days=30)
            v = r.get("margen_neto_porcentaje")
            value = float(v) if v is not None else None
        elif metric == "revenue_30d":
            from src.tools.sales import query_revenue_summary

            r = await query_revenue_summary(days=30)
            v = r.get("revenue")
            value = float(v) if v is not None else None
    except Exception:  # noqa: BLE001 — una métrica que falla no debe abortar el loop
        value = None
    cache[metric] = value
    return value


async def _fire(rule: dict, value: float) -> dict:
    action = (rule.get("action") or "create_proposal").strip()
    if action == "create_proposal":
        from src.tools.strategic import submit_proposal

        label = SUPPORTED_METRICS.get(rule.get("metric"), rule.get("metric"))
        return await submit_proposal(
            title=f"Regla disparada: {rule.get('name')}",
            problem=(
                f"La métrica '{label}' = {round(value, 2)} cruzó tu umbral "
                f"({rule.get('op')} {rule.get('threshold')})."
            ),
            proposed_action="Revisá y decidí la acción correspondiente para esta alerta.",
            urgency="alta",
            category="Automatización",
            strategy="Regla de automatización (if-then)",
        )
    return {"status": "skipped", "reason": f"acción no soportada: {action}"}


async def evaluate_rules() -> dict:
    """Lee las reglas habilitadas del tenant, computa las métricas referenciadas una
    sola vez, y dispara las acciones que matchean. Corre bajo el contexto del tenant
    (headless cron o JWT)."""
    client = await get_supabase()
    rules = (
        await client.table("automation_rules").select("*").eq("enabled", True).execute()
    ).data or []
    if not rules:
        return {"rules_evaluated": 0, "fired": []}

    cache: dict[str, Any] = {}
    metrics: dict = {}
    for metric in {r.get("metric") for r in rules}:
        metrics[metric] = await _metric_value(metric, cache)

    fired = []
    for rule in _evaluate(rules, metrics):
        res = await _fire(rule, float(metrics[rule["metric"]]))
        fired.append(
            {
                "rule": rule.get("name"),
                "metric": rule.get("metric"),
                "value": metrics[rule["metric"]],
                "action": res,
            }
        )
    return {"rules_evaluated": len(rules), "fired": fired}
