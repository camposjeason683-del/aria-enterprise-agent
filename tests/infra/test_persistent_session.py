# spec: specs/infra/persistent-session.spec.md
"""TDD for the InsForge-backed session service (S4).

A fake in-memory store stands in for InsForge but does a REAL
Session.model_dump(mode="json") -> Session(**...) round-trip, so it validates
serialization, not just call wiring.
"""
import pytest
from google.adk.events.event import Event

from src.infra.insforge import InsForgeResponse
from src.infra.session_insforge import InsForgeSessionService


class _FakeStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}


class _FakeQuery:
    def __init__(self, store: _FakeStore):
        self._store = store
        self._op = None
        self._row = None
        self._filters: dict = {}

    def upsert(self, row, on_conflict=None):
        self._op, self._row = "upsert", row
        return self

    def select(self, *a, **k):
        self._op = "select"
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, n):
        return self

    async def execute(self):
        if self._op == "upsert":
            self._store.rows[self._row["id"]] = self._row
            return InsForgeResponse([self._row])
        if self._op == "select":
            row = self._store.rows.get(self._filters.get("id"))
            return InsForgeResponse([row] if row else [])
        if self._op == "delete":
            self._store.rows.pop(self._filters.get("id"), None)
            return InsForgeResponse([])
        return InsForgeResponse([])


class _FakeClient:
    def __init__(self, store: _FakeStore):
        self._store = store

    def table(self, name):
        assert name == "agent_sessions"
        return _FakeQuery(self._store)


def _service(store):
    return InsForgeSessionService(client_factory=lambda: _FakeClient(store))


async def test_create_persists_session():
    store = _FakeStore()
    svc = _service(store)
    await svc.create_session(
        app_name="agents", user_id="u1", state={"tenant_id": "A"}, session_id="s1"
    )
    assert "agents:u1:s1" in store.rows
    assert store.rows["agents:u1:s1"]["session_id"] == "s1"


async def test_session_survives_restart():
    store = _FakeStore()
    svc = _service(store)
    sess = await svc.create_session(app_name="agents", user_id="u1", session_id="s1")
    await svc.append_event(sess, Event(author="user"))

    # A brand-new service instance with empty memory (== a restart / other pod).
    svc2 = _service(store)
    loaded = await svc2.get_session(app_name="agents", user_id="u1", session_id="s1")

    assert loaded is not None
    assert len(loaded.events) >= 1


async def test_append_event_is_persisted():
    store = _FakeStore()
    svc = _service(store)
    sess = await svc.create_session(app_name="agents", user_id="u1", session_id="s1")
    await svc.append_event(sess, Event(author="user"))

    row = store.rows["agents:u1:s1"]
    assert len(row["state"]["events"]) >= 1


async def test_get_missing_session_returns_none():
    store = _FakeStore()
    svc = _service(store)
    got = await svc.get_session(app_name="agents", user_id="u1", session_id="nope")
    assert got is None
