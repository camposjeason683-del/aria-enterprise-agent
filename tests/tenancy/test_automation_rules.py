# spec: motor de reglas de automatización (Fase 3)
"""Truth-table unit tests for the PURE rule-matching core (no DB)."""
from src.tools.automation import _compare, _evaluate


def test_compare_operators_and_boundaries():
    assert _compare(90, ">", 80) is True
    assert _compare(80, ">", 80) is False          # boundary: strict
    assert _compare(80, ">=", 80) is True           # boundary: inclusive
    assert _compare(70, "<", 80) is True
    assert _compare(80, "<=", 80) is True
    assert _compare(80, "==", 80) is True
    assert _compare(5, "≈", 1) is False             # unknown op → never fires


def test_evaluate_fires_only_matching_rules():
    rules = [
        {"name": "high risk", "metric": "stockout_risk_max", "op": ">", "threshold": 80},
        {"name": "ok margin", "metric": "net_margin_pct", "op": "<", "threshold": 10},
        {"name": "missing", "metric": "unknown_x", "op": ">", "threshold": 0},
    ]
    metrics = {"stockout_risk_max": 92, "net_margin_pct": 15, "unknown_x": None}
    fired = _evaluate(rules, metrics)
    assert [r["name"] for r in fired] == ["high risk"]  # only risk crosses; margin doesn't; missing skipped


def test_evaluate_skips_none_metric_and_bad_threshold():
    assert _evaluate([{"name": "y", "metric": "m", "op": ">", "threshold": 1}], {"m": None}) == []
    assert _evaluate([{"name": "x", "metric": "m", "op": ">", "threshold": "NaNish"}], {"m": 5}) == []


def test_evaluate_boundary_inclusive_vs_strict():
    rule_ge = [{"name": "b", "metric": "m", "op": ">=", "threshold": 80}]
    rule_gt = [{"name": "b", "metric": "m", "op": ">", "threshold": 80}]
    assert _evaluate(rule_ge, {"m": 80}) == rule_ge   # >= 80 fires at 80
    assert _evaluate(rule_gt, {"m": 80}) == []          # > 80 does not
