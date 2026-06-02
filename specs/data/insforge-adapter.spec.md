# Spec — InsForge REST Adapter (`data/insforge-adapter`)

> Track A · Sin dependencias · Invariante cardinal: lectura de negocio ⇒
> cliente tenant-scoped; nunca silencia errores.

## Story

Como backend de ARIA-OS, necesito un adapter que hable la REST API de InsForge
(PostgREST: `GET/POST/PATCH/DELETE /api/database/records/{tabla}`,
`POST /api/database/rpc/{fn}`) **preservando la interfaz fluida** que las tools
ya usaban con `supabase-py` (`.table().select().eq()...execute() -> .data`),
para que la migración Supabase→InsForge toque **un módulo** en vez de ~50
funciones de tools.

## Invariants

- **I1** — Toda lectura de **datos de negocio** usa un cliente tenant-scoped que
  lleva el **JWT del usuario** (`Authorization: Bearer <jwt>`); las lecturas de
  **sistema** usan el cliente admin (`Bearer <INSFORGE_API_KEY>`).
- **I2** — El adapter **nunca** loguea el JWT ni la API key.
- **I3** — Un error de InsForge (≥400) **se levanta** como `InsForgeError`
  con su `code`+`message`; jamás devuelve `[]` silenciosamente.

## Acceptance Criteria (BDD)

```gherkin
Scenario: Select fluido traduce a PostgREST
  Given un cliente tenant para el JWT "jwt-A"
  When la tool llama .table("wc_orders_cache").select("id,total").eq("status","processing").limit(10).execute()
  Then el adapter emite GET /api/database/records/wc_orders_cache con status=eq.processing, select=id,total, limit=10
  And el header Authorization es "Bearer jwt-A"
  And retorna un objeto cuyo .data es el array parseado

Scenario: Error de InsForge se propaga, no se silencia
  Given la REST API responde 400 INVALID_QUERY
  When una tool ejecuta una query
  Then el adapter levanta InsForgeError con code="INVALID_QUERY"
  And no retorna lista vacía

Scenario: Secretos nunca se filtran
  Given un cliente con un JWT secreto
  When una request falla y se loguea el error
  Then el log no contiene el JWT

Scenario: Insert usa formato array y devuelve representación
  Given un cliente admin
  When .table("aria_proposals").insert({"title":"x"}).execute()
  Then el body HTTP es un array [ {"title":"x"} ]
  And el header Prefer incluye return=representation
  And .data es el array de filas creadas

Scenario: RPC para SQL crudo tenant-safe
  Given un cliente tenant para el JWT "jwt-A"
  When .rpc("exec_safe_read", {"q":"SELECT 1"})
  Then el adapter emite POST /api/database/rpc/exec_safe_read con Bearer jwt-A
  And .data es la respuesta del RPC
```

## Tests

`tests/data/test_insforge_adapter.py` — httpx mockeado con `MockTransport`:
URL/params, header `Authorization`, propagación de error, redacción de secreto,
formato array del insert, y el RPC.
