# spec: cron multi-tenant proactive-sweep wiring (Fase 2)
"""Unit test for the headless per-tenant cron loop (no DB).

Mocks the active-tenant list + the sweep coroutine and asserts the loop runs each
tenant under its OWN headless context, isolates per-tenant failures, and that the
shared-secret guard rejects unauthenticated calls.
"""
import pytest
from fastapi.testclient import TestClient

import src.main as main_mod
from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_proactive_sweep_iterates_tenants_and_isolates_failures(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")

    async def fake_list(*a, **k):
        return [{"id": "t-A"}, {"id": "t-B"}]

    monkeypatch.setattr(main_mod, "list_active_tenants", fake_list)

    ran_under = []

    async def fake_sweep():
        from src.infra.tenant_context import current

        ctx = current()
        ran_under.append(ctx.tenant_id if ctx else None)
        assert ctx is not None and ctx.headless  # ran under a headless context
        if ctx.tenant_id == "t-B":
            raise RuntimeError("boom")  # one tenant fails
        return {"ok": True}

    monkeypatch.setattr("src.tools.strategic.execute_proactive_sweep_auto", fake_sweep)

    r = client.post("/api/v1/cron/proactive-sweep", headers={"X-Cron-Secret": "s3cr3t"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenants"] == 2
    statuses = {x["tenant_id"]: x["status"] for x in body["results"]}
    assert statuses == {"t-A": "ok", "t-B": "error"}  # B failed, A still ran
    assert ran_under == ["t-A", "t-B"]  # each under its own tenant context


def test_cron_rejects_without_secret(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    assert client.post("/api/v1/cron/proactive-sweep").status_code == 403
    assert client.post("/api/v1/cron/morning-brief").status_code == 403
