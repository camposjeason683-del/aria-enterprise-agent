# Spec — Tenant Data Isolation (`tenancy/tenant-isolation`) ⚠️ crítica

> Track A · Depende de S1, S2 · **Invariante cardinal de toda la plataforma.**

## Story

Como empresa, mis datos son invisibles para toda otra empresa, **incluso si el
agente escribe SQL crudo que olvida un filtro**.

## Invariants

- **I1 (cardinal)** — Para cualquier usuario autenticado del tenant T, ningún
  path devuelve una fila con `tenant_id ≠ T`.
- **I2** — El aislamiento lo fuerza **RLS en la DB** vía `is_tenant_member()`,
  no filtros `.eq()` a nivel app.
- **I3** — El path de SQL crudo (`exec_safe_read`) corre `SECURITY INVOKER` bajo
  el JWT del usuario → RLS aplica.
- **I4** — Los helpers usados en políticas son `SECURITY DEFINER` (sin RLS
  recursivo / OOM).

## Acceptance Criteria (BDD)

```gherkin
Scenario: Query de tool acotada al tenant
  Given el tenant A con 3 órdenes y el tenant B con 5
  And un usuario autenticado del tenant A
  When la tool de ventas lista órdenes
  Then se devuelven exactamente 3, todas con tenant_id=A

Scenario: SQL crudo del LLM no cruza tenants
  Given un usuario autenticado del tenant A
  When execute_safe_read_query corre "SELECT * FROM wc_orders_cache" (sin filtro)
  Then solo se devuelven filas del tenant A y cero de B

Scenario: Agregado sin filtro sigue acotado
  When un usuario de A corre "SELECT count(*) FROM aria_proposals"
  Then el conteo es solo el de A

Scenario: Escritura cross-tenant rechazada
  Given un usuario del tenant A
  When una escritura intenta tenant_id=B
  Then RLS la rechaza (WITH CHECK)
```

## Implementación

- Migración `migrations/0005_rls_policies.sql` (ENABLE RLS + `tenant_isolation`).
- Funciones en `migrations/0004_functions.sql` (`is_tenant_member` DEFINER,
  `exec_safe_read` INVOKER).
- El backend usa `get_tenant_client(jwt)` (S1) para todo dato de negocio.

## Tests

`tests/tenancy/test_tenant_isolation.py` — **test de aislamiento 2-tenants**:
siembra datos de A y B, y con el JWT de A verifica (i) tool normal, (ii)
`execute_safe_read_query` con SELECT sin filtro, (iii) agregado sin filtro →
cero filas de B en los tres casos. **Requiere el proyecto InsForge en vivo y se
corre contra un branch** (gate del cutover, Fase 3). Cross-check:
`GET /api/database/policies`.
