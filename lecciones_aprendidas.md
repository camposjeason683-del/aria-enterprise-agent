# Lecciones Aprendidas: Framer Motion y Animaciones Dinámicas en React

Este documento recopila las lecciones arquitectónicas y de implementación descubiertas al lidiar con animaciones complejas, arrastre (drag) y cambios de estado (línea de tiempo) usando `framer-motion` en Next.js/React.

## 1. El Peligro de los Estilos en Línea (Inline Styles) para Coordenadas
**El Error:** Asignar `style={{ x: clampedX, y: clampedY }}` directamente al componente `<motion.div>`.
**La Causa:** React procesa los estilos en línea aplicándolos inmediatamente al DOM durante la fase de renderizado. Cuando se cambia de un nodo en la línea de tiempo a otro, las nuevas coordenadas reemplazan instantáneamente a las anteriores. Framer Motion no tiene oportunidad de animar la diferencia (el "FLIP") porque el elemento "se teletransporta".
**La Regla:** Para propiedades que deben ser animadas (como posiciones, tamaño, o escala) al ocurrir un cambio de estado global (ej. retroceder en el tiempo), **elimina** `x` e `y` del prop `style` y pásalas exclusivamente al prop `animate={{ x, y }}`. Framer Motion se encargará de gestionar el movimiento fluido.

## 2. La Sincronización del Estado de Animación (Render vs useEffect)
**El Error:** Depender de `useEffect` para actualizar un booleano (ej. `shouldAnimateLayout`) que habilite las animaciones al cambiar de nodo.
**La Causa:** `useEffect` se ejecuta *después* del renderizado. Si el cambio de coordenadas y el estado del nodo cambian en el renderizado inicial, pero la animación se habilita después en el `useEffect`, el componente ya se renderizó en la nueva posición de forma instantánea. 
**La Regla:** La detección de cambios críticos (como el cambio de `activeNodeId`) debe hacerse **síncronamente durante la fase de render**. Se pueden usar `useRef` para guardar el nodo anterior y compararlo durante el cuerpo de la función (Render) para calcular variables derivadas (ej. `const isTransitioning = prevNodeRef.current !== activeNodeId`), asegurando que `transition={{ duration: 0.8 }}` se aplique en el *mismo* ciclo de render en que cambian las coordenadas.

## 3. Dinamismo en el prop `transition`
**El Error:** Usar una transición fija o usar `layout` globalmente, lo cual causaba "rebotes" (bouncing) o comportamientos erráticos al arrastrar las tarjetas.
**La Causa:** Cuando arrastramos un elemento, queremos que siga al cursor instantáneamente (duración 0). Cuando cambiamos de estado o hacemos "zoom", queremos una transición suave (duración 0.3 a 0.8).
**La Regla:** El prop `transition` debe ser completamente dinámico. 
```tsx
transition={{
  type: "tween",
  ease: "easeInOut",
  duration: isDragging ? 0 : isTransitioning ? 0.8 : 0
}}
```
Esto separa limpiamente las interacciones instantáneas de los eventos guiados por el sistema.

## 4. Separación de Scale y Layout (Width/Height)
**El Error:** Mezclar cambios de `width`/`height` y `scale` en los estilos en línea causando que las tarjetas saltaran o perdieran el foco del mouse durante la animación de redimensionamiento (Zoom de Macro a Micro).
**La Causa:** Modificar las dimensiones reales del layout instantáneamente interrumpe los cálculos internos de `drag` de Framer Motion. 
**La Regla:** Las propiedades `width`, `height` y `scale` también deben ser controladas por el prop `animate`. Además, es crucial definir el `transformOrigin: 'top left'` estáticamente en el prop `style` para asegurar que todas las animaciones de escala comiencen desde el mismo punto predecible, evitando desfases extraños.

## 5. El Impacto de `key` en el Desmontaje
**El Error:** Cambiar agresivamente el `key` del contenedor de las tarjetas al cambiar de estado en la línea temporal.
**La Causa:** React destruye por completo y vuelve a montar el componente cuando su `key` cambia. Si la tarjeta se desmonta, es imposible animar su transición desde las coordenadas del Nodo A a las del Nodo B; en su lugar, simplemente aparece en la nueva ubicación (pop-in).
**La Regla:** Para animar la modificación de un elemento existente a través del tiempo, su `key` **no debe cambiar**. Se deben animar sus props internos (coordenadas, tamaño) mientras el elemento sobrevive en el DOM.

---
**Resumen:** Confía el control de la posición (`x`, `y`, `width`, `height`) a `animate` de Framer Motion y retíralo de React `style`. Controla las duraciones dinámicamente (`isDragging`, `isResizing`, `isTransitioning`) calculando los cambios en la fase de render, no como efectos secundarios.
