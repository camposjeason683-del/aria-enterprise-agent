"""
ARIA-OS: time-series forecasting tool (Tier 1, BQML-free).

Closes the only real gap vs Google's `data-science` ADK sample (BQML's managed
ARIMA_PLUS / ARIMA_PLUS_XREG) WITHOUT BigQuery or Vertex — as a native,
server-side ADK tool. Statistical models only (statsmodels SARIMAX + Holt-Winters
ETS, with a pure-Python linear fallback); deep-learning (TFT) is intentionally out
of scope (it would need an async training job, not an inline tool).

Design mirrors `calc_sales_forecast` in calculations.py:
- `forecast_sales(...)` queries the tenant-scoped series via `get_supabase()` (RLS
  enforced by the request JWT), then delegates the math to `_fit_forecast`.
- `_fit_forecast(...)` is a PURE function (no DB, no LLM, no randomness) so the
  forecasting math is unit-testable in isolation and deterministic for a given
  input — same inputs ⇒ same output.

Cost/reliability: pure numerics, no network, no GCP. Multi-tenant safe because the
data is already RLS-scoped before it reaches the model.
"""
from __future__ import annotations

import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta

# NOTE: get_supabase is imported lazily inside forecast_sales (not at module load)
# so the PURE core (_fit_forecast/_linear_naive) is importable + unit-testable with
# only numpy/statsmodels — no DB/ADK stack required.

# ~80% prediction interval (one-sided z for 0.10 tail).
_Z80 = 1.2816
# A seasonal model needs at least this many full cycles of history.
_MIN_SEASONS = 2


def _linear_naive(values: list[float], horizon: int) -> tuple[str, list[float], list[float], list[float]]:
    """Dependency-free fallback: least-squares trend + residual-based interval.

    Used for very short series where SARIMAX/ETS can't fit. Pure Python (no numpy),
    so it always works even if the scientific stack is unavailable.
    """
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    fitted = [intercept + slope * x for x in xs]
    resid = [values[i] - fitted[i] for i in range(n)]
    sigma = (sum(r * r for r in resid) / max(1, n - 2)) ** 0.5 if n > 2 else 0.0
    point: list[float] = []
    lo: list[float] = []
    hi: list[float] = []
    for h in range(1, horizon + 1):
        v = max(0.0, intercept + slope * (n - 1 + h))
        point.append(v)
        lo.append(max(0.0, v - _Z80 * sigma))
        hi.append(v + _Z80 * sigma)
    return "linear-naive", point, lo, hi


