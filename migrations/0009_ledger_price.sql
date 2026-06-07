-- 0009_ledger_price.sql
-- XREG: precio diario por (producto, fecha) para forecasting demanda~precio
-- (paridad con BQML ARIMA_PLUS_XREG). El ledger ya es un snapshot diario por
-- producto; agregar el precio del día es natural. TODO ADITIVO y nullable —
-- filas viejas quedan price=NULL y forecast_sales cae al univariado (sin regresión).
-- La tabla ya tiene RLS (0005); no se toca la policy.

ALTER TABLE daily_inventory_ledger ADD COLUMN IF NOT EXISTS price NUMERIC;

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- ALTER TABLE daily_inventory_ledger DROP COLUMN IF EXISTS price;
