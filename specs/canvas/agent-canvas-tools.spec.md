# Spec — Agent Canvas Tools (`canvas/agent-canvas-tools`)

> Track B · Depende de S7 · Invariante cardinal: las tools emiten text-tags
> válidos que el parser del frontend entiende; UI agnóstica al negocio.

## Story

Como usuario, cuando le pido al agente que arme una vista, crea/actualiza/borra
tarjetas en mi canvas (Estado Pasivo).

## Invariants

- **I1** — Las tools emiten el protocolo text-tag (`<create_card>`,
  `<update_card>`, `<delete_card>`) **exactamente** como lo espera
  `parseCardsFromMessage` (`sandbox/page.tsx:103-167`).
- **I2** — El JSON de la tarjeta cumple el schema `CardState` mínimo
  (al menos `title`; en "add" también `macroData` y un `type` válido).
- **I3** — Las tools son agnósticas al negocio (solo UI); los datos vienen de
  las tools de analista que corren bajo RLS, nunca de acá.

## Acceptance Criteria (BDD)

```gherkin
Scenario: El agente crea una tarjeta
  When manage_canvas_widgets(action="add", widget_id="card-sales", card_type="kpi",
       widget_config={title, macroData:{value}})
  Then devuelve un tag <create_card id="card-sales" type="kpi"> con JSON válido adentro
  And ese tag re-parsea con la MISMA regex del frontend a una tarjeta kpi

Scenario: El agente actualiza una tarjeta
  When manage_canvas_widgets(action="update", widget_id="card-sales", widget_config={...})
  Then devuelve <update_card id="card-sales"> (no crea una nueva)

Scenario: El agente elimina una tarjeta
  When manage_canvas_widgets(action="remove", widget_id="card-sales")
  Then devuelve <delete_card id="card-sales"/>

Scenario: Config malformada es rechazada
  When add sin "title" (o type inválido, o sin macroData)
  Then status="error" y NO se emite ningún tag
```

## Tests

`tests/canvas/test_agent_canvas_tools.py` — re-parsea el tag emitido con un port
Python de la regex de `parseCardsFromMessage` para probar compatibilidad real
(I1), y valida los rechazos (I2). Registradas en `skill_retriever._NODE_TOOLS`.
