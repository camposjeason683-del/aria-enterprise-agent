"""
ARIA-OS: InsForge data adapter (anti-corruption layer / hexagonal port).

Speaks InsForge's PostgREST-style REST API while exposing the SAME fluent query
interface the tools already used with supabase-py
(`.table().select().eq()...execute() -> .data`), so the Supabase -> InsForge
migration is isolated to this module instead of ~50 tool functions.

Two client factories:
  - get_admin_client()      -> Authorization: Bearer <INSFORGE_API_KEY>
                               (system tables only; the admin key BYPASSES RLS)
  - get_tenant_client(jwt)  -> Authorization: Bearer <user JWT>
                               (business data; RLS-scoped via auth.uid())

Why an adapter and not the supabase-py client repointed at InsForge: InsForge's
REST paths differ (`/api/database/records/{t}` vs `/rest/v1/{t}`) and its auth
header model is single-header (`Authorization` only, no separate `apikey`), so a
thin purpose-built translator is more predictable than coercing another client.

# spec: specs/data/insforge-adapter.spec.md
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from src.infra.logger import log_error

# REST surface (see fetch-sdk-docs db/rest-api).
_RECORDS_PATH = "/api/database/records"
_RPC_PATH = "/api/database/rpc"

# PostgREST scalar filter operators exposed as fluent methods.
_FILTER_OPS = ("eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike")


class InsForgeError(Exception):
    """Domain error raised on any non-2xx InsForge response or transport failure.

    Carrying ``code``/``message`` (never the offending token) keeps I2 intact:
    callers and logs see what failed, not the secret used to authenticate.
    """

    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"InsForge {code}: {message}")


class InsForgeResponse:
    """Mirrors supabase-py's APIResponse surface the tools read: ``.data``/``.count``."""

    __slots__ = ("data", "count")

    def __init__(self, data: Any, count: int | None = None):
        self.data = data
        self.count = count


