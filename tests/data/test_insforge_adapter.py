# spec: specs/data/insforge-adapter.spec.md
"""TDD for the InsForge REST adapter (S1).

httpx is mocked with MockTransport so no live backend is needed. Each test maps
to an Acceptance Criterion / Invariant in the spec.
"""
import json

import httpx
import pytest

from src.infra import insforge


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INSFORGE_URL", "https://aria.test.insforge.app")
    monkeypatch.setenv("INSFORGE_API_KEY", "sk-admin-secret")


def _client(handler, token="jwt-A"):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return insforge.InsForgeClient(token, http=http)


async def test_select_translates_to_postgrest():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"id": 1, "total": 10}])

    res = await (
        _client(handler, "jwt-A")
        .table("wc_orders_cache")
        .select("id,total")
        .eq("status", "processing")
        .limit(10)
        .execute()
    )

    assert res.data == [{"id": 1, "total": 10}]
    assert "/api/database/records/wc_orders_cache" in captured["url"]
    assert "status=eq.processing" in captured["url"]
    assert "limit=10" in captured["url"]
    # select=id,total (comma may be url-encoded as %2C)
    assert "select=id%2Ctotal" in captured["url"] or "select=id,total" in captured["url"]
    assert captured["auth"] == "Bearer jwt-A"


async def test_error_raises_not_silent():
    def handler(request):
        return httpx.Response(
            400, json={"error": "INVALID_QUERY", "message": "bad filter", "statusCode": 400}
        )

    with pytest.raises(insforge.InsForgeError) as ei:
        await _client(handler).table("posts").select().execute()

    assert ei.value.code == "INVALID_QUERY"
    assert ei.value.status_code == 400


async def test_secret_never_logged(capsys):
    secret = "super-secret-jwt-DO-NOT-LEAK-123"

    def handler(request):
        return httpx.Response(403, json={"error": "FORBIDDEN", "message": "nope"})

    with pytest.raises(insforge.InsForgeError):
        await _client(handler, token=secret).table("posts").select().execute()

    out = capsys.readouterr().out
    assert secret not in out


async def test_insert_uses_array_and_returns_representation():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["prefer"] = request.headers.get("prefer")
        return httpx.Response(201, json=[{"id": "x", "title": "x"}])

    res = await _client(handler).table("aria_proposals").insert({"title": "x"}).execute()

    assert captured["method"] == "POST"
    assert isinstance(captured["body"], list)  # array format required by InsForge
    assert captured["body"] == [{"title": "x"}]
    assert "return=representation" in captured["prefer"]
    assert res.data == [{"id": "x", "title": "x"}]


async def test_rpc_targets_rpc_path_with_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"n": 3}])

    res = await _client(handler, "jwt-A").rpc("exec_safe_read", {"q": "SELECT 1"})

    assert captured["path"] == "/api/database/rpc/exec_safe_read"
    assert captured["auth"] == "Bearer jwt-A"
    assert captured["body"] == {"q": "SELECT 1"}
    assert res.data == [{"n": 3}]


async def test_in_filter_and_order():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    await (
        _client(handler)
        .table("aria_proposals")
        .select()
        .in_("status", ["pending", "approved"])
        .order("created_at", desc=True)
        .execute()
    )

    assert "status=in." in captured["url"]
    assert "pending" in captured["url"] and "approved" in captured["url"]
    assert "order=created_at.desc" in captured["url"]


async def test_multiple_order_combines_into_single_param():
    """Chained .order() must emit ONE `order=col1,col2` param, not two `order=`
    params — PostgREST rejects duplicates ("failed to parse filter"). Mirrors
    supabase-py, where successive .order() calls accumulate sort keys."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        # httpx exposes repeated query keys via .get_list / multi_items
        captured["orders"] = request.url.params.get_list("order")
        return httpx.Response(200, json=[])

    await (
        _client(handler)
        .table("daily_inventory_ledger")
        .select("product_name,date")
        .order("product_name")
        .order("date")
        .execute()
    )

    # Exactly one order param, carrying both clauses in PostgREST syntax.
    assert captured["orders"] == ["product_name.asc,date.asc"]
    assert (
        "order=product_name.asc%2Cdate.asc" in captured["url"]
        or "order=product_name.asc,date.asc" in captured["url"]
    )


async def test_single_returns_object_not_list():
    def handler(request):
        return httpx.Response(200, json=[{"id": "only"}])

    res = await _client(handler).table("tenants").select().eq("id", "x").single().execute()
    assert res.data == {"id": "only"}


def test_get_tenant_client_requires_jwt():
    with pytest.raises(insforge.InsForgeError):
        insforge.get_tenant_client("")


def test_get_admin_client_requires_key(monkeypatch):
    monkeypatch.delenv("INSFORGE_API_KEY", raising=False)
    with pytest.raises(insforge.InsForgeError):
        insforge.get_admin_client()
