"""CSV / Google-Sheets ingestion for tenants without WooCommerce.

Maps a user's columns to the canonical sales record, validates with data_quality, then
feeds the SAME keystone path as WooCommerce: synthesise ``wc_orders_cache`` rows (one
line-item per record) and call ``compile_ledger_for_tenant``. One ingestion pipeline,
not two — the ledger is always produced by the M1 ETL.

Idempotent re-import: each record gets a DETERMINISTIC synthetic ``order_id`` (stable
hash of its content + occurrence index), so re-uploading the same file upserts in place
(0011 UNIQUE(tenant_id,order_id)) instead of double-counting.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from typing import Any, Optional

from src.infra.db import get_supabase
from src.infra.tenant_context import current
from src.tools.data_quality import validate_records
from src.tools.ledger_etl import compile_ledger_for_tenant

# Canonical field → the set of header aliases we accept when auto-mapping.
_ALIASES = {
    "date": ("date", "fecha", "order_date", "día", "dia"),
    "product_name": ("product_name", "product", "producto", "item", "nombre", "name", "sku_name"),
    "quantity": ("quantity", "qty", "cantidad", "units", "unidades"),
    "price": ("price", "precio", "unit_price", "precio_unitario", "amount"),
    "status": ("status", "estado"),
}


def infer_mapping(headers: list[str]) -> dict[str, str]:
    """Auto-map raw headers → canonical fields by alias (case/space-insensitive)."""
    norm = {h: re.sub(r"\s+", "_", (h or "").strip().lower()) for h in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for raw, n in norm.items():
            if n in aliases:
                mapping[canonical] = raw
                break
    return mapping


def parse_csv(text: str, mapping: Optional[dict] = None) -> tuple[list[dict], dict]:
    """Parse CSV text → (canonical records, mapping used). Pure. ``mapping`` maps
    canonical field → raw header; inferred from the header row when omitted."""
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    mp = mapping or infer_mapping(headers)
    records = []
    for raw in reader:
        records.append({canon: raw.get(src) for canon, src in mp.items()})
    return records, mp


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


async def import_csv(text: str, mapping: Optional[dict] = None) -> dict:
    """Parse + import CSV text for the current tenant."""
    records, used = await _parse_async(text, mapping)
    result = await import_records(records)
    result["mapping"] = used
    return result


async def _parse_async(text: str, mapping: Optional[dict]):
    return parse_csv(text, mapping)


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
        text = r.text
    return await import_csv(text, mapping)
