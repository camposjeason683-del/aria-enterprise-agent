-- 0007_proposal_fields.sql
-- submit_proposal() (y execute_proactive_sweep_auto) escriben `strategy`,
-- `recommendation` e `items` en aria_proposals, pero la tabla (0002) nunca tuvo
-- esas columnas → TODO insert de propuesta del barrido proactivo fallaba con
-- "column 'items' does not exist". La estructura de 3 niveles (estrategia /
-- recomendación / acción) + la lista de ítems consolidados son atributos de
-- primera clase de una propuesta, así que se agregan como columnas.
--
-- TODO ADITIVO y nullable (filas viejas no explotan; clientes viejos ignoran los
-- campos nuevos). Sin cambios de RLS ni de datos. Aplicar branch-DB primero.

ALTER TABLE aria_proposals ADD COLUMN IF NOT EXISTS strategy       TEXT;
ALTER TABLE aria_proposals ADD COLUMN IF NOT EXISTS recommendation TEXT;
ALTER TABLE aria_proposals ADD COLUMN IF NOT EXISTS items          JSONB;

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- ALTER TABLE aria_proposals
--   DROP COLUMN IF EXISTS items,
--   DROP COLUMN IF EXISTS recommendation,
--   DROP COLUMN IF EXISTS strategy;
