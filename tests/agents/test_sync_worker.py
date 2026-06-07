"""Unit tests for the pure sync helpers (WooCommerce → cache row / stock map).

The agent wrapper (network + DB) is exercised live; the mapping logic — which is
exactly where the prior cache-write bug lived (id vs order_id, phantom `currency`,
missing tenant_id) — is tested here in isolation.
"""
from src.agents.sync_worker import _order_to_cache_row, _wc_products_to_stock_map


def test_order_to_cache_row_maps_correct_columns():
    o = {
        "id": 5012, "status": "completed", "total": "42.50", "currency": "USD",
        "date_created": "2026-03-04T11:00:00",
        "billing": {"first_name": "Ana", "last_name": "Pérez"},
        "line_items": [{"name": "Tomate", "quantity": 3, "price": "2.0"}],
    }
    row = _order_to_cache_row(o, "tenant-1")
    assert row["order_id"] == 5012          # order_id, NOT id (the bug)
    assert "id" not in row                   # never write the UUID PK
    assert "currency" not in row             # phantom column dropped
    assert row["tenant_id"] == "tenant-1"    # tenant_id set (was missing)
    assert row["customer_name"] == "Ana Pérez"
    assert row["status"] == "completed" and row["total"] == "42.50"
    assert row["line_items"] == [{"name": "Tomate", "quantity": 3, "price": "2.0"}]


def test_order_to_cache_row_handles_missing_billing_and_items():
    row = _order_to_cache_row({"id": 1}, "t1")
    assert row["customer_name"] is None and row["line_items"] == [] and row["order_id"] == 1


def test_wc_products_to_stock_map_normalises_and_filters():
    products = [
        {"name": "  Tomate Cherry ", "stock_quantity": 40},
        {"name": "Queso", "stock_quantity": 0},          # 0 is a real managed value → kept
        {"name": "Pan", "stock_quantity": None},          # not managed → excluded (stays NULL)
        {"name": "", "stock_quantity": 5},                # no name → skip
        "not-a-dict",
        {"stock_quantity": 9},                            # no name → skip
    ]
    sm = _wc_products_to_stock_map(products)
    assert sm == {"tomate cherry": 40.0, "queso": 0.0}


def test_wc_products_to_stock_map_skips_non_numeric_stock():
    assert _wc_products_to_stock_map([{"name": "X", "stock_quantity": "abc"}]) == {}


def test_wc_products_to_stock_map_empty():
    assert _wc_products_to_stock_map([]) == {} and _wc_products_to_stock_map(None) == {}
