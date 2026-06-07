"""Unit tests for the CSV/Sheets importer (pure parts): header mapping, CSV parsing,
records→synthetic-orders, deterministic order ids, and Google-Sheets URL handling.
"""
from src.tools.importers import (
    _sheet_csv_url, _synthetic_order_id, infer_mapping, parse_csv, records_to_orders,
)


def test_infer_mapping_matches_aliases_including_spanish():
    mp = infer_mapping(["Fecha", "Producto", "Cantidad", "Precio", "Estado"])
    assert mp == {"date": "Fecha", "product_name": "Producto", "quantity": "Cantidad",
                  "price": "Precio", "status": "Estado"}


def test_parse_csv_uses_inferred_mapping():
    text = "fecha,producto,cantidad,precio\n2026-03-01,Tomate,3,2.5\n2026-03-01,Queso,1,5\n"
    records, mapping = parse_csv(text)
    assert mapping["product_name"] == "producto"
    assert records[0] == {"date": "2026-03-01", "product_name": "Tomate",
                          "quantity": "3", "price": "2.5"}
    assert len(records) == 2


def test_parse_csv_explicit_mapping():
    text = "d,p,q\n2026-03-01,Pan,7\n"
    records, _ = parse_csv(text, {"date": "d", "product_name": "p", "quantity": "q"})
    assert records[0] == {"date": "2026-03-01", "product_name": "Pan", "quantity": "7"}


def test_records_to_orders_shape_and_total():
    recs = [{"date": "2026-03-01", "product_name": "Tomate", "quantity": 3.0, "price": 2.0}]
    rows = records_to_orders(recs, "t1")
    assert rows[0]["tenant_id"] == "t1"
    assert rows[0]["total"] == 6.0
    assert rows[0]["date_created"] == "2026-03-01T12:00:00Z"
    assert rows[0]["line_items"] == [{"product_name": "Tomate", "qty": 3.0, "price": 2.0}]
    assert isinstance(rows[0]["order_id"], int)


def test_records_to_orders_total_none_when_price_none():
    rows = records_to_orders(
        [{"date": "2026-03-01", "product_name": "X", "quantity": 2.0, "price": None}], "t1")
    assert rows[0]["total"] is None


def test_duplicate_records_get_distinct_order_ids():
    rec = {"date": "2026-03-01", "product_name": "A", "quantity": 1.0, "price": 1.0}
    rows = records_to_orders([dict(rec), dict(rec)], "t1")
    assert rows[0]["order_id"] != rows[1]["order_id"]   # occurrence disambiguates


def test_synthetic_order_id_is_deterministic_and_bigint():
    rec = {"date": "2026-03-01", "product_name": "A", "quantity": 1.0, "price": 1.0}
    a = _synthetic_order_id(rec, 0)
    b = _synthetic_order_id(rec, 0)
    assert a == b and 0 < a < 2**63   # stable across runs, fits BIGINT


def test_sheet_csv_url_extraction():
    u = _sheet_csv_url("https://docs.google.com/spreadsheets/d/ABC123_xy/edit#gid=42")
    assert u == "https://docs.google.com/spreadsheets/d/ABC123_xy/export?format=csv&gid=42"
    assert _sheet_csv_url("https://example.com/not-a-sheet") is None
