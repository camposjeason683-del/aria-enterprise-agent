# Spec — Persistent Agent Session (`infra/persistent-session`)

> Track A · Depende de S1, S2 · Invariante cardinal: la sesión sobrevive
> reinicios y multi-instancia.

## Story

Como usuario, mi conversación con el agente sobrevive reinicios del servidor y
funciona aunque distintas instancias del backend atiendan turnos consecutivos.

## Invariants

- **I1** — El state de la sesión persiste en `agent_sessions` por
  `(app_name, user_id, session_id)` (write-through en create/append).
- **I2** — Un reinicio (memoria limpia) no pierde un hilo: `get_session`
  hidrata desde InsForge si no está en memoria.
- **I3** — Las filas de sesión llevan `tenant_id` (para auditoría / RLS).

## Acceptance Criteria (BDD)

```gherkin
Scenario: La sesión persiste al crearse
  Given un InsForgeSessionService
  When se crea una sesión con state inicial
  Then se escribe una fila en agent_sessions con ese state

Scenario: La sesión sobrevive un "reinicio"
  Given una sesión creada y con un evento agregado
  When una instancia NUEVA del servicio (memoria vacía) hace get_session
  Then hidrata desde InsForge y devuelve la sesión con su evento

Scenario: append_event persiste el turno
  Given una sesión existente
  When se agrega un evento
  Then la fila persistida refleja el evento agregado
```

## Tests

`tests/infra/test_persistent_session.py` — adapter fake en memoria que hace un
round-trip real `Session.model_dump(mode="json") -> Session(**...)`, validando
la serialización. La verificación multi-instancia real contra Postgres se hace
contra el proyecto InsForge en vivo (Fase 0).
