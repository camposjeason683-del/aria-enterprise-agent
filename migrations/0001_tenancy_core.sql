-- M1 — Tenancy core (tenants, membership+role, integrations, plugins)
-- Apply via: POST /api/database/migrations  {version:"0001", name:"tenancy-core", sql:"..."}
-- or: npx @insforge/cli db query < migrations/0001_tenancy_core.sql
-- NOTE: InsForge runs each migration in its own transaction — do NOT add BEGIN/COMMIT.
-- spec: specs/tenancy/tenant-isolation.spec.md

-- ── Tenants (empresas) ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                VARCHAR(255) NOT NULL,
  slug                VARCHAR(255) UNIQUE NOT NULL,
  subscription_tier   VARCHAR(50)  NOT NULL DEFAULT 'free',     -- free | pro | enterprise
  subscription_status VARCHAR(50)  NOT NULL DEFAULT 'active',   -- active | past_due | canceled
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ── Membership + role (admin / employee) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role       VARCHAR(20) NOT NULL DEFAULT 'employee' CHECK (role IN ('admin','employee')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tenant_users_user   ON tenant_users(user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant ON tenant_users(tenant_id);

-- ── Per-tenant integration credentials (WooCommerce). Values are encrypted at
--    the application layer before insert; columns are opaque ciphertext. ──────
CREATE TABLE IF NOT EXISTS tenant_integrations (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  woo_url             VARCHAR(255),
  woo_consumer_key    TEXT,   -- encrypted
  woo_consumer_secret TEXT,   -- encrypted
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id)
);

-- ── Per-tenant capabilities (consumed by src/plugins/registry.py) ────────────
CREATE TABLE IF NOT EXISTS tenant_plugins (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plugin_name VARCHAR(100) NOT NULL,
  active      BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, plugin_name)
);

-- Keep updated_at fresh (InsForge built-in trigger function).
CREATE TRIGGER tenants_updated_at            BEFORE UPDATE ON tenants            FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER tenant_integrations_updated_at BEFORE UPDATE ON tenant_integrations FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
