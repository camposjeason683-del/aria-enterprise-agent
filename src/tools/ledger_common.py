"""Shared read helpers for the tool layer.

Single source of truth for small data-access idioms that were copy-pasted across
the strategic / analytics / database tool modules. Keeping them here removes the
duplication (DRY) and gives one place to optimize.
"""
from typing import Optional


async def latest_ledger_date(client) -> Optional[str]:
    """Most recent ``date`` present in ``daily_inventory_ledger`` for the current
    tenant, or ``None`` when the ledger is empty.

    Canonical form of the "latest available ledger date" lookup that appeared
    verbatim at ~11 call sites. Callers keep their own empty-fallback (most
    default to today's date; the sync worker keeps ``None``) so the exact
    per-site semantics are preserved. Backed by ``idx_ledger_tenant_date_desc``
    (migration 0006) → index-only top-1 read.

    ``client`` is a tenant-scoped InsForge client; RLS already constrains the
    rows to the caller's tenant, so no explicit tenant filter is needed here.
    """
    res = (
        await client.table("daily_inventory_ledger")
        .select("date")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["date"] if res.data else None
