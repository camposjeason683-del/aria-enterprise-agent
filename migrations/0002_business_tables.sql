-- M2 — Business tables (net-new in InsForge), each scoped by tenant_id.
-- Column names follow src/specs/db_schema.json + the QC rules in README.md
-- (wc_orders_cache uses customer_name + date_created; status filtering enforced
-- at the app layer / pre_flight_validate_sql).
-- spec: specs/tenancy/tenant-isolation.spec.md

-- ── WooCommerce orders cache ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wc_orders_cache (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  order_id      BIGINT,
  customer_name TEXT,
  total         NUMERIC(12,2),
  status        TEXT,
  date_created  TIMESTAMPTZ,
  line_items    JSONB
);
CREATE INDEX IF NOT EXISTS idx_wc_orders_tenant        ON wc_orders_cache(tenant_id);
CREATE INDEX IF NOT EXISTS idx_wc_orders_tenant_status ON wc_orders_cache(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_wc_orders_tenant_date   ON wc_orders_cache(tenant_id, date_created);

-- ── Daily inventory ledger ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_inventory_ledger (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  date               DATE,
  product_id         TEXT,
  product_name       TEXT,
  stock_end_of_day   NUMERIC,
  sales_velocity     NUMERIC,
  production_detected NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_ledger_tenant      ON daily_inventory_ledger(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ledger_tenant_date ON daily_inventory_ledger(tenant_id, date);

-- ── Supplier catalog ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS supplier_catalog (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  product_id     TEXT,
  nombre_original TEXT,
  proveedor      TEXT,
  marca          TEXT,
  submarca       TEXT
);
CREATE INDEX IF NOT EXISTS idx_supplier_tenant ON supplier_catalog(tenant_id);

-- ── Strategic proposals + comments (ubiquitous language: proposal) ───────────
CREATE TABLE IF NOT EXISTS aria_proposals (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title            TEXT NOT NULL,
  problem          TEXT,
  proposed_action  TEXT,
  urgency          TEXT,
  status           TEXT NOT NULL DEFAULT 'pending',
  estimated_impact TEXT,
  risk             TEXT,
  notes            TEXT,
  category         TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at      TIMESTAMPTZ,
  approved_by      TEXT,
  executed_at      TIMESTAMPTZ,
  rejection_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_tenant        ON aria_proposals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_proposals_tenant_status ON aria_proposals(tenant_id, status);

CREATE TABLE IF NOT EXISTS proposal_comments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  proposal_id UUID NOT NULL REFERENCES aria_proposals(id) ON DELETE CASCADE,
  author      TEXT,
  content     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comments_tenant   ON proposal_comments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_comments_proposal ON proposal_comments(proposal_id);

-- ── Purchase order drafts ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS purchase_order_drafts (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'draft',
  items        JSONB,
  created_by   TEXT,
  audited_by   TEXT,
  label        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_po_tenant ON purchase_order_drafts(tenant_id);

-- ── Products master (minimal; extend as the catalog grows) ───────────────────
CREATE TABLE IF NOT EXISTS products (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  sku        TEXT,
  name       TEXT,
  price      NUMERIC(12,2),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id);
