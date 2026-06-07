-- 0010_ledger_unique.sql
-- KEYSTONE ETL idempotency: exactly one ledger row per (tenant, day, product).
-- Lets compile_ledger_for_tenant() UPSERT (on_conflict tenant_id,date,product_id)
-- instead of accumulating duplicates that would double-count sales_velocity.
--
-- ADITIVA pero NO vacía de precondición: la creación del UNIQUE FALLA si ya existen
-- duplicados. Verificar/dedupe ANTES de aplicar (ver el query de chequeo abajo).
-- La tabla ya tiene RLS (0005); no se toca la policy. Postgres trata NULLs como
-- distintos, así que filas legacy con product_id/date NULL no rompen la constraint.

-- Precondición (debe devolver 0 filas):
--   SELECT tenant_id, date, product_id, count(*)
--   FROM daily_inventory_ledger
--   WHERE product_id IS NOT NULL AND date IS NOT NULL
--   GROUP BY 1,2,3 HAVING count(*) > 1;

ALTER TABLE daily_inventory_ledger
  ADD CONSTRAINT daily_inventory_ledger_tenant_date_product_key
  UNIQUE (tenant_id, date, product_id);

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- ALTER TABLE daily_inventory_ledger
--   DROP CONSTRAINT IF EXISTS daily_inventory_ledger_tenant_date_product_key;
