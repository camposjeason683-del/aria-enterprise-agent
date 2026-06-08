"""Unit tests for the CSV/Sheets importer (pure parts): header mapping, CSV parsing,
records→synthetic-orders, deterministic order ids, Google-Sheets URL handling, and the
robust file parser (xlsx, auto delimiter/encoding, junk headers, duplicate detection).
"""
import io

from src.tools.importers import (
    _sheet_csv_url, _synthetic_order_id, detect_duplicate_products, infer_mapping,
    parse_csv, parse_table, records_to_orders,
)


# ── robust file parsing (parse_table) ────────────────────────────────────────
def test_parse_table_semicolon_and_spanish_headers():
    # The typical LatAm Excel export: semicolon-delimited, accented Spanish headers.
    raw = "Fecha de Venta;Producto;Cantidad;Precio\n2026-05-01;Tomate;3;2,5\n".encode("utf-8")
    recs, headers, m = parse_table(raw, "ventas.csv")
    assert m == {"date": "Fecha de Venta", "product_name": "Producto",
                 "quantity": "Cantidad", "price": "Precio"}
    assert recs[0]["product_name"] == "Tomate" and recs[0]["price"] == "2,5"


def test_parse_table_latin1_encoding():
    recs, _, _ = parse_table("fecha,producto,cantidad\n2026-05-01,Café,2\n".encode("latin-1"), "x.csv")
    assert recs[0]["product_name"] == "Café"


def test_parse_table_xlsx():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["fecha", "producto", "cantidad", "precio"])
    ws.append(["2026-05-01", "Leche", 4, 1.5])
    buf = io.BytesIO()
    wb.save(buf)
    recs, _, _ = parse_table(buf.getvalue(), "ventas.xlsx")
    assert recs[0] == {"date": "2026-05-01", "product_name": "Leche",
                       "quantity": "4", "price": "1.5"}


def test_parse_table_skips_junk_header_rows():
    raw = "Reporte de ventas\nGenerado hoy\nfecha,producto,cantidad\n2026-05-01,Pan,7\n".encode("utf-8")
    recs, headers, _ = parse_table(raw, "r.csv")
    assert headers == ["fecha", "producto", "cantidad"]
    assert recs[0]["product_name"] == "Pan"


def test_parse_table_explicit_mapping_override():
    raw = "f,p,q\n2026-05-01,Pan,7\n".encode("utf-8")
    recs, _, m = parse_table(raw, "r.csv", {"date": "f", "product_name": "p", "quantity": "q"})
    assert recs[0] == {"date": "2026-05-01", "product_name": "Pan", "quantity": "7"}
    assert m["date"] == "f"


def test_detect_duplicate_products():
    dups = detect_duplicate_products(
        [{"product_name": "Coca Cola"}, {"product_name": "Coca-Cola"}, {"product_name": "Pan"}])
    assert dups == [["Coca Cola", "Coca-Cola"]]
    assert detect_duplicate_products([{"product_name": "A"}, {"product_name": "B"}]) == []


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
