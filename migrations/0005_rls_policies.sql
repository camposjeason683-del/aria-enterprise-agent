-- M5 — RLS cutover (HIGHEST-RISK STEP). Apply in an InsForge backend BRANCH and
-- only merge after the 2-tenant isolation test (tests/tenancy) is green.
-- spec: specs/tenancy/tenant-isolation.spec.md
--
-- Every business table: full tenant isolation via is_tenant_member(tenant_id),
-- with both USING (reads) and WITH CHECK (writes) so a row can never be read or
-- written across tenants.

-- ── Business data ────────────────────────────────────────────────────────────
ALTER TABLE wc_orders_cache         ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_inventory_ledger  ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_catalog        ENABLE ROW LEVEL SECURITY;
ALTER TABLE aria_proposals          ENABLE ROW LEVEL SECURITY;
ALTER TABLE proposal_comments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_drafts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE products                ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON wc_orders_cache        FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON daily_inventory_ledger FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON supplier_catalog       FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON aria_proposals         FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON proposal_comments      FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON purchase_order_drafts  FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON products               FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));

-- ── Canvas + sessions + usage (tenant-scoped) ────────────────────────────────
ALTER TABLE canvas_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE aria_usage_log    ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_counters ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON canvas_workspaces   FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON agent_sessions      FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON aria_usage_log      FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));
CREATE POLICY tenant_isolation ON rate_limit_counters FOR ALL USING (is_tenant_member(tenant_id)) WITH CHECK (is_tenant_member(tenant_id));

-- ── Tenancy core ─────────────────────────────────────────────────────────────
ALTER TABLE tenants             ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_users        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_plugins      ENABLE ROW LEVEL SECURITY;

-- Members can see their own tenant + the membership rows of their tenant.
CREATE POLICY tenant_read   ON tenants        FOR SELECT USING (is_tenant_member(id));
CREATE POLICY members_read  ON tenant_users   FOR SELECT USING (is_tenant_member(tenant_id));
CREATE POLICY plugins_read  ON tenant_plugins FOR SELECT USING (is_tenant_member(tenant_id));

-- Integrations: members read; only admins write (encrypted WooCommerce creds).
CREATE POLICY ti_read  ON tenant_integrations FOR SELECT USING (is_tenant_member(tenant_id));
CREATE POLICY ti_write ON tenant_integrations FOR ALL    USING (is_tenant_admin(tenant_id)) WITH CHECK (is_tenant_admin(tenant_id));
