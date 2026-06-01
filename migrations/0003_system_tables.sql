-- M3 — System / infra tables.
-- These are written by the trusted backend (admin client). RLS is still enabled
-- in M5 so any direct user reads stay tenant-scoped where tenant_id applies.
-- specs: infra/persistent-session, infra/rate-limiting, canvas/canvas-persistence

-- ── Global kill switch + config (NO tenant_id — platform-wide) ───────────────
CREATE TABLE IF NOT EXISTS system_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO system_config (key, value) VALUES ('ai_active', 'true')
  ON CONFLICT (key) DO NOTHING;

-- ── Structured usage log (observability) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_usage_log (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID REFERENCES tenants(id) ON DELETE SET NULL,
  user_id          TEXT,
  agent            TEXT,
  response_time_ms NUMERIC,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_tenant ON aria_usage_log(tenant_id, created_at);

-- ── Shared rate-limit counters (consistent across instances) ─────────────────
CREATE TABLE IF NOT EXISTS rate_limit_counters (
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  window_key TEXT NOT NULL,            -- e.g. '2026-06-01' (daily window)
  count      INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id, window_key)
);

-- ── Persistent ADK sessions (survive restarts / multi-instance) ──────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
  id               TEXT PRIMARY KEY,        -- "app_name:user_id:session_id"
  app_name         TEXT NOT NULL,
  user_id          TEXT NOT NULL,
  session_id       TEXT NOT NULL,
  tenant_id        UUID REFERENCES tenants(id) ON DELETE CASCADE,
  state            JSONB NOT NULL,          -- full Session.model_dump(mode="json")
  last_update_time DOUBLE PRECISION,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_lookup ON agent_sessions(app_name, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON agent_sessions(tenant_id);

-- ── Canvas persistence (Fase 2): one workspace per (tenant,user) for the MVP ─
CREATE TABLE IF NOT EXISTS canvas_workspaces (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  state      JSONB NOT NULL,                -- { nodes, branches, activeNodeId, activeBranchId }
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id)
);

CREATE TRIGGER canvas_workspaces_updated_at BEFORE UPDATE ON canvas_workspaces FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER rate_limit_counters_updated_at BEFORE UPDATE ON rate_limit_counters FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