def _fmt(value: Any) -> str:
    """Render a Python value as a PostgREST filter literal."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _merge_prefer(existing: str | None, addition: str) -> str:
    return f"{existing},{addition}" if existing else addition


# ─── Shared pooled HTTP client (per-request auth header, reused connections) ──
_http: httpx.AsyncClient | None = None


def _shared_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=20.0)
    return _http


async def close_http() -> None:
    """Close the shared client during server shutdown."""
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _base_url() -> str:
    url = os.environ.get("INSFORGE_URL", "").rstrip("/")
    if not url:
        raise InsForgeError("CONFIG", "INSFORGE_URL is not set in the environment")
    return url


class _Query:
    """Chainable PostgREST query builder. Sync builders; async ``execute()``."""

    def __init__(self, client: "InsForgeClient", table: str):
        self._client = client
        self._table = table
        self._params: list[tuple[str, str]] = []
        self._method = "GET"
        self._body: Any = None
        self._headers: dict[str, str] = {}
        self._single = False
        self._maybe_single = False

    # ── projection ──────────────────────────────────────────────────────────
    def select(self, columns: str = "*", count: str | None = None) -> "_Query":
        if columns and columns != "*":
            self._params.append(("select", columns))
        if count:
            self._headers["Prefer"] = _merge_prefer(
                self._headers.get("Prefer"), f"count={count}"
            )
        return self

    # ── scalar filters (eq/neq/gt/gte/lt/lte/like/ilike) ─────────────────────
    def _filter(self, op: str, column: str, value: Any) -> "_Query":
        self._params.append((column, f"{op}.{_fmt(value)}"))
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        return self._filter("eq", column, value)

    def neq(self, column: str, value: Any) -> "_Query":
        return self._filter("neq", column, value)

    def gt(self, column: str, value: Any) -> "_Query":
        return self._filter("gt", column, value)

    def gte(self, column: str, value: Any) -> "_Query":
        return self._filter("gte", column, value)

    def lt(self, column: str, value: Any) -> "_Query":
        return self._filter("lt", column, value)

    def lte(self, column: str, value: Any) -> "_Query":
        return self._filter("lte", column, value)

    def like(self, column: str, pattern: str) -> "_Query":
        return self._filter("like", column, pattern)

    def ilike(self, column: str, pattern: str) -> "_Query":
        return self._filter("ilike", column, pattern)

    def in_(self, column: str, values: list[Any]) -> "_Query":
        joined = ",".join(_fmt(v) for v in values)
        self._params.append((column, f"in.({joined})"))
        return self

    def is_(self, column: str, value: Any) -> "_Query":
        self._params.append((column, f"is.{_fmt(value)}"))
        return self

    # ── modifiers ────────────────────────────────────────────────────────────
    def order(self, column: str, desc: bool = False) -> "_Query":
        # PostgREST wants ONE `order=` param with comma-separated clauses
        # (`order=a.asc,b.desc`). Appending a separate ("order", ...) tuple per call
        # makes httpx serialize duplicate `order=` params, which PostgREST rejects
        # with "failed to parse filter (...)". Accumulate into the existing clause so
        # chained `.order()` mirrors supabase-py (the API this adapter emulates).
        clause = f"{column}.{'desc' if desc else 'asc'}"
        for i, (key, val) in enumerate(self._params):
            if key == "order":
                self._params[i] = ("order", f"{val},{clause}")
                return self
        self._params.append(("order", clause))
        return self

    def limit(self, n: int) -> "_Query":
        self._params.append(("limit", str(n)))
        return self

    def range(self, start: int, end: int) -> "_Query":
        self._params.append(("offset", str(start)))
        self._params.append(("limit", str(end - start + 1)))
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    def maybe_single(self) -> "_Query":
        self._maybe_single = True
        return self

    # ── writes ───────────────────────────────────────────────────────────────
    def insert(self, rows: Any) -> "_Query":
        self._method = "POST"
        self._body = rows if isinstance(rows, list) else [rows]
        self._headers["Prefer"] = _merge_prefer(
            self._headers.get("Prefer"), "return=representation"
        )
        return self

    def upsert(self, rows: Any, on_conflict: str | None = None) -> "_Query":
        self._method = "POST"
        self._body = rows if isinstance(rows, list) else [rows]
        self._headers["Prefer"] = _merge_prefer(
            self._headers.get("Prefer"),
            "resolution=merge-duplicates,return=representation",
        )
        if on_conflict:
            self._params.append(("on_conflict", on_conflict))
        return self

    def update(self, values: dict) -> "_Query":
        self._method = "PATCH"
        self._body = values
        self._headers["Prefer"] = _merge_prefer(
            self._headers.get("Prefer"), "return=representation"
        )
        return self

    def delete(self) -> "_Query":
        self._method = "DELETE"
        self._headers["Prefer"] = _merge_prefer(
            self._headers.get("Prefer"), "return=representation"
        )
        return self

    async def execute(self) -> InsForgeResponse:
        return await self._client._request(self)


class InsForgeClient:
    """A thin InsForge client bound to one bearer token (admin key or user JWT)."""

    def __init__(self, token: str, http: httpx.AsyncClient | None = None):
        # ``http`` is injectable so tests can pass an httpx.MockTransport client.
        self._token = token
        self._http = http

    def _client_http(self) -> httpx.AsyncClient:
        return self._http or _shared_http()

    def _auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    async def rpc(self, fn: str, params: dict | None = None) -> InsForgeResponse:
        url = f"{_base_url()}{_RPC_PATH}/{fn}"
        http = self._client_http()
        try:
            resp = await http.post(url, json=params or {}, headers=self._auth_headers())
        except httpx.HTTPError as exc:  # network/transport failure
            log_error("InsForge rpc transport error", tool="insforge", error=str(exc))
            raise InsForgeError("NETWORK", str(exc)) from exc
        return _parse_response(resp, single=False, maybe_single=False)

    async def _request(self, q: _Query) -> InsForgeResponse:
        url = f"{_base_url()}{_RECORDS_PATH}/{q._table}"
        http = self._client_http()
        try:
            resp = await http.request(
                q._method,
                url,
                params=q._params or None,
                json=q._body,
                headers=self._auth_headers(q._headers),
            )
        except httpx.HTTPError as exc:
            # Never include the token; only the failure cause (I2).
            log_error(
                "InsForge request transport error",
                tool="insforge",
                error=f"{q._method} {q._table}: {exc}",
            )
            raise InsForgeError("NETWORK", str(exc)) from exc
        return _parse_response(resp, single=q._single, maybe_single=q._maybe_single)


def _parse_response(
    resp: httpx.Response, single: bool, maybe_single: bool
) -> InsForgeResponse:
    if resp.status_code >= 400:
        code, message = "HTTP_ERROR", resp.text[:300]
        try:
            err = resp.json()
            code = err.get("error", code)
            message = err.get("message", message)
        except Exception:
            pass
        # I3: surface, never silence. I2: log code/message, not the bearer token.
        log_error("InsForge error response", tool="insforge", error=f"{code}: {message}")
        raise InsForgeError(code, message, resp.status_code)

    if resp.status_code == 204 or not resp.content:
        data: Any = []
    else:
        data = resp.json()

    count: int | None = None
    raw_count = resp.headers.get("X-Total-Count")
    if raw_count is not None:
        try:
            count = int(raw_count)
        except ValueError:
            count = None

    if single or maybe_single:
        if isinstance(data, list):
            if data:
                data = data[0]
            elif maybe_single:
                data = None
            else:
                raise InsForgeError("NO_ROWS", "single() expected exactly one row")

    return InsForgeResponse(data, count)


# ─── Factories ───────────────────────────────────────────────────────────────
def get_admin_client(http: httpx.AsyncClient | None = None) -> InsForgeClient:
    """Client authenticated with the admin API key. SYSTEM tables only — it
    bypasses RLS, so it must never run LLM-authored or business-data queries."""
    key = os.environ.get("INSFORGE_API_KEY", "")
    if not key:
        raise InsForgeError("CONFIG", "INSFORGE_API_KEY is not set in the environment")
    return InsForgeClient(key, http=http)


def get_tenant_client(user_jwt: str, http: httpx.AsyncClient | None = None) -> InsForgeClient:
    """Client authenticated with the end user's JWT. All business-data and raw-SQL
    access goes through here so InsForge RLS scopes every row to the tenant."""
    if not user_jwt:
        raise InsForgeError("CONFIG", "A tenant JWT is required for get_tenant_client()")
    return InsForgeClient(user_jwt, http=http)


class _TenantScopedAdminClient(InsForgeClient):
    """Admin-key client that pins EVERY ``.table()`` to one ``tenant_id``.

    For the HEADLESS cron path only (no user JWT): the admin key bypasses RLS, so
    every business read/write is scoped explicitly to the tenant — a sweep can never
    touch another tenant's rows even if a call site forgets a filter. All business
    tables carry ``tenant_id``; the deterministic sweep never uses ``.rpc`` (raw
    SQL), so nothing escapes the scope. Inserts already set ``tenant_id`` in the
    payload — the pinned filter is a harmless query param on POST (it only constrains
    the return=representation, not which row is inserted).
    """

    def __init__(self, tenant_id: str, http: httpx.AsyncClient | None = None):
        key = os.environ.get("INSFORGE_API_KEY", "")
        if not key:
            raise InsForgeError("CONFIG", "INSFORGE_API_KEY is not set in the environment")
        super().__init__(key, http=http)
        self._tenant_id = tenant_id

    def table(self, name: str) -> _Query:
        return super().table(name).eq("tenant_id", self._tenant_id)


def get_tenant_scoped_admin_client(
    tenant_id: str, http: httpx.AsyncClient | None = None
) -> InsForgeClient:
    """Headless cron client: admin key + every table pinned to ``tenant_id``."""
    if not tenant_id:
        raise InsForgeError("CONFIG", "tenant_id is required for get_tenant_scoped_admin_client()")
    return _TenantScopedAdminClient(tenant_id, http=http)
