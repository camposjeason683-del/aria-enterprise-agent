# spec: migrations/0006_audit_remediation.sql (pedido_config: per-tenant transit_days/coverage_days)
"""Regression tests for batch_purchase_orders' pedido_config read (Bug 1).

Pre-existing bug: the sweep read pedido_config with `.select("name, dias_transito,
dias_inventario")`, but the real table (migration 0006) is per-tenant with columns
transit_days / coverage_days. The read 400'd ("column pedido_config.name does not
exist") and fell back to defaults via try/except, so the per-tenant config was NEVER
applied. These tests pin (a) the SELECT uses the real columns and (b) the values
actually flow into the reorder-point math.

Backend is mocked with httpx.MockTransport — no live DB, no shared-state writes.
"""
import httpx
import pytest

from src.infra import insforge
from src.tools import strategic

TARGET_DATE = "2026-06-05"  # latest_ledger_date the mock reports

# One critical product (stock 5 ≤ 15) with enough recent orders to yield daily > 0.
_PRODUCT = {"id": "p1", "name": "Tomate", "sku": "SKU-1", "price": 10.0}
_CRITICAL_LEDGER = [
    {"product_id": "p1", "product_name": "Tomate", "stock_end_of_day": 5, "sales_velocity": 2.0}
]
_CATALOG = [{"product_id": "p1", "nombre_original": "Tomate", "proveedor": "Proveedor X"}]
# 12 completed orders within ~3 weeks of TARGET_DATE → non-zero weekly velocity.
_ORDERS = [
    {
        "id": 1000 + i,
        "date_created": f"2026-05-{15 + i:02d}T10:00:00Z",
        "status": "completed",
        "line_items": [{"name": "Tomate", "sku": "SKU-1", "quantity": 5}],
    }
    for i in range(12)
]


def _make_handler(pedido_config_rows, captured):
    """Build a MockTransport handler returning canned data; records each table's
    `select` param so the test can assert which columns were requested."""

    def handler(request: httpx.Request) -> httpx.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        params = request.url.params
        select = params.get("select")
        captured.setdefault(table, []).append(select)

        if table == "daily_inventory_ledger":
            # latest_ledger_date uses select=date; the critical-stock read uses a
            # wider projection. Distinguish by the projection.
            if select == "date":
                return httpx.Response(200, json=[{"date": TARGET_DATE}])
            return httpx.Response(200, json=_CRITICAL_LEDGER)
        if table == "products":
            return httpx.Response(200, json=[_PRODUCT])
        if table == "supplier_catalog":
            return httpx.Response(200, json=_CATALOG)
        if table == "pedido_config":
            return httpx.Response(200, json=list(pedido_config_rows))
        if table == "wc_orders_cache":
            return httpx.Response(200, json=_ORDERS)
        return httpx.Response(200, json=[])

    return handler


async def _run_batch(monkeypatch, pedido_config_rows, captured):
    client = insforge.InsForgeClient(
        "test-jwt", http=httpx.AsyncClient(transport=httpx.MockTransport(_make_handler(pedido_config_rows, captured)))
    )

    async def fake_get_supabase():
        return client

    monkeypatch.setattr(strategic, "get_supabase", fake_get_supabase)
    return await strategic.batch_purchase_orders()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INSFORGE_URL", "https://aria.test.insforge.app")
    monkeypatch.setenv("INSFORGE_API_KEY", "sk-admin-secret")


def _first_product(result):
    opps = result.get("batching_opportunities", [])
    assert opps, f"expected at least one batching opportunity, got: {result}"
    prods = opps[0]["productos"]
    assert prods, "opportunity had no products"
    return prods[0]


async def test_pedido_config_selects_real_columns(monkeypatch):
    """The read must request transit_days/coverage_days — never the dropped `name`
    or the never-existent dias_transito/dias_inventario columns."""
    captured = {}
    await _run_batch(monkeypatch, [{"transit_days": 5, "coverage_days": 10}], captured)

    selects = captured.get("pedido_config")
    assert selects, "batch_purchase_orders never queried pedido_config"
    sel = selects[0] or ""
    assert "transit_days" in sel and "coverage_days" in sel
    assert "name" not in sel
    assert "dias_transito" not in sel and "dias_inventario" not in sel


async def test_per_tenant_config_is_applied_to_reorder_math(monkeypatch):
    """With a custom (transit=5, coverage=10) config the safety stock and reorder
    point must scale vs the defaults (3, 7) — proving the values are USED, not
    silently dropped. Same orders → same daily, so the ratios are deterministic:
      safety_stock ∝ coverage_days        → 10/7
      reorder_point ∝ transit+coverage    → 15/10
    """
    cap_cfg, cap_def = {}, {}
    res_cfg = await _run_batch(monkeypatch, [{"transit_days": 5, "coverage_days": 10}], cap_cfg)
    res_def = await _run_batch(monkeypatch, [], cap_def)  # empty → code falls back to 3/7

    p_cfg = _first_product(res_cfg)
    p_def = _first_product(res_def)

    # daily > 0 ⇒ positive safety stock / reorder point in both runs.
    assert p_def["stock_seguridad"] > 0 and p_def["punto_de_reorden"] > 0

    assert p_cfg["stock_seguridad"] / p_def["stock_seguridad"] == pytest.approx(10 / 7, rel=0.05)
    assert p_cfg["punto_de_reorden"] / p_def["punto_de_reorden"] == pytest.approx(15 / 10, rel=0.05)
