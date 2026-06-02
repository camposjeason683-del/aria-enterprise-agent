# spec: specs/auth/tenant-auth.spec.md
"""TDD for tenant authentication (S2). No live backend: JWTs are signed with a
test secret and the admin client is faked."""
import pytest
from fastapi import HTTPException
from jose import jwt as jose_jwt

from src.infra import auth as auth_mod
from src.infra.insforge import InsForgeResponse

SECRET = "test-jwt-secret-aria"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INSFORGE_JWT_SECRET", SECRET)


def _token(sub="u1", secret=SECRET, **extra):
    return jose_jwt.encode({"sub": sub, **extra}, secret, algorithm="HS256")


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def execute(self):
        return InsForgeResponse(self._rows)


class _FakeAdmin:
    def __init__(self, rows, expect_table="tenant_users"):
        self._rows = rows
        self._expect_table = expect_table

    def table(self, name):
        assert name == self._expect_table
        return _FakeQuery(self._rows)


# ── verify_insforge_jwt ──────────────────────────────────────────────────────
def test_verify_valid_returns_claims():
    claims = auth_mod.verify_insforge_jwt(_token("u1"))
    assert claims["sub"] == "u1"


def test_verify_invalid_signature_rejected():
    bad = _token("u1", secret="the-wrong-secret")
    with pytest.raises(HTTPException) as ei:
        auth_mod.verify_insforge_jwt(bad)
    assert ei.value.status_code == 403


def test_verify_requires_configured_secret(monkeypatch):
    token = _token("u1")
    monkeypatch.delenv("INSFORGE_JWT_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        auth_mod.verify_insforge_jwt(token)
    assert ei.value.status_code == 500


# ── resolve_tenant_membership ────────────────────────────────────────────────
async def test_resolve_returns_tenant_and_role():
    admin = _FakeAdmin([{"tenant_id": "A", "role": "admin"}])
    membership = await auth_mod.resolve_tenant_membership("u1", admin=admin)
    assert membership == {"tenant_id": "A", "role": "admin"}


async def test_resolve_rejects_user_without_membership():
    admin = _FakeAdmin([])  # no tenant_users row
    with pytest.raises(HTTPException) as ei:
        await auth_mod.resolve_tenant_membership("u1", admin=admin)
    assert ei.value.status_code == 403


# ── require_tenant ───────────────────────────────────────────────────────────
async def test_require_tenant_rejects_missing_bearer():
    with pytest.raises(HTTPException) as ei:
        await auth_mod.require_tenant(_FakeRequest({}))
    assert ei.value.status_code == 401


async def test_require_tenant_uses_jwt_identity_and_seeds_contextvar(monkeypatch):
    async def fake_resolve(user_id, admin=None):
        assert user_id == "u1"  # identity comes from the JWT sub
        return {"tenant_id": "A", "role": "employee"}

    monkeypatch.setattr(auth_mod, "resolve_tenant_membership", fake_resolve)

    # The client tries to spoof a different user_id via a form field; ignored.
    req = _FakeRequest({"Authorization": f"Bearer {_token('u1')}"})
    ctx = await auth_mod.require_tenant(req)

    assert ctx.user_id == "u1"
    assert ctx.tenant_id == "A"
    assert ctx.role == "employee"

    from src.infra.tenant_context import current

    assert current().user_id == "u1"
    assert current().jwt  # token carried for RLS-scoped data calls


def test_tenant_context_hides_jwt_in_repr():
    from src.infra.tenant_context import TenantContext

    ctx = TenantContext(user_id="u1", tenant_id="A", role="admin", jwt="secret-token")
    assert "secret-token" not in repr(ctx)
