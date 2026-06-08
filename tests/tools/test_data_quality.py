"""Unit tests for the data-quality validators — the guard the prototype never had
($0 margins, NaN velocities, unparseable dates entered silently). Pure, no I/O.
"""
from src.tools.data_quality import (
    coerce_number, parse_date, validate_record, validate_records,
)


def test_coerce_number_handles_formats_and_junk():
    assert coerce_number(5) == 5.0
    assert coerce_number("3.50") == 3.5
    assert coerce_number("$1,250.00") == 1250.0
    assert coerce_number("  42 ") == 42.0
    assert coerce_number(None) is None
    assert coerce_number("") is None
    assert coerce_number("abc") is None
    assert coerce_number(True) is None          # bool is not a quantity
    assert coerce_number(float("nan")) is None
    assert coerce_number(float("inf")) is None


def test_coerce_number_locale_decimals():
    # The comma-decimal case (LatAm/EU) — essential for semicolon-delimited Excel exports.
    assert coerce_number("2,5") == 2.5            # comma-decimal
    assert coerce_number("1.234,56") == 1234.56   # EU: dot thousands, comma decimal
    assert coerce_number("1,234.56") == 1234.56   # US: comma thousands, dot decimal
    assert coerce_number("1,000") == 1000.0       # comma thousands
    assert coerce_number("12,345,678") == 12345678.0


def test_parse_date_formats_and_invalids():
    assert parse_date("2026-03-01") == "2026-03-01"
    assert parse_date("2026-3-1") == "2026-03-01"
    assert parse_date("2026-03-01T10:00:00Z") == "2026-03-01"
    assert parse_date("01/03/2026") == "2026-03-01"      # DD/MM/YYYY
    assert parse_date("2026-13-01") is None              # bad month
    assert parse_date("2026-02-30") is None              # bad day
    assert parse_date("nope") is None
    assert parse_date("") is None


def test_validate_record_valid():
    norm, errors, warnings = validate_record(
        {"date": "01/03/2026", "product_name": " Tomate ", "quantity": "3", "price": "2.5"})
    assert errors == [] and warnings == []
    assert norm == {"date": "2026-03-01", "product_name": "Tomate", "quantity": 3.0,
                    "price": 2.5, "status": "completed"}


def test_validate_record_collects_errors():
    norm, errors, _ = validate_record({"date": "bad", "product_name": "", "quantity": "x"})
    assert norm is None
    assert any("product_name" in e for e in errors)
    assert any("date" in e for e in errors)
    assert any("quantity" in e for e in errors)


def test_validate_record_quantity_must_be_positive():
    norm, errors, _ = validate_record({"date": "2026-03-01", "product_name": "A", "quantity": 0})
    assert norm is None and any("> 0" in e for e in errors)


def test_validate_record_negative_price_is_error_missing_price_is_warning():
    norm, errors, _ = validate_record(
        {"date": "2026-03-01", "product_name": "A", "quantity": 2, "price": -1})
    assert norm is None and any("negativo" in e for e in errors)

    norm2, errors2, warnings2 = validate_record(
        {"date": "2026-03-01", "product_name": "A", "quantity": 2})  # no price
    assert norm2 is not None and norm2["price"] is None
    assert errors2 == [] and any("margen" in w for w in warnings2)


def test_validate_records_batch_partitions():
    report = validate_records([
        {"date": "2026-03-01", "product_name": "A", "quantity": 2, "price": 1.0},   # ok
        {"date": "bad", "product_name": "B", "quantity": 1, "price": 1.0},           # rejected
        {"date": "2026-03-02", "product_name": "C", "quantity": 1},                  # ok + warning
    ])
    assert report["stats"] == {"total": 3, "ok": 2, "rejected": 1, "warned": 1}
    assert report["rejected"][0]["index"] == 1
    assert report["warnings"][0]["index"] == 2
