"""CSV / Excel / Google-Sheets ingestion for tenants without WooCommerce.

Robust file parsing (any real, messy export) feeding the SAME keystone path as
WooCommerce: map a user's columns → the canonical sales record, validate with
data_quality, synthesise ``wc_orders_cache`` rows and call ``compile_ledger_for_tenant``.

Robustness (no new deps — pandas/openpyxl/charset_normalizer are already installed):
- ``.xlsx``/``.xls`` via ``pandas.read_excel``; CSV/TXT via ``pandas.read_csv``.
- Auto delimiter (``,`` / ``;`` / tab) via ``csv.Sniffer`` — the typical LatAm Excel
  export is semicolon-delimited and would otherwise parse as one column.
- Auto encoding (UTF-8 / Latin-1 / …) via ``charset_normalizer``.
- Junk title rows before the header are skipped (header-row detection by mapping score).

Idempotent re-import: each record gets a DETERMINISTIC synthetic ``order_id`` (stable hash
of its content + occurrence), so re-uploading the same file upserts in place (0011).
"""
from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from typing import Optional

from src.infra.db import get_supabase
from src.infra.tenant_context import current
from src.tools.data_quality import validate_records
from src.tools.ledger_etl import _norm, compile_ledger_for_tenant

# Canonical field → header aliases we accept when auto-mapping.
_ALIASES = {
    "date": ("date", "fecha", "order_date", "día", "dia", "fecha_venta", "fecha de venta"),
    "product_name": ("product_name", "product", "producto", "item", "nombre", "name",
                     "sku_name", "descripcion", "descripción", "artículo", "articulo"),
    "quantity": ("quantity", "qty", "cantidad", "units", "unidades", "cant"),
    "price": ("price", "precio", "unit_price", "precio_unitario", "amount", "importe",
              "precio_unit", "p_unit"),
    "status": ("status", "estado"),
}
_FILE_MAX_HEADER_SKIP = 4   # try skipping up to N junk rows before the real header


def infer_mapping(headers: list[str]) -> dict[str, str]:
    """Auto-map raw headers → canonical fields by alias (case/space-insensitive)."""
    norm = {h: re.sub(r"\s+", "_", (h or "").strip().lower()) for h in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for raw, n in norm.items():
            if n in aliases or n.replace("_", " ") in aliases:
                mapping[canonical] = raw
                break
    return mapping


# ── robust parsing ───────────────────────────────────────────────────────────
def _decode(content: bytes) -> str:
    """Decode bytes to text, auto-detecting the encoding (Latin-1/UTF-8/…)."""
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(content).best()
        if best is not None:
            return str(best)
    except Exception:  # noqa: BLE001
        pass
    return content.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str) -> str:
    """Detect the CSV delimiter from a sample (`,` `;` tab `|`); default comma."""
    import csv

    sample = "\n".join(text.splitlines()[:25])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:  # noqa: BLE001
        return ","


def parse_table(content: bytes, filename: str = "", mapping: Optional[dict] = None
                ) -> tuple[list[dict], list[str], dict]:
    """PURE: raw file bytes → (canonical records, detected headers, mapping used).

    Handles .xlsx/.xls + CSV/TXT with any delimiter/encoding, skipping junk title rows
    by picking the header row whose columns map best to the canonical fields."""
    import pandas as pd

    name = (filename or "").lower()
    is_excel = name.endswith((".xlsx", ".xls"))
    text = None if is_excel else _decode(content)
    sep = "," if is_excel else _sniff_delimiter(text)

    best = None  # (df, headers, inferred_mapping, score)
    for skip in range(_FILE_MAX_HEADER_SKIP):
        try:
            if is_excel:
                df = pd.read_excel(io.BytesIO(content), dtype=str, header=skip)
            else:
                df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str,
                                 skip_blank_lines=True, skiprows=skip)
        except Exception:  # noqa: BLE001 — try the next header offset
            continue
        if df is None or df.shape[1] == 0 or df.shape[0] == 0:
            continue
        headers = [str(h) for h in df.columns]
        inferred = infer_mapping(headers)
        score = len(inferred)
        if best is None or score > best[3]:
            best = (df, headers, inferred, score)
        if score >= 2:   # found the real header (date + product, etc.)
            break

    if best is None:
        return [], [], (mapping or {})

    df, headers, inferred, _ = best
    df = df.fillna("")
    use = mapping or inferred
    records = [
        {canon: str(row[src]).strip() for canon, src in use.items() if src in df.columns}
        for _, row in df.iterrows()
    ]
    return records, headers, use


def parse_csv(text: str, mapping: Optional[dict] = None) -> tuple[list[dict], dict]:
    """Backwards-compatible CSV text parse (delegates to the robust core)."""
    records, _headers, used = parse_table(text.encode("utf-8"), "data.csv", mapping)
    return records, used


