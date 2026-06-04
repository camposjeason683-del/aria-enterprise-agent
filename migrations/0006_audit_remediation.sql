-- 0006_audit_remediation.sql
-- Fase B de la remediación de auditoría. TODO ADITIVO y reversible (sin cambios
-- destructivos de datos). Aplicar en un BRANCH DB de InsForge primero, correr
-- scripts/verify_isolation.py (gate 2-tenant) y recién entonces merge a prod.
--
-- Rollback: cada objeto tiene su DROP comentado al final.

-- ── P1: índices de texto (trgm) para los ILIKE '%...%' de hot-path ───────────
-- Sin esto, cada calc/búsqueda por nombre de producto/proveedor es un full scan
-- de la partición del tenant. pg_trgm hace que ILIKE '%x%' use índice GIN.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_ledger_product_name_trgm
    ON daily_inventory_ledger USING gin (product_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_products_name_trgm
    ON products USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_supplier_proveedor_trgm
    ON supplier_catalog USING gin (proveedor gin_trgm_ops);

-- ── P1: índices para los WHERE/ORDER BY reales ──────────────────────────────
-- Sirve el "última fecha del ledger" (ORDER BY date DESC LIMIT 1) como top-1
-- index-only, y los lookups por (tenant, fecha) / (tenant, producto).
CREATE INDEX IF NOT EXISTS idx_ledger_tenant_date_desc
    ON daily_inventory_ledger (tenant_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_tenant_product
    ON daily_inventory_ledger (tenant_id, product_name);

-- purchase_order_drafts se filtra por status en varios tools; hoy solo hay (tenant_id).
CREATE INDEX IF NOT EXISTS idx_po_drafts_tenant_status
    ON purchase_order_drafts (tenant_id, status);

-- wc_orders_cache: los analytics filtran status + ventana de date_created juntos.
CREATE INDEX IF NOT EXISTS idx_orders_tenant_status_date
    ON wc_orders_cache (tenant_id, status, date_created);

-- ── pedido_config: tabla opcional que batch_purchase_orders consulta ─────────
-- Hoy no existe → el tool cae a defaults con try/except (no rompe, pero hace un
-- RTT que siempre falla). Esta tabla la hace explícita y por-tenant (RLS).
CREATE TABLE IF NOT EXISTS pedido_config (
    tenant_id        uuid NOT NULL,
    transit_days     integer NOT NULL DEFAULT 3,
    coverage_days    integer NOT NULL DEFAULT 7,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id)
);
ALTER TABLE pedido_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pedido_config_tenant_isolation ON pedido_config;
CREATE POLICY pedido_config_tenant_isolation ON pedido_config
    USING (is_tenant_member(tenant_id))
    WITH CHECK (is_tenant_member(tenant_id));

-- ── M1: contador de rate-limit atómico (SECURITY DEFINER) ───────────────────
-- Reemplaza el read-then-write last-write-wins de rate_limiter.py (sub-cuenta bajo
-- ráfaga). Devuelve el valor ya incrementado. Cablear desde rate_limiter en una
-- pasada de código posterior (no aplicar el código hasta que el RPC exista).
CREATE OR REPLACE FUNCTION increment_rate_counter(
    p_tenant_id uuid, p_user_id text, p_window_key text, p_limit integer
) RETURNS TABLE(count integer, allowed boolean)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_count integer;
BEGIN
    INSERT INTO rate_limit_counters (tenant_id, user_id, window_key, count)
    VALUES (p_tenant_id, p_user_id, p_window_key, 1)
    ON CONFLICT (tenant_id, user_id, window_key)
    DO UPDATE SET count = rate_limit_counters.count + 1
    RETURNING rate_limit_counters.count INTO v_count;
    RETURN QUERY SELECT v_count, (v_count <= p_limit);
END;
$$;

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- DROP FUNCTION IF EXISTS increment_rate_counter(uuid, text, text, integer);
-- DROP TABLE IF EXISTS pedido_config;
-- DROP INDEX IF EXISTS idx_orders_tenant_status_date, idx_po_drafts_tenant_status,
--   idx_ledger_tenant_product, idx_ledger_tenant_date_desc,
--   idx_supplier_proveedor_trgm, idx_products_name_trgm, idx_ledger_product_name_trgm;
