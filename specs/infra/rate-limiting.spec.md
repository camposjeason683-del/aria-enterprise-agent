# Spec — Per-Tenant Rate Limiting (`infra/rate-limiting`)

> Track A · Depende de S1, S2 · Invariante cardinal: cuota por tier, contador
> compartido; nunca drop silencioso.

## Story

Como plataforma, aplico cuotas de requests por plan por `(tenant, user)` de
forma consistente entre instancias del backend.

## Invariants

- **I1** — El contador vive en `rate_limit_counters` (tabla compartida), no en
  memoria de proceso → consistente entre instancias.
- **I2** — La cuota depende del tier de la suscripción: Free 20/día, Pro
  ilimitado, Enterprise ilimitado. Tier desconocido ⇒ trato como Free.
- **I3** — Exceder devuelve `allowed=False, remaining=0` (el caller responde
  429); nunca se descarta en silencio.

## Acceptance Criteria (BDD)

```gherkin
Scenario: Tope diario del tier Free
  Given el tenant A (Free, 20/día) que ya consumió 20 hoy
  When el usuario hace el request 21
  Then check_rate_limit devuelve allowed=False, remaining=0

Scenario: Bajo la cuota consume y reporta lo que queda
  Given el tenant A (Free) con 5 consumidos hoy
  When hace 1 request
  Then allowed=True y remaining=14
  And el contador del día queda en 6

Scenario: Tier Pro es ilimitado
  Given el tenant B en Pro
  Then check_rate_limit devuelve allowed=True, remaining=None y no toca el contador

Scenario: Contador compartido (multi-instancia)
  Given 20 consumidos hoy (persistidos en rate_limit_counters)
  When otra instancia evalúa el request 21
  Then lo rechaza (lee el contador compartido, no memoria local)
```

## Tests

`tests/infra/test_rate_limiting.py` — cliente fake con contador en memoria que
emula la tabla compartida; `day_key` inyectado para determinismo.
