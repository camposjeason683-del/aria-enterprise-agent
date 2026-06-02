# Spec — `canvas/timeline-reducer`

**Story:** Como usuario del Sandbox (canvas 4D + timeline git), cuando escribo, forkeo,
fusiono, rompo o reviero la línea temporal, el **árbol de nodos** se transforma con lógica
absoluta y predecible, sin que la conversación lineal de CopilotKit (`messages`) corrompa
la estructura.

**Fuente de verdad:** `nodes` (el árbol). `messages` se **deriva** del camino activo
(`getActivePath` → `compileMessagesForPath`) y nunca al revés.

## Invariants

- **I1 (fuente de verdad):** ningún reducer lee `messages`; cada uno es función pura
  `(state, args, idgen?) => state` de `{nodes, branches, activeNodeId, activeBranchId}`.
- **I2 (Bug-1 — fork mantiene su rama):** al escribir sobre un nodo del pasado, el nodo
  nuevo queda en la **rama nueva/activa**, jamás re-derivado a la rama del padre.
- **I3 (Bug-2 — revert poda con árbol post-borrado):** al revertir, la poda de ramas se
  computa contra el árbol **ya borrado**, no contra un snapshot previo.
- **I4 (alineación de IDs):** para todo nodo, `node.userMessage.id === node.id` (sobre eso
  se apoya la captura de la respuesta del asistente).
- **I5 (determinismo):** mismos inputs + mismo `idgen` ⇒ output deep-equal (sin `Date.now()`
  ni `Math.random()` adentro).

## Acceptance Criteria (Gherkin)

```gherkin
Scenario: Escribir en una hoja appendea en la rama activa
  Given una cadena lineal en "main" con hoja H activa
  When appendTurn({text})
  Then el nodo nuevo tiene parentId=H y branchId="main"
  And activeNodeId === el nodo nuevo

Scenario: Escribir en un nodo del pasado crea una rama nueva (Bug 1)
  Given un nodo P no-hoja en "main", activo, con activeBranchId="main"
  When appendTurn({text})
  Then se crea una rama nueva R (branches pasa de 1 a 2)
  And el nodo nuevo tiene branchId=R (R !== "main") y parentId=P
  And activeBranchId === R
  And el nodo nuevo NO quedó en "main"

Scenario: Primera escritura en una rama ghost parentea al fork point
  Given una rama R vacía con forkParentId=F
  And activeBranchId=R
  When appendTurn({text})
  Then el nodo nuevo tiene parentId=F y branchId=R
  And depth === nodes[F].depth + 1

Scenario: Revert borra el subárbol y poda ramas con el árbol post-borrado (Bug 2)
  Given "main" con A→B→C y una rama R forkeada en B con nodos B1,B2
  When revertTo({ancestorId: A})
  Then B, C, B1, B2 ya no existen
  And la rama R queda podada (sin nodos y con forkParentId borrado)
  And "main" se conserva
  And activeNodeId === A y activeBranchId === A.branchId

Scenario: Revert conserva una rama ghost cuyo fork point sobrevive
  Given una rama R forkeada en un nodo F que NO se borra, pero R no tiene nodos
  When revertTo a un ancestro que conserva F
  Then R se conserva (ghost) porque su forkParentId sigue vivo

Scenario: Merge A→B produce un nodo merge
  Given nodos A (rama X) y B (rama Y)
  When mergeNodes({nodeAId:A, nodeBId:B})
  Then el nodo merge tiene parentId=B y mergeParentId=A
  And una card presente en ambos toma la versión de A si A es más profunda
  And activeNodeId === el nodo merge

Scenario: Break desconecta y re-rootea
  Given B con parentId=A
  When breakNode({nodeId:B})
  Then B.parentId === null
  And las profundidades quedan contiguas desde las raíces

Scenario: Determinismo
  Given el mismo estado y el mismo idgen contador
  When se corre el mismo reducer dos veces
  Then ambos outputs son deep-equal
```

## Tests

`frontend/src/app/sandbox/timelineReducer.test.ts` (vitest, `idgen` contador determinista).
