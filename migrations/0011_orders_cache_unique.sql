-- 0011_orders_cache_unique.sql
-- Idempotent WooCommerce sync: one cache row per (tenant, order). Lets sync_worker
-- UPSERT (on_conflict tenant_id,order_id) so a re-sync updates orders in place
-- instead of duplicating them (which would double-count sales_velocity downstream).
--
-- ADITIVA. Precondición (debe devolver 0 filas) — verificar antes de aplicar:
--   SELECT tenant_id, order_id, count(*) FROM wc_orders_cache
--   WHERE order_id IS NOT NULL GROUP BY 1,2 HAVING count(*) > 1;
-- Postgres trata NULLs como distintos → filas legacy con order_id NULL no rompen.
-- La tabla ya tiene RLS (0005); no se toca la policy.

ALTER TABLE wc_orders_cache
  ADD CONSTRAINT wc_orders_cache_tenant_order_key UNIQUE (tenant_id, order_id);

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- ALTER TABLE wc_orders_cache DROP CONSTRAINT IF EXISTS wc_orders_cache_tenant_order_key;
