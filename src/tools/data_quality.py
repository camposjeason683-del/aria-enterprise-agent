"""Data-quality validation for inbound business records (CSV / Sheets / WooCommerce).

The prototype's latent bugs ($0 margins, id mismatches, NaN velocities) all traced to
dirty data entering silently. This is the guard at the door: pure validators that turn
a raw record into either a normalised record or a precise list of errors — shared by the
CSV/Sheets importer (M2) and reused conceptually by the ETL (M1).

A canonical sales record is: ``{date, product_name, quantity, price?, status?}``.
- ``date``         required, parseable → ``YYYY-MM-DD``.
- ``product_name`` required, non-empty.
- ``quantity``     required, numeric, > 0.
- ``price``        optional, numeric, ≥ 0 (missing/0 → warning, since margins need it).
- ``status``       optional; defaults to ``completed``.

Pure: no I/O, no RNG, no wall-clock. ``parse_date`` accepts ISO-ish strings only
(no ``datetime.now``-style relative parsing) to stay deterministic.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")  # DD/MM/YYYY (LatAm default)
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def coerce_number(v: Any) -> Optional[float]:
    """Best-effort numeric coercion; None on non-numeric / NaN / inf. Handles $, %, spaces,
    and BOTH decimal conventions: US (``1,234.56``) and LatAm/EU (``1.234,56`` · ``2,5``) —
    essential for semicolon-delimited Excel exports where the decimal is a comma."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = str(v or "").strip().replace("$", "").replace("%", "").replace(" ", "")
        if not s:
            return None
        has_dot, has_comma = "." in s, "," in s
        if has_dot and has_comma:
            if s.rfind(",") > s.rfind("."):            # 1.234,56 → EU (dot=thousands)
                s = s.replace(".", "").replace(",", ".")
            else:                                       # 1,234.56 → US (comma=thousands)
                s = s.replace(",", "")
        elif has_comma:
            if re.match(r"^-?\d{1,3}(,\d{3})+$", s):     # 1,000 / 12,345,678 → thousands
                s = s.replace(",", "")
            else:                                        # 2,5 → comma-decimal
                s = s.replace(",", ".")
        try:
            f = float(s)
        except ValueError:
            return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def parse_date(v: Any) -> Optional[str]:
    """Normalise a date to ``YYYY-MM-DD``. Accepts ``YYYY-MM-DD[...]`` and ``DD/MM/YYYY``.
    Returns None if unparseable or calendar-invalid. Deterministic (no 'today')."""
    s = str(v or "").strip()
    if not s:
        return None
    y = mo = d = None
    m = _DATE_RE.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _SLASH_RE.match(s)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y is None or not (1 <= mo <= 12) or not (1 <= d <= _MONTH_DAYS[mo - 1]):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def validate_record(rec: dict) -> tuple[Optional[dict], list[str], list[str]]:
    """Validate one canonical record → (normalised | None, errors, warnings).

    ``normalised`` is None iff there is at least one error. Warnings never block."""
    errors: list[str] = []
    warnings: list[str] = []

    name = str(rec.get("product_name") or "").strip()
    if not name:
        errors.append("product_name vacío o ausente")

    date = parse_date(rec.get("date"))
    if date is None:
        errors.append(f"date inválida o ausente: {rec.get('date')!r}")

    qty = coerce_number(rec.get("quantity"))
    if qty is None:
        errors.append(f"quantity no numérica: {rec.get('quantity')!r}")
    elif qty <= 0:
        errors.append(f"quantity debe ser > 0: {qty}")

    price = coerce_number(rec.get("price"))
    if rec.get("price") not in (None, "") and price is None:
        errors.append(f"price no numérico: {rec.get('price')!r}")
    elif price is not None and price < 0:
        errors.append(f"price negativo: {price}")
    elif price is None or price == 0:
        warnings.append("price ausente o 0 — el margen no podrá calcularse para esta fila")

    if errors:
        return None, errors, warnings

    return {
        "date": date,
        "product_name": name,
        "quantity": qty,
        "price": price,                       # may be None → margin unknown (honest)
        "status": str(rec.get("status") or "completed").strip().lower(),
    }, errors, warnings


def validate_records(records: list[dict]) -> dict:
    """Validate a batch → {valid, rejected, warnings, stats}. Order-stable."""
    valid: list[dict] = []
    rejected: list[dict] = []
    warned: list[dict] = []
    for i, rec in enumerate(records):
        norm, errors, warnings = validate_record(rec)
        if norm is None:
            rejected.append({"index": i, "errors": errors, "raw": rec})
        else:
            valid.append(norm)
            if warnings:
                warned.append({"index": i, "warnings": warnings})
    return {
        "valid": valid,
        "rejected": rejected,
        "warnings": warned,
        "stats": {
            "total": len(records),
            "ok": len(valid),
            "rejected": len(rejected),
            "warned": len(warned),
        },
    }
