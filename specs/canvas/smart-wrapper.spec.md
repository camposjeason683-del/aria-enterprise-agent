# Spec — SmartWrapper Canvas Component (`canvas/smart-wrapper`)

> Track B · Sin dependencias · Invariante cardinal: coords por `animate` (FLIP),
> sin teletransporte ni remount.

## Story

Como usuario, las tarjetas se arrastran, hacen zoom y viajan por la línea de
tiempo de forma fluida sin saltos, y cualquier tipo de tarjeta hereda este
comportamiento por estar envuelto en `SmartWrapper`.

## Invariants

- **I1** — `x`, `y`, `width`, `height` los maneja el prop `animate` de Framer
  Motion, **no** `style` (preserva el FLIP; arregla el bug documentado en
  `sandbox/page.tsx:1736`). Solo `zIndex`/`transformOrigin` quedan en `style`.
- **I2** — Transición dinámica: al arrastrar, `duration: 0`; en viaje temporal,
  suave (~0.4s); el cálculo se hace en fase de render (no en `useEffect`).
- **I3** — El `key` de la tarjeta no cambia durante el viaje temporal (sin
  remount → se anima, no hace pop-in).

## Acceptance Criteria (BDD)

```gherkin
Scenario: Viaje temporal anima, no teletransporta
  Given una tarjeta en P1 en el nodo N1
  When el usuario viaja al nodo N2 donde la tarjeta está en P2
  Then la tarjeta anima de P1 a P2 (~0.4s), no salta

Scenario: El arrastre es instantáneo
  When el usuario arrastra una tarjeta
  Then sigue al cursor con duración de transición 0

Scenario: x/y/size NO están en style
  Given el render de SmartWrapper
  Then el objeto style no contiene x, y, width ni height
  And esas props están en animate

Scenario: Un tipo nuevo hereda el comportamiento
  Given un tipo de tarjeta nuevo envuelto en SmartWrapper
  Then soporta drag, zoom y animación temporal sin código extra
```

## Implementación

- `frontend/src/components/SmartWrapper.tsx`: extrae el `motion.div` externo
  (`sandbox/page.tsx:1691-1738`); props `card, draggingCardId, resizingCardId,
  shouldAnimateLayout, canvasSize, onDragEnd, onResizeStart, children`.
- `frontend/src/components/ContentRenderer.tsx`: generaliza Macro/Meso/Micro
  (`:2041-2255`); renderers registrables por `card.type` (kpi, inventory,
  saif-tracker).

## Tests

`frontend` con **vitest** (a agregar): `SmartWrapper.test.tsx` afirma que el
objeto `style` no contiene x/y/width/height y que `transition.duration` es 0 al
arrastrar. Validación visual del FLIP con screenshot/eval contra el preview.
