# spec: specs/data-science/forecasting.spec.md
"""Unit tests for the pure forecasting core `_fit_forecast`.

Mirrors the repo convention (tests/test_tools.py): the math is tested in isolation,
without touching the DB. The `forecast_sales` tool = DB query (RLS) + this core;
the query layer is exercised in the live smoke test, not here.
"""
import math

from src.tools.forecasting import _backtest, _fit_forecast, _fit_forecast_xreg, _linear_naive


def _seasonal_series(n: int) -> list[float]:
    """Deterministic daily series: linear trend + weekly seasonality (no RNG)."""
    return [10.0 + 0.1 * i + 3.0 * math.sin(2 * math.pi * i / 7) for i in range(n)]


def _assert_intervals_ok(result: dict, horizon: int) -> None:
    assert result["status"] == "success"
    assert result["horizon"] == horizon
    assert len(result["point"]) == horizon
    assert len(result["lo"]) == horizon
    assert len(result["hi"]) == horizon
    for i in range(horizon):
        # I2: lo <= value <= hi ; I3: non-negative
        assert result["lo"][i] <= result["point"][i] <= result["hi"][i]
        assert result["point"][i] >= 0.0
        assert result["lo"][i] >= 0.0


def test_long_seasonal_series_uses_a_real_model():
    # >= 2*7+2 points -> seasonal model (SARIMAX or ETS), not the linear fallback.
    result = _fit_forecast(_seasonal_series(120), 30, season=7)
    _assert_intervals_ok(result, 30)
    assert result["model_used"] != "linear-naive"
    assert result["data_points"] == 120


def test_short_series_falls_back_to_linear_naive():
    # 8 points: too few for ETS (needs >=9) or SARIMAX (needs >=16) -> linear-naive.
    result = _fit_forecast(_seasonal_series(8), 14, season=7)
    _assert_intervals_ok(result, 14)
    assert result["model_used"] == "linear-naive"


def test_insufficient_history():
    result = _fit_forecast([1.0, 2.0, 3.0], 10, season=7)
    assert result["status"] == "insufficient_history"
    assert result["data_points"] == 3


def test_horizon_is_clamped_to_90():
    result = _fit_forecast(_seasonal_series(120), 999, season=7)
    assert result["horizon"] == 90
    assert len(result["point"]) == 90


def test_determinism_same_input_same_output():
    series = _seasonal_series(90)
    a = _fit_forecast(series, 30, season=7)
    b = _fit_forecast(series, 30, season=7)
    assert a == b  # I5: no RNG, deep-equal


def test_forecasts_are_non_negative_even_with_declining_trend():
    # Strongly declining series -> point/lo must clip at 0, never negative.
    declining = [max(0.0, 100.0 - 1.5 * i) for i in range(120)]
    result = _fit_forecast(declining, 60, season=7)
    _assert_intervals_ok(result, 60)


def test_linear_naive_core_is_pure_and_bounded():
    model, point, lo, hi = _linear_naive([1.0, 2.0, 3.0, 4.0, 5.0], 5)
    assert model == "linear-naive"
    assert len(point) == len(lo) == len(hi) == 5
    for i in range(5):
        assert lo[i] <= point[i] <= hi[i]
        assert point[i] >= 0.0


# ── _backtest (rolling-origin accuracy) ──────────────────────────────────────
def test_backtest_on_seasonal_series_reports_reasonable_metrics():
    bt = _backtest(_seasonal_series(120))
    assert bt["status"] == "success"
    assert bt["folds"] >= 1
    assert isinstance(bt["mape"], float) and bt["mape"] >= 0.0
    assert bt["mape"] < 40.0  # clean synthetic series → low error
    assert isinstance(bt["rmse"], float) and bt["rmse"] >= 0.0
    assert 0.0 <= bt["interval_coverage"] <= 1.0
    assert bt["n_points_scored"] > 0


def test_backtest_insufficient_history():
    bt = _backtest(_seasonal_series(10))  # < min_train(9) + horizon(14)
    assert bt["status"] == "insufficient_history"
    assert bt["folds"] == 0


def test_backtest_is_deterministic():
    series = _seasonal_series(120)
    assert _backtest(series) == _backtest(series)  # I5: no RNG


def test_backtest_keys_present_and_typed():
    bt = _backtest(_seasonal_series(120))
    assert set(bt) == {
        "status", "folds", "horizon", "mape", "rmse",
        "interval_coverage", "n_points_scored",
    }


def test_backtest_handles_zero_actuals_without_crash():
    # Holdout steps with actual==0 are skipped for MAPE (no ZeroDivisionError).
    series = [0.0 if i % 4 == 0 else 5.0 + 0.1 * i for i in range(60)]
    bt = _backtest(series)
    assert bt["status"] in ("success", "insufficient_history")


# ── _fit_forecast_xreg (price as exogenous regressor) ────────────────────────
def test_xreg_falls_back_when_exog_is_constant():
    r = _fit_forecast_xreg(_seasonal_series(60), [5.0] * 60, [5.0] * 30, 30)
    assert r["status"] == "success"
    assert "XREG" not in r["model_used"]  # constant exog → univariate fallback


def test_xreg_falls_back_on_length_mismatch():
    r = _fit_forecast_xreg(_seasonal_series(60), [5.0] * 59, [5.0] * 30, 30)
    assert "XREG" not in r["model_used"]


def test_xreg_engages_and_bounds_hold_when_price_varies():
    # demand = 10 + 1.5*price + weekly seasonality; price alternates 3 vs 8.
    price = [3.0 if (i // 7) % 2 == 0 else 8.0 for i in range(80)]
    vals = [max(0.0, 10.0 + 1.5 * price[i] + 2.0 * math.sin(2 * math.pi * i / 7)) for i in range(80)]
    r = _fit_forecast_xreg(vals, price, [price[-1]] * 20, 20)
    assert r["status"] == "success"
    assert "XREG" in r["model_used"]  # varying exog → the price-aware model engages
    for i in range(20):
        assert r["lo"][i] <= r["point"][i] <= r["hi"][i]
        assert r["point"][i] >= 0.0