def _fit_forecast(values, horizon: int, *, season: int = 7) -> dict:
    """Pure forecasting core. Project `horizon` steps from a chronological series.

    Picks the richest model the history supports:
      - SARIMAX(1,1,1)(1,0,1,season)  when there are >= 2 seasonal cycles,
      - Holt-Winters ETS(add,add)     when there is >= ~1 seasonal cycle,
      - linear-naive trend            otherwise.
    Returns 80% prediction intervals. Deterministic (no RNG); forecasts clipped at 0.

    Returns a dict with `status` in {"success","insufficient_history"} and, on
    success, `model_used`, `horizon`, `point[]`, `lo[]`, `hi[]`, `data_points`.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    horizon = max(1, min(int(horizon), 90))

    if n < 4:
        return {
            "status": "insufficient_history",
            "data_points": n,
            "message": "Se necesitan al menos 4 puntos históricos para proyectar.",
        }

    model_used: str | None = None
    point = lo = hi = None

    # Tier A — seasonal SARIMAX (closest analog to BQML ARIMA_PLUS).
    if n >= _MIN_SEASONS * season + 2:
        try:
            import numpy as np
            import statsmodels.api as sm

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = sm.tsa.SARIMAX(
                    np.asarray(vals, dtype=float),
                    order=(1, 1, 1),
                    seasonal_order=(1, 0, 1, season),
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit(disp=False)
                fc = res.get_forecast(horizon)
                mean = fc.predicted_mean
                ci = fc.conf_int(alpha=0.2)  # 80%
            point = [max(0.0, float(m)) for m in mean]
            lo = [max(0.0, float(ci[i, 0])) for i in range(horizon)]
            hi = [max(0.0, float(ci[i, 1])) for i in range(horizon)]
            model_used = f"SARIMAX(1,1,1)(1,0,1,{season})"
        except Exception:
            model_used = None

    # Tier B — Holt-Winters ETS.
    if model_used is None and n >= season + 2:
        try:
            import numpy as np
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = ExponentialSmoothing(
                    np.asarray(vals, dtype=float),
                    trend="add",
                    seasonal="add",
                    seasonal_periods=season,
                    initialization_method="estimated",
                ).fit()
                fcast = res.forecast(horizon)
                sigma = float(np.std(res.resid)) if len(res.resid) else 0.0
            point = [max(0.0, float(v)) for v in fcast]
            lo = [max(0.0, point[i] - _Z80 * sigma) for i in range(horizon)]
            hi = [point[i] + _Z80 * sigma for i in range(horizon)]
            model_used = f"ETS(add,add,{season})"
        except Exception:
            model_used = None

    # Tier C — pure-Python linear trend.
    if model_used is None:
        model_used, point, lo, hi = _linear_naive(vals, horizon)

    return {
        "status": "success",
        "model_used": model_used,
        "horizon": horizon,
        "point": [round(p, 2) for p in point],
        "lo": [round(x, 2) for x in lo],
        "hi": [round(x, 2) for x in hi],
        "data_points": n,
    }


def _backtest(values, season: int = 7, *, horizon: int = 14, folds: int = 3) -> dict:
    """Rolling-origin backtest of the SAME model `_fit_forecast` selects, so the
    reported accuracy describes the live forecast. PURE (reuses `_fit_forecast`),
    deterministic, best-effort.

    Anchors the most recent holdout at the end of the series and steps back by
    `horizon` per fold (expanding train window). Per scored fold:
        train = values[:t],  actual = values[t:t+horizon]
    Aggregates over all steps of all scored folds: MAPE (skips actual==0 steps),
    RMSE, interval_coverage (lo<=actual<=hi). Returns
    {status:"insufficient_history", folds:0} when no fold can be scored — the live
    forecast still succeeds; the backtest is informational only.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    horizon = max(1, int(horizon))
    folds = max(1, int(folds))
    min_train = max(season + 2, 4)  # enough for ETS/linear; SARIMAX kicks in at 2*season+2
    if n < min_train + horizon:
        return {"status": "insufficient_history", "folds": 0}

    sq_errs: list[float] = []
    pct_errs: list[float] = []
    covered = scored_steps = scored_folds = 0
    for k in range(folds):
        end = n - k * horizon
        t = end - horizon
        if t < min_train:
            break
        core = _fit_forecast(vals[:t], horizon, season=season)
        if core["status"] != "success":
            continue
        point, lo, hi = core["point"], core["lo"], core["hi"]
        scored_folds += 1
        for i in range(horizon):
            a, p = vals[t + i], point[i]
            sq_errs.append((a - p) ** 2)
            covered += 1 if lo[i] <= a <= hi[i] else 0
            scored_steps += 1
            if a > 0:
                pct_errs.append(abs(a - p) / a)

    if scored_steps == 0:
        return {"status": "insufficient_history", "folds": 0}

    return {
        "status": "success",
        "folds": scored_folds,
        "horizon": horizon,
        "mape": round(sum(pct_errs) / len(pct_errs) * 100, 1) if pct_errs else None,
        "rmse": round((sum(sq_errs) / len(sq_errs)) ** 0.5, 2),
        "interval_coverage": round(covered / scored_steps, 2),
        "n_points_scored": scored_steps,
    }


def _fit_forecast_xreg(values, exog, future_exog, horizon: int, *, season: int = 7) -> dict:
    """SARIMAX con un regresor EXÓGENO (p.ej. precio): demanda ~ precio (paridad con
    BQML ARIMA_PLUS_XREG). `exog` alinea 1:1 con `values`; `future_exog` tiene largo
    `horizon` (la senda asumida del driver — por defecto el último precio sostenido).
    Cae al `_fit_forecast` univariado si el exog no puede ayudar (serie corta, sin
    varianza, o sin statsmodels). PURO + determinístico; clippea en 0.
    """
    vals = [float(v) for v in values]
    ex = [float(x) for x in exog]
    fex = [float(x) for x in future_exog]
    n = len(vals)
    horizon = max(1, min(int(horizon), 90))
    if n < _MIN_SEASONS * season + 2 or len(ex) != n or len(fex) != horizon:
        return _fit_forecast(vals, horizon, season=season)
    mean_ex = sum(ex) / n
    if sum((x - mean_ex) ** 2 for x in ex) / n <= 1e-9:  # exog constante → no aporta
        return _fit_forecast(vals, horizon, season=season)
    try:
        import numpy as np
        import statsmodels.api as sm

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = sm.tsa.SARIMAX(
                np.asarray(vals, dtype=float),
                exog=np.asarray(ex, dtype=float).reshape(-1, 1),
                order=(1, 1, 1),
                seasonal_order=(1, 0, 1, season),
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)
            fc = res.get_forecast(horizon, exog=np.asarray(fex, dtype=float).reshape(-1, 1))
            mean = fc.predicted_mean
            ci = fc.conf_int(alpha=0.2)
        point = [max(0.0, float(m)) for m in mean]
        lo = [max(0.0, float(ci[i, 0])) for i in range(horizon)]
        hi = [max(0.0, float(ci[i, 1])) for i in range(horizon)]
    except Exception:
        return _fit_forecast(vals, horizon, season=season)

    return {
        "status": "success",
        "model_used": f"SARIMAX-XREG(1,1,1)(1,0,1,{season})",
        "horizon": horizon,
        "point": [round(p, 2) for p in point],
        "lo": [round(x, 2) for x in lo],
        "hi": [round(x, 2) for x in hi],
        "data_points": n,
        "exog_used": True,
    }


