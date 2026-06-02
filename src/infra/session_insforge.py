"""
ARIA-OS: InsForge-backed ADK session service (write-through persistence).

Subclasses ADK's InMemorySessionService so we reuse its battle-tested state/
event mechanics, and adds durability: every create/append writes the session
through to the `agent_sessions` table, and a get() miss hydrates from InsForge.
This makes conversations survive restarts and work across Cloud Run / Fly
instances (the InMemory default loses them).

If InsForge later exposes a direct Postgres DSN, ADK's DatabaseSessionService is
a drop-in alternative; this REST-backed service avoids needing that DSN.

# spec: specs/infra/persistent-session.spec.md
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.session import Session

from src.infra.insforge import get_admin_client
from src.infra.logger import log_error
from src.infra.tenant_context import current as _current_tenant


def _row_id(app_name: str, user_id: str, session_id: str) -> str:
    return f"{app_name}:{user_id}:{session_id}"


class InsForgeSessionService(InMemorySessionService):
    """Durable session service. ``client_factory`` is injectable for tests."""

    def __init__(
        self,
        client_factory: Optional[Callable[[], Any]] = None,
        table: str = "agent_sessions",
    ):
        super().__init__()
        # agent_sessions is internal infra written only by this trusted service,
        # so it persists via the admin client; the tenant_id column is stored for
        # auditing and future RLS-scoped direct reads.
        self._client_factory = client_factory or get_admin_client
        self._table = table

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        session = await super().create_session(
            app_name=app_name, user_id=user_id, state=state, session_id=session_id
        )
        await self._persist(session)
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        session = await super().get_session(
            app_name=app_name, user_id=user_id, session_id=session_id, config=config
        )
        if session is not None:
            return session
        # Miss in memory (e.g. after a restart or on another instance) → hydrate.
        loaded = await self._load(app_name, user_id, session_id)
        if loaded is None:
            return None
        self.sessions.setdefault(app_name, {}).setdefault(user_id, {})[
            session_id
        ] = loaded
        return await super().get_session(
            app_name=app_name, user_id=user_id, session_id=session_id, config=config
        )

    async def append_event(self, session: Session, event: Event) -> Event:
        result = await super().append_event(session, event)
        stored = (
            self.sessions.get(session.app_name, {})
            .get(session.user_id, {})
            .get(session.id)
        )
        if stored is not None:
            await self._persist(stored)
        return result

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        await super().delete_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        try:
            client = self._client_factory()
            await (
                client.table(self._table)
                .delete()
                .eq("id", _row_id(app_name, user_id, session_id))
                .execute()
            )
        except Exception as exc:  # deletion is best-effort; never crash the flow
            log_error("InsForgeSessionService delete failed", error=str(exc))

    # ── persistence helpers ──────────────────────────────────────────────────
    async def _persist(self, session: Session) -> None:
        ctx = _current_tenant()
        row = {
            "id": _row_id(session.app_name, session.user_id, session.id),
            "app_name": session.app_name,
            "user_id": session.user_id,
            "session_id": session.id,
            "tenant_id": ctx.tenant_id if ctx else None,
            "state": session.model_dump(mode="json"),
            "last_update_time": session.last_update_time,
        }
        try:
            client = self._client_factory()
            await client.table(self._table).upsert(row, on_conflict="id").execute()
        except Exception as exc:
            # Don't let a persistence hiccup abort the user's turn; log it.
            log_error("InsForgeSessionService persist failed", error=str(exc))

    async def _load(
        self, app_name: str, user_id: str, session_id: str
    ) -> Optional[Session]:
        try:
            client = self._client_factory()
            res = (
                await client.table(self._table)
                .select("state")
                .eq("id", _row_id(app_name, user_id, session_id))
                .limit(1)
                .execute()
            )
        except Exception as exc:
            log_error("InsForgeSessionService load failed", error=str(exc))
            return None
        if not res.data:
            return None
        return Session(**res.data[0]["state"])
