-- 0008_automation_rules.sql
-- Fase 3: motor de reglas declarativas ("si métrica X cruza umbral → acción Y").
-- Per-tenant, calca el patrón de pedido_config (0006): RLS is_tenant_member.
-- TODO ADITIVO y reversible. Aplicar branch-DB primero → gate de aislamiento → prod.

CREATE TABLE IF NOT EXISTS automation_rules (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL,
    name        text NOT NULL,
    metric      text NOT NULL,                       -- p.ej. 'stockout_risk_max','net_margin_pct'
    op          text NOT NULL,                       -- '>','<','>=','<=','=='
    threshold   numeric NOT NULL,
    action      text NOT NULL DEFAULT 'create_proposal',
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE automation_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS automation_rules_tenant_isolation ON automation_rules;
CREATE POLICY automation_rules_tenant_isolation ON automation_rules
    USING (is_tenant_member(tenant_id))
    WITH CHECK (is_tenant_member(tenant_id));

-- Índice para el read de evaluación por tenant (enabled).
CREATE INDEX IF NOT EXISTS idx_automation_rules_tenant_enabled
    ON automation_rules (tenant_id, enabled);

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS automation_rules;
