-- 0014_billing_fields.sql
-- Stripe linkage on tenants for billing (M7). Additive/nullable — existing tenants
-- keep working (subscription_status already defaults to 'active'). The webhook maps a
-- Stripe customer → tenant via stripe_customer_id. La tabla ya tiene RLS (0005).

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id     TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS current_period_end     TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_tenants_stripe_customer ON tenants(stripe_customer_id);

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- ALTER TABLE tenants DROP COLUMN IF EXISTS stripe_customer_id;
-- ALTER TABLE tenants DROP COLUMN IF EXISTS stripe_subscription_id;
-- ALTER TABLE tenants DROP COLUMN IF EXISTS current_period_end;