def detect_duplicate_products(records: list[dict], threshold: float = 0.86) -> list[list[str]]:
    """PURE: groups of product names that look like the same product (warn-only — never
    auto-merged, since "Coca 500ml"/"Coca 1L" must stay distinct)."""
    import difflib

    names = sorted({r["product_name"] for r in records if r.get("product_name")})
    groups: list[list[str]] = []
    seen: set[str] = set()
    for i, a in enumerate(names):
        if a in seen:
            continue
        na = _norm(a)
        similar = [b for b in names[i + 1:]
                   if b not in seen and na != _norm(b)
                   and difflib.SequenceMatcher(None, na, _norm(b)).ratio() >= threshold]
        if similar:
            group = [a] + similar
            groups.append(group)
            seen.update(group)
    return groups


def _synthetic_order_id(rec: dict, occurrence: int) -> int:
    """Deterministic 63-bit order_id from record content + occurrence (idempotent re-import)."""
    key = f"{rec['date']}|{rec['product_name']}|{rec['quantity']}|{rec['price']}|{occurrence}"
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:15], 16)


def records_to_orders(records: list[dict], tenant_id: str) -> list[dict]:
    """PURE: validated canonical records → wc_orders_cache rows (one line-item each)."""
    seen: Counter = Counter()
    rows = []
    for rec in records:
        sig = (rec["date"], rec["product_name"], rec["quantity"], rec["price"])
        occ = seen[sig]
        seen[sig] += 1
        rows.append({
            "tenant_id": tenant_id,
            "order_id": _synthetic_order_id(rec, occ),
            "status": rec.get("status") or "completed",
            "total": (rec["quantity"] * rec["price"]) if rec["price"] is not None else None,
            "date_created": f"{rec['date']}T12:00:00Z",
            "line_items": [{"product_name": rec["product_name"], "qty": rec["quantity"],
                            "price": rec["price"]}],
        })
    return rows


async def import_records(records: list[dict]) -> dict:
    """Validate + ingest canonical records for the current tenant, then compile the ledger."""
    ctx = current()
    if ctx is None:
        raise RuntimeError("import_records requires a tenant context")
    tid = ctx.tenant_id
    report = validate_records(records)
    rows = records_to_orders(report["valid"], tid)
    client = await get_supabase()
    for i in range(0, len(rows), 400):
        await client.table("wc_orders_cache").upsert(
            rows[i:i + 400], on_conflict="tenant_id,order_id").execute()
    compiled = await compile_ledger_for_tenant() if rows else {"rows": 0, "products_added": 0}
    return {
        "imported": len(rows),
        "rejected": report["rejected"],
        "warnings": report["warnings"],
        "stats": report["stats"],
        "ledger": {"rows": compiled.get("rows", 0), "products_added": compiled.get("products_added", 0)},
    }


def preview_table(content: bytes, filename: str = "", mapping: Optional[dict] = None) -> dict:
    """Validate WITHOUT committing — everything the mapping UI needs (PURE)."""
    records, headers, used = parse_table(content, filename, mapping)
    report = validate_records(records)
    return {
        "headers": headers,
        "mapping": used,
        "stats": report["stats"],
        "sample": report["valid"][:10],
        "rejected": report["rejected"][:50],
        "warnings": report["warnings"][:50],
        "possible_duplicates": detect_duplicate_products(report["valid"])[:20],
    }


async def import_table(content: bytes, filename: str = "", mapping: Optional[dict] = None) -> dict:
    """Parse (robust) + validate + ingest a file for the current tenant."""
    records, headers, used = parse_table(content, filename, mapping)
    result = await import_records(records)
    result["mapping"] = used
    result["headers"] = headers
    return result


async def import_csv(text: str, mapping: Optional[dict] = None) -> dict:
    """Backwards-compatible: import CSV text (used by the Google-Sheets path)."""
    return await import_table(text.encode("utf-8"), "data.csv", mapping)


def _sheet_csv_url(url: str) -> Optional[str]:
    """Google-Sheets share URL → its CSV export URL (public sheets only)."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url or "")
    if not m:
        return None
    gid = "0"
    g = re.search(r"[#&?]gid=(\d+)", url)
    if g:
        gid = g.group(1)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"


async def connect_google_sheet(url: str, mapping: Optional[dict] = None) -> dict:
    """Fetch a PUBLIC Google Sheet as CSV and import it for the current tenant."""
    import httpx

    csv_url = _sheet_csv_url(url)
    if not csv_url:
        raise ValueError("URL de Google Sheets inválida")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        r = await http.get(csv_url)
        r.raise_for_status()
        content = r.content
    return await import_table(content, "sheet.csv", mapping)
