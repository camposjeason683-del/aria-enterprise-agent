# Spec — Canvas Persistence (`canvas/canvas-persistence`)

> Track B · Depende de S2, S3 · Invariante cardinal: canvas persiste por
> (tenant, user), aislado por RLS.

## Story

Como usuario, mi canvas (tarjetas + timeline) se guarda en mi cuenta y está
disponible en cualquier dispositivo.

## Invariants

- **I1** — El estado persiste en `canvas_workspaces` por `(tenant_id, user_id)`,
  aislado por RLS (reemplaza el `localStorage` de `sandbox/page.tsx:311-384`).
- **I2** — Cargar en otro dispositivo restaura el mismo estado (nodes, branches,
  active).
- **I3** — Ningún tenant lee el workspace de otro.

## Acceptance Criteria (BDD)

```gherkin
Scenario: El canvas persiste entre dispositivos
  Given un usuario acomodó tarjetas en el dispositivo 1 (guardado en canvas_workspaces)
  When abre ARIA-OS en el dispositivo 2
  Then se restauran las mismas tarjetas y timeline

Scenario: Debounce de guardado
  Given el usuario arrastra varias tarjetas seguidas
  Then el guardado se hace con debounce (no una escritura por frame)

Scenario: El workspace está aislado por tenant
  Given un usuario del tenant A guardó un workspace
  When un usuario del tenant B consulta workspaces
  Then B no ve ninguno de A (RLS)
```

## Implementación

- `frontend/src/lib/insforge.ts`: cliente `@insforge/sdk` (tenant-scoped por el
  access token del usuario) con `loadWorkspace()` / `saveWorkspace(state)`.
- `sandbox/page.tsx`: reemplazar los `localStorage.*` por load on-mount +
  save con debounce; el estado es `{ nodes, branches, activeNodeId, activeBranchId }`.
- Tabla `canvas_workspaces` (`migrations/0003`) + RLS (`migrations/0005`).

## Tests

`tests/canvas/test_canvas_persistence.ts` (vitest) — `saveWorkspace`/`loadWorkspace`
round-trip con SDK mockeado. El aislamiento por tenant se valida contra el
proyecto InsForge en vivo (RLS, Fase 4).
