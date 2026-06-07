"""Unit tests for the pure ETL core `_aggregate` (orders → daily ledger rows).

The math (aggregation, status filtering, product-id resolution, price weighting,
stock preservation) is tested in isolation without touching the DB — mirroring the
repo convention (test_forecasting.py / test_anomaly.py). The DB I/O wrapper
`compile_ledger_for_tenant` is exercised in the live 2-tenant smoke, not here.
"""
from src.tools.ledger_etl import _aggregate, _norm, _num, _product_id


def _order(status: str, date: str, items: list) -> dict:
    return {"order_id": 1, "date_created": f"{date}T12:00:00Z", "status": status,
            "line_items": items}


def _item(name, qty, price=None) -> dict:
    d = {"product_name": name, "qty": qty}
    if price is not None:
        d["price"] = price
    return d


def _agg(orders, **kw):
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("existing_by_name", {})
    kw.setdefault("existing_stock", {})
    return _aggregate(orders, **kw)


# ── aggregation ──────────────────────────────────────────────────────────────
def test_sums_qty_per_product_per_day():
    orders = [
        _order("completed", "2026-01-01", [_item("Tomate", 3, 2.0), _item("Queso", 1, 5.0)]),
        _order("processing", "2026-01-01", [_item("Tomate", 2, 2.0)]),
    ]
    rows, _ = _agg(orders)
    by = {(r["product_name"], r["date"]): r for r in rows}
    assert by[("Tomate", "2026-01-01")]["sales_velocity"] == 5.0   # 3 + 2
    assert by[("Queso", "2026-01-01")]["sales_velocity"] == 1.0


def test_filters_non_sold_statuses():
    orders = [
        _order("completed", "2026-01-01", [_item("A", 5, 1.0)]),
        _order("cancelled", "2026-01-01", [_item("A", 100, 1.0)]),
        _order("failed", "2026-01-01", [_item("A", 100, 1.0)]),
        _order("refunded", "2026-01-01", [_item("A", 100, 1.0)]),
    ]
    rows, _ = _agg(orders)
    assert len(rows) == 1 and rows[0]["sales_velocity"] == 5.0  # only the completed one


def test_weighted_average_price():
    # 3 @ 2.0  +  1 @ 6.0  →  (6 + 6) / 4 = 3.0 per unit
    rows, _ = _agg([_order("completed", "2026-01-01", [_item("X", 3, 2.0), _item("X", 1, 6.0)])])
    assert rows[0]["sales_velocity"] == 4.0
    assert rows[0]["price"] == 3.0


def test_price_is_none_when_no_priced_lines():
    rows, _ = _agg([_order("completed", "2026-01-01", [_item("X", 4)])])  # no price
    assert rows[0]["sales_velocity"] == 4.0 and rows[0]["price"] is None


def test_is_deterministic():
    orders = [_order("completed", "2026-01-01", [_item("A", 2, 1.0), _item("B", 3, 2.5)])]
    assert _agg(orders) == _agg(orders)  # no RNG, no wall-clock


# ── product-id resolution ────────────────────────────────────────────────────
def test_reuses_existing_product_id_and_mints_new():
    existing = {"tomate": "EXISTING-ID"}
    orders = [_order("completed", "2026-01-01", [_item("Tomate", 1, 1.0), _item("Cebolla", 1, 1.0)])]
    rows, new = _agg(orders, existing_by_name=existing)
    by = {r["product_name"]: r for r in rows}
    assert by["Tomate"]["product_id"] == "EXISTING-ID"                 # reused
    assert by["Cebolla"]["product_id"] == _product_id("t1", "cebolla")  # deterministic mint
    assert [p["name"] for p in new] == ["Cebolla"]                     # only the unknown name


def test_new_product_carries_weighted_price():
    rows, new = _agg([_order("completed", "2026-01-01", [_item("A", 2, 3.0)])])
    assert len(new) == 1
    assert new[0] == {"tenant_id": "t1", "id": _product_id("t1", "a"), "name": "A", "price": 3.0}


# ── data-quality guards (the $0-margin / id-mismatch class of bugs) ───────────
def test_skips_malformed_line_items():
    orders = [_order("completed", "2026-01-01", [
        "not-a-dict",                                   # not a dict
        {"qty": 5},                                     # no name
        {"product_name": "", "qty": 5},                 # empty name
        {"product_name": "A", "qty": "abc"},            # non-numeric qty
        {"product_name": "A", "qty": -3},               # non-positive qty
        {"product_name": "A", "qty": 2, "price": 1.5},  # the only valid line
    ])]
    rows, _ = _agg(orders)
    assert len(rows) == 1 and rows[0]["product_name"] == "A" and rows[0]["sales_velocity"] == 2.0


def test_skips_orders_with_bad_dates_or_items():
    orders = [
        {"status": "completed", "date_created": None, "line_items": [_item("A", 5, 1.0)]},
        {"status": "completed", "date_created": "2026", "line_items": [_item("A", 5, 1.0)]},
        {"status": "completed", "date_created": "2026-01-01T00:00:00Z", "line_items": "nope"},
    ]
    rows, _ = _agg(orders)
    assert rows == []


# ── stock preservation / override ────────────────────────────────────────────
def test_stock_unknown_is_none_not_zero():
    # Honest: unknown stock stays NULL, never a misleading 0 (which the sweep would
    # coerce into a false "critical stock" alarm).
    rows, _ = _agg([_order("completed", "2026-01-01", [_item("A", 1, 1.0)])])
    assert rows[0]["stock_end_of_day"] is None


def test_preserves_existing_stock_and_stock_map_overrides_latest_date_only():
    orders = [
        _order("completed", "2026-01-01", [_item("A", 1, 1.0)]),
        _order("completed", "2026-01-02", [_item("A", 1, 1.0)]),  # latest date
    ]
    pid = _product_id("t1", "a")
    existing_stock = {(pid, "2026-01-01"): 50, (pid, "2026-01-02"): 40}

    rows, _ = _agg(orders, existing_stock=existing_stock)
    by = {r["date"]: r for r in rows}
    assert by["2026-01-01"]["stock_end_of_day"] == 50  # preserved
    assert by["2026-01-02"]["stock_end_of_day"] == 40  # preserved

    rows2, _ = _agg(orders, existing_stock=existing_stock, stock_map={"a": 7})
    by2 = {r["date"]: r for r in rows2}
    assert by2["2026-01-01"]["stock_end_of_day"] == 50  # not latest → preserved
    assert by2["2026-01-02"]["stock_end_of_day"] == 7   # latest → fresh stock_map


# ── helpers + edge cases ─────────────────────────────────────────────────────
def test_empty_orders_yield_nothing():
    rows, new = _agg([])
    assert rows == [] and new == []


def test_norm_collapses_and_lowercases():
    assert _norm("  Tomate   Cherry ") == "tomate cherry"
    assert _norm("TOMATE") == "tomate"
    assert _norm(None) == ""


def test_product_id_is_deterministic_and_tenant_scoped():
    assert _product_id("t1", "a") == _product_id("t1", "a")
    assert _product_id("t1", "a") != _product_id("t2", "a")


def test_num_coercion_guards():
    assert _num("3.5") == 3.5
    assert _num(None) is None
    assert _num("abc") is None
    assert _num(float("nan")) is None
    assert _num(float("inf")) is None
