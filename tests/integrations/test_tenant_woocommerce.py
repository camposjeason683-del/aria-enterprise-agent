# spec: specs/integrations/tenant-woocommerce.spec.md
"""TDD for per-tenant WooCommerce credentials (S6, code part). A fake client
stands in for InsForge; encryption is real (Fernet)."""
import pytest
from cryptography.fernet import Fernet

from src.infra import crypto
from src.infra.insforge import InsForgeResponse
from src.tools.integrations import load_tenant_integration, save_tenant_integration


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    # A real (random) Fernet key for the test process.
    monkeypatch.setenv("ARIA_ENCRYPTION_KEY", Fernet.generate_key().decode())


class _IntegrationsClient:
    """Emulates tenant_integrations (one row per tenant)."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._op = None
        self._row = None
        self._filters: dict = {}

    def table(self, name):
        assert name == "tenant_integrations"
        self._op = None
        self._row = None
        self._filters = {}
        return self

    def upsert(self, row, on_conflict=None):
        self._op, self._row = "upsert", row
        return self

    def select(self, *a, **k):
        self._op = "select"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, n):
        return self

    async def execute(self):
        if self._op == "upsert":
            self.rows[self._row["tenant_id"]] = self._row
            return InsForgeResponse([self._row])
        if self._op == "select":
            row = self.rows.get(self._filters.get("tenant_id"))
            return InsForgeResponse([row] if row else [])
        return InsForgeResponse([])


def test_crypto_round_trip():
    ct = crypto.encrypt("ck_supersecret")
    assert ct != "ck_supersecret"  # actually encrypted
    assert crypto.decrypt(ct) == "ck_supersecret"
    assert crypto.encrypt(None) is None and crypto.decrypt(None) is None


async def test_save_stores_encrypted_and_load_decrypts():
    client = _IntegrationsClient()
    await save_tenant_integration(
        "A", "https://shop-a.com", "ck_plain", "cs_plain", client=client
    )

    stored = client.rows["A"]
    # I1: credentials are NOT stored in plaintext.
    assert stored["woo_consumer_key"] != "ck_plain"
    assert stored["woo_consumer_secret"] != "cs_plain"

    loaded = await load_tenant_integration("A", client=client)
    assert loaded["woo_url"] == "https://shop-a.com"
    assert loaded["woo_consumer_key"] == "ck_plain"   # decrypted back
    assert loaded["woo_consumer_secret"] == "cs_plain"


async def test_load_missing_tenant_returns_none():
    client = _IntegrationsClient()
    assert await load_tenant_integration("ghost", client=client) is None
