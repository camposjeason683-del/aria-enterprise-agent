# Spec — Card Repertoire (`canvas/card-templates`)

> Track B · Depende de S8 (agent-canvas-tools) · Schema canónico: `CardState` en
> `frontend/src/app/sandbox/timelineReducer.ts`.

## Story

Como usuario, quiero un **repertorio curado de tarjetas pre-construidas** que pueda
**insertar con 1 click** (al instante, datos de muestra), **rellenar con datos reales**
pidiéndoselo al agente, y **modificar** seleccionando una tarjeta y escribiéndole al
agente qué cambiar.

## Invariants

- **I1 — Pureza & determinismo:** `cardTemplates.ts` no depende de React/JSX ni usa
  `Date.now`/`Math.random`. `instantiateTemplate(tpl, idGen, turnId, index)` es puro:
  mismos inputs + mismo `idGen` ⇒ output deep-equal.
- **I2 — Schema válido:** cada template cumple el `CardState` que el renderer
  (Macro/Meso/MicroBody) y el validador backend (`canvas.py:_validate_card`) aceptan:
  `macroData.value` no vacío; `mesoData` con `chartData[]` **o** `bullets[]`;
  `chartData` = `{label:str, value:number}`; `tableRows` = arrays de strings;
  `type ∈ {kpi, inventory, saif-tracker}`.
- **I3 — Insert local, sin agente:** insertar un template es una mutación de UI
  (`setNodes` agrega la card a `activeCards` del nodo activo), sin request al agente.
- **I4 — Modificar = update sobre id existente:** al modificar una tarjeta seleccionada,
  el agente emite `<update_card id="<id>">` con el id literal de la card viva (el parser
  del front solo aplica update si el id ya existe).
- **I5 — Sin drift:** el schema descrito en el prompt (`CANVAS_PROTOCOL` en `config.py`)
  y los templates (`cardTemplates.ts`) referencian a `CardState` como fuente única.

## Acceptance Criteria (BDD)

```gherkin
Scenario: Insertar una plantilla con 1 click (instantáneo, sin agente)
  Given el repertorio de ~10 plantillas
  When el usuario hace click en "Ventas mensuales"
  Then aparece una card kpi en el canvas al instante
  And NO se dispara ninguna request al endpoint del agente
  And la card queda persistida en activeCards del nodo activo

Scenario: instantiateTemplate produce un CardState completo
  When se instancia un template con un idGen contador en el índice 0
  Then la card tiene id del idGen, zoom="macro", position {x:32,y:12},
       updatedInTurn=<nodo>, y macro/meso/micro del template

Scenario: Rellenar con datos reales (vía agente)
  Given una card de muestra insertada
  When el usuario pulsa "Datos reales"
  Then se envía un mensaje pidiendo al agente rellenar ese widget_id bajo RLS
  And el agente consulta datos + emite <update_card id="<id>"> (o pide aclaración)

Scenario: Modificar una card seleccionada
  Given una card seleccionada en el canvas
  When el usuario escribe "cambiá el valor a $20,000" en el chat
  Then el mensaje lleva el bloque [CONTEXTO: TARJETA SELECCIONADA] con su spec
  And el agente actualiza SOLO esa card (update_card) sin crear nuevas

Scenario: Template inválido es imposible (drift guard)
  Given cualquier template del repertorio
  Then cumple las invariantes que canvas.py:_validate_card exige (test cross-check)
```

## Tests

- `frontend/src/app/sandbox/cardTemplates.test.ts` (vitest): determinismo de
  `instantiateTemplate`, grid de posición, y cross-check de las invariantes de schema
  para los ~10 templates (I1/I2/I5).
- `tests/canvas/test_agent_canvas_tools.py` (pytest): validación por tipo + shape-guards
  de `manage_canvas_widgets` (respalda I2/I4 del lado backend).
- Ola 2 (UI) se valida end-to-end con Preview MCP (insert instantáneo, selección+modify,
  rellenar-con-datos, deselect, regresión de overwrite).
