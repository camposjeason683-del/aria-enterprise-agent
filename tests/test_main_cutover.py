# spec: specs/auth/tenant-auth.spec.md  (main.py wiring)
"""Smoke test of the main.py cutover wiring via a real TestClient request.
No live DB: these paths reject/short-circuit before any InsForge call."""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_chat_requires_auth(client):
    # No Authorization header → require_tenant rejects before the agent runs.
    r = client.post("/api/v1/chat", data={"message": "hola"})
    assert r.status_code == 401


def test_chat_rejects_non_bearer(client):
    r = client.post(
        "/api/v1/chat",
        data={"message": "hola"},
        headers={"Authorization": "Basic abc"},
    )
    assert r.status_code == 401


def test_proposals_require_auth(client):
    assert client.get("/api/v1/proposals").status_code == 401


def test_cron_is_501_pending_multitenant(client):
    assert client.post("/api/v1/cron/morning-brief").status_code == 501
    assert client.post("/api/v1/cron/proactive-sweep").status_code == 501