async def forecast_sales(product_name: str = "", forecast_days: int = 30) -> dict:
    """Proyecta la demanda/ventas futuras de un producto (o del total) con un
    modelo estadístico de series de tiempo (SARIMAX / Holt-Winters), incluyendo
    intervalos de confianza. Reemplaza a BQML sin depender de BigQuery.

    Usá esta herramienta cuando el usuario pida "pronóstico", "proyección",
    "forecast", "qué va a pasar con las ventas", "cuánto voy a vender", etc.

    Args:
        product_name: Nombre del producto a proyectar. Vacío ("") = serie total
            agregada de todos los productos.
        forecast_days: Días a proyectar hacia adelante (máximo 90).

    Returns:
        dict con la proyección lista para graficar como tarjeta:
        history[] y forecast[] (cada punto con value + intervalo lo/hi),
        model_used, seasonality, proyeccion_total y summary. En su defecto,
        status "no_data" o "insufficient_history" (nunca inventa datos).
    """
    forecast_days = max(1, min(int(forecast_days), 90))
    from src.infra.db import get_supabase

    client = await get_supabase()

    # Pull up to ~1 year so the model can see weekly/seasonal structure (more than
    # calc_sales_forecast's 30-day window). RLS-scoped to the tenant via the JWT.
    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    query = client.table("daily_inventory_ledger").select("sales_velocity, date, price")
    if product_name:
        query = query.ilike("product_name", f"%{product_name}%")
    # Fetch the MOST RECENT rows (desc): with many products a plain limit would
    # otherwise truncate to the OLDEST days and forecast off stale data. The by-date
    # aggregation below re-sorts ascending for the model.
    result = await query.gte("date", cutoff).order("date", desc=True).limit(800).execute()

    rows = result.data or []
    label = product_name or "Todos los productos"
    if not rows:
        return {
            "status": "no_data",
            "product": label,
            "message": f"No hay historial de ventas para '{label}'.",
        }

    # Aggregate velocity (sum) + price (avg) by date.
    by_date: dict[str, float] = defaultdict(float)
    price_by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        d = r.get("date")
        if d is None:
            continue
        key = str(d)[:10]
        by_date[key] += float(r.get("sales_velocity") or 0)
        p = r.get("price")
        if p is not None:
            price_by_date[key].append(float(p))

    dates = sorted(by_date)
    values = [by_date[d] for d in dates]

    # XREG: for a SPECIFIC product, use its daily price as an exogenous regressor
    # (demanda ~ precio). Only when price exists for every day AND it varied; else the
    # univariate model. Future price is held at the last observed value.
    core = None
    if product_name and all(price_by_date.get(d) for d in dates):
        price_series = [sum(price_by_date[d]) / len(price_by_date[d]) for d in dates]
        if max(price_series) - min(price_series) > 1e-6:
            core = _fit_forecast_xreg(
                values, price_series, [price_series[-1]] * forecast_days, forecast_days, season=7
            )
    if core is None:
        core = _fit_forecast(values, forecast_days, season=7)
    if core["status"] != "success":
        return {**core, "product": label}

    # Best-effort backtest of the SAME model on the same series → report accuracy.
    bt = _backtest(values, season=7)

    horizon = core["horizon"]
    # Future date labels continue from the last observed date.
    try:
        last = date.fromisoformat(dates[-1])
        f_labels = [(last + timedelta(days=i + 1)).isoformat() for i in range(horizon)]
    except Exception:
        f_labels = [f"+{i + 1}d" for i in range(horizon)]

    history = [{"label": dates[i], "value": round(values[i], 2)} for i in range(len(dates))][-90:]
    forecast = [
        {"label": f_labels[i], "value": core["point"][i], "lo": core["lo"][i], "hi": core["hi"][i]}
        for i in range(horizon)
    ]
    total = round(sum(core["point"]), 2)
    summary = (
        f"Proyección a {horizon} días para '{label}': total ≈ {total} "
        f"(modelo {core['model_used']}, {core['data_points']} puntos históricos)."
    )
    if bt.get("status") == "success" and bt.get("mape") is not None:
        weeks = max(1, (bt["horizon"] * bt["folds"]) // 7)
        summary += (
            f" Precisión (backtest): ~{bt['mape']:.1f}% de error MAPE sobre las "
            f"últimas ~{weeks} semana(s), con cobertura del intervalo del "
            f"{int(bt['interval_coverage'] * 100)}%."
        )
    return {
        "status": "success",
        "product": label,
        "model_used": core["model_used"],
        "seasonality": "weekly" if "7)" in core["model_used"] else "none",
        "horizon_days": horizon,
        "data_points": core["data_points"],
        "history": history,
        "forecast": forecast,
        "proyeccion_total": total,
        "backtest": bt,
        "summary": summary,
    }
