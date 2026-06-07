# spec: detección autónoma de anomalías (Fase 4)
"""Unit tests for the PURE anomaly detectors (_cusum, _scan_series). No DB."""
import math

from src.tools.anomaly import _cusum, _scan_series


def _flat(n: int, v: float = 10.0) -> list[float]:
    return [v] * n


def _seasonal(n: int) -> list[float]:
    return [10.0 + 0.1 * i + 3.0 * math.sin(2 * math.pi * i / 7) for i in range(n)]


def test_cusum_flags_regime_shift():
    series = _flat(30, 10.0) + _flat(30, 30.0)  # clear level shift
    assert _cusum(series) is not None  # a regime change is detected somewhere


def test_cusum_none_on_stationary():
    assert _cusum(_flat(60, 10.0)) is None


def test_cusum_short_series_none():
    assert _cusum([1.0, 2.0, 3.0]) is None


def test_scan_series_flags_spike():
    s = _seasonal(60)
    s[-1] = s[-1] + 100.0  # big spike on the last day
    findings = _scan_series("X", s)
    assert any(f["tipo"].startswith("pico") for f in findings)


def test_scan_series_flags_drop():
    s = _seasonal(60)
    s[-1] = 0.0  # collapse on the last day
    findings = _scan_series("X", s)
    assert any("caída" in f["tipo"] for f in findings)


def test_scan_series_flat_has_no_forecast_residual_anomaly():
    # Perfectly flat series: the last point equals the prediction → no pico/caída
    # de demanda (zero residual → exact interval, the in-pattern point is inside).
    findings = _scan_series("X", _flat(60, 10.0))
    assert not any("demanda" in f["tipo"] for f in findings)


def test_scan_series_short_returns_empty():
    assert _scan_series("X", [1.0] * 5) == []
