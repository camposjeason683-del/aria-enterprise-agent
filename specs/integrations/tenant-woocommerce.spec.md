# Spec — Per-Tenant WooCommerce Integration (`integrations/tenant-woocommerce`)

> Track A · Depende de S3 · Invariante cardinal: el sync de T usa solo creds de
> T y escribe `tenant_id=T`.

## Story

Como admin, conecto mi propia tienda WooCommerce; el sync usa mis credenciales
encriptadas y nunca las de otro tenant.

## Invariants

- **I1** — Las credenciales se guardan **encriptadas** en `tenant_integrations`;
  nunca en logs.
- **I2** — Solo un **admin** del tenant puede escribir credenciales (RLS
  `is_tenant_admin`).
- **I3** — El sync del tenant T usa solo las creds de T y escribe filas con
  `tenant_id=T` en `wc_orders_cache` / `daily_inventory_ledger`.

## Acceptance Criteria (BDD)

```gherkin
Scenario: Admin conecta su tienda
  Given un admin autenticado del tenant A
  When guarda url+key+secret de WooCommerce en Ajustes
  Then las creds quedan encriptadas bajo el tenant A
  And un employee de A no puede sobrescribirlas (RLS)

Scenario: El sync aísla tenants
  Given A y B conectaron cada uno su tienda
  When corre el cron de sync (itera tenants activos)
  Then el ledger de A se puebla solo desde la tienda de A
  And toda fila escrita tiene tenant_id=A

Scenario: Credenciales nunca en logs
  When el sync corre y loguea su progreso
  Then el log no contiene el consumer_key/secret
```

## Implementación

- `src/agents/sync_worker.py` + `src/tools/api_connector.py`: cargan creds desde
  `tenant_integrations` (desencriptadas con el helper de cifrado), iteran tenants
  activos con `asyncio.gather` + semáforo (sin colas externas para ~10 tenants).
- Cron: endpoint `/api/v1/cron/*` disparado por schedule de InsForge / scheduler.

## Tests

`tests/integrations/test_tenant_woocommerce.py` — unit: el cifrado round-trip y
la selección de creds por tenant con cliente fake. La verificación del sync real
contra WooCommerce + DB en vivo es Fase 4 (requiere proyecto InsForge + una
tienda de prueba).
