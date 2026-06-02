# spec: specs/data-science/forecasting.spec.md
"""Unit tests for the pure forecasting core `_fit_forecast`.

Mirrors the repo convention (tests/test_tools.py): the math is tested in isolation,
without touching the DB. The `forecast_sales` tool = DB query (RLS) + this core;
the query layer is exercised in the live smoke test, not here.
"""
import math

from src.tools.forecasting import _fit_forecast, _linear_naive


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
