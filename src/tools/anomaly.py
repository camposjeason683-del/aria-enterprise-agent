"""ARIA-OS: detección autónoma de anomalías en la demanda.

Cruza la serie de ventas de cada producto con el modelo de pronóstico para hallar
señales que ningún humano pidió mirar, y las deja como un hallazgo en la bandeja
(reusa submit_proposal con categoría "Anomalía" — cero cambio de UI). Dos
detectores baratos y explicables:

1. **Residuo del forecast** — se ajusta un pronóstico de 1 paso sobre la historia
   sin el último día (reusa `_fit_forecast`); si el último real cae FUERA de su
   propio intervalo [lo, hi], es un pico/caída anómalo con magnitud lista.
2. **Changepoint (CUSUM)** — quiebre de régimen sostenido en la velocidad.

El scan por serie `_scan_series` y `_cusum` son PUROS (sin DB) → unit-testeables.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from src.infra.db import get_supabase
from src.tools.forecasting import _fit_forecast


def _cusum(series: list[float], threshold: float = 5.0) -> int | None:
    """CUSUM changepoint PURO: acumula desvíos normalizados de la media; devuelve el
    índice donde la suma acumulada cruza ±threshold (quiebre de régimen), si no None.
    Determinístico, numpy-free."""
    n = len(series)
    if n < 8:
        return None
    mean = sum(series) / n
    sigma = (sum((x - mean) ** 2 for x in series) / n) ** 0.5 or 1.0
    s_pos = 0.0
    s_neg = 0.0
    for i, x in enumerate(series):
        d = (x - mean) / sigma
        s_pos = max(0.0, s_pos + d - 0.5)
        s_neg = min(0.0, s_neg + d + 0.5)
        if s_pos > threshold or s_neg < -threshold:
            return i
    return None


def _scan_series(product: str, vals: list[float], season: int = 7) -> list[dict]:
    """Scan PURO de una serie de un producto (residuo del forecast + CUSUM). Sin DB."""
    out: list[dict] = []
    if len(vals) < 10:
        return out
    core = _fit_forecast(vals[:-1], 1, season=season)
    if core["status"] == "success":
        last = vals[-1]
        lo, hi = core["lo"][0], core["hi"][0]
        if last < lo or last > hi:
            direction = "caída" if last < lo else "pico"
            expected = round(core["point"][0], 1)
            out.append(
                {
                    "product": product,
                    "tipo": f"{direction} de demanda",
                    "detalle": (
                        f"Último día = {round(last, 1)} u, fuera del rango esperado "
                        f"[{round(lo, 1)}, {round(hi, 1)}] (esperado ≈ {expected})."
                    ),
                    "severidad": round(abs(last - expected), 2),
                }
            )
    cp = _cusum(vals)
    if cp is not None:
        out.append(
            {
                "product": product,
                "tipo": "cambio de régimen",
                "detalle": f"Quiebre de tendencia (CUSUM) cerca del punto {cp}/{len(vals)}.",
                "severidad": 0.0,
            }
        )
    return out


async def detect_anomalies(top_n: int = 20, season: int = 7) -> dict:
    """Escanea las series de ventas de los productos del tenant buscando anomalías
    (pico/caída fuera del intervalo del forecast + quiebres de régimen) y deja UNA
    propuesta consolidada categoría "Anomalía" en la bandeja. Corre bajo el contexto
    del tenant (headless cron o JWT)."""
    client = await get_supabase()
    cutoff = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    rows = (
        await client.table("daily_inventory_ledger")
        .select("product_name, sales_velocity, date")
        .gte("date", cutoff)
        .order("date", desc=True)
        .limit(4000)
        .execute()
    ).data or []

    by_product: dict = defaultdict(list)
    for r in rows:
        by_product[r.get("product_name")].append(
            (str(r.get("date"))[:10], float(r.get("sales_velocity") or 0))
        )

    findings: list[dict] = []
    for product, pts in by_product.items():
        if not product:
            continue
        pts.sort()  # chronological
        findings.extend(_scan_series(product, [v for _, v in pts], season=season))

    findings.sort(key=lambda f: f["severidad"], reverse=True)
    findings = findings[:top_n]
    if not findings:
        return {"status": "no_anomalies", "count": 0, "findings": []}

    from src.tools.strategic import submit_proposal

    lines = [f"- {f['product']}: {f['tipo']} — {f['detalle']}" for f in findings]
    res = await submit_proposal(
        title="Anomalías detectadas en la demanda",
        problem=(
            f"Se detectaron {len(findings)} señales anómalas cruzando la serie de "
            f"ventas con el modelo de pronóstico (residuos fuera del intervalo + "
            f"quiebres de régimen)."
        ),
        proposed_action="Revisá los productos señalados:\n" + "\n".join(lines),
        urgency="media",
        category="Anomalía",
        strategy="Detección autónoma de anomalías (residuos del forecast + CUSUM)",
        recommendation=(
            "Estas señales surgen de comparar la realidad reciente contra lo que el "
            "modelo SARIMAX/ETS esperaba. Un pico/caída fuera del intervalo del 80% o "
            "un quiebre de régimen ameritan revisar causas (promo, quiebre de stock, "
            "estacionalidad atípica) antes de que impacten el reabastecimiento."
        ),
        items=findings,
    )
    return {"status": "success", "count": len(findings), "findings": findings, "proposal": res}
