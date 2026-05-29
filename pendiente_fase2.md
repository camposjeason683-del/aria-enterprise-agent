# Arquitectura del Agente Supremo Empresarial (ARIA-OS) - PENDIENTE FASE 2

Este plan define la arquitectura funcional del agente, transformándolo en una herramienta agnóstica de negocio capaz de pensar, analizar, planificar y ejecutar usando la interfaz de líneas de tiempo.

## Visión General
El agente no es un simple chat; es un motor de decisiones (Decision Engine) que utiliza el *Canvas* (el espacio de trabajo con tarjetas) y la *Línea de Tiempo* (Timeline) para representar la realidad actual y simular realidades alternativas. Es totalmente agnóstico al modelo de negocio, dependiendo de las APIs/Bases de datos a las que se conecte.

## Los 3 Estados Operativos

### 1. Estado Pasivo (Comando y Ejecución)
El agente recibe instrucciones directas del usuario y actúa como un "creador de tableros".
*   **Manipulación Profunda de UI (Tools):** El agente cuenta con herramientas (CopilotKit actions) para invocar, crear, mover, redimensionar, destruir y **modificar profundamente** Widgets (tarjetas) en el canvas de forma dinámica. Cuando decimos modificar, hablamos por ejemplo de: agregar valores a un gráfico, actualizar etiquetas, cambiar colores, rehacer las fórmulas de los datos en tiempo real, etc.
*   **Ejemplo:** El usuario dice *"Muéstrame el rendimiento de la campaña X vs la Y"*. El agente limpia el canvas, genera dos tarjetas de tipo gráfico y las posiciona en pantalla.

### 2. Estado Reactivo (Dirigido por Eventos)
El agente está suscrito a eventos del sistema (Webhooks, colas de mensajes, triggers de BD).
*   **Comportamiento UI:** Cuando ocurre un evento crítico (Ej. *Fallo en servidor* o *Aprobación de factura requerida*), el agente **no interrumpe** el canvas actual. En su lugar, crea un **Nuevo Nodo/Commit** en la línea de tiempo.
*   **Interacción:** El usuario ve un nuevo nodo brillante en su línea de tiempo, hace clic en él, y viaja a esa versión del sistema donde el agente ya preparó las tarjetas relevantes para atender la emergencia.

### 3. Estado Proactivo (Análisis Autónomo y Predicción)
El agente cruza datos en segundo plano y busca anomalías de forma autónoma.
*   **Ramificación (Branching):** Este es el mayor poder de la línea de tiempo. Si el agente detecta un problema futuro, **crea una rama paralela (Simulación)** en la línea de tiempo.
*   **Ejemplo:** *"He notado un patrón inusual en las ventas de la región sur. He creado una rama llamada 'Simulación: Caída de stock Sur'. En esa línea de tiempo te he dejado un plan de reabastecimiento que puedes ejecutar con un clic."*

---

## Capacidades Base a Desarrollar (CopilotKit Tools)

Para lograr esto, necesitamos construir las siguientes herramientas (Tools) que el LLM podrá llamar:

1.  **`manage_canvas_widgets`**: Permite al LLM crear, actualizar o eliminar tarjetas en la pantalla actual, enviando un esquema JSON estandarizado que el frontend renderice (agnóstico al negocio). Esto incluye actualizar configuraciones completas de gráficos, fórmulas y datos crudos.
2.  **`create_timeline_branch`**: Permite al LLM bifurcar la línea de tiempo actual para mostrar proyecciones o escenarios "What-if" sin alterar la línea principal ("Main").
3.  **`execute_business_action`**: Un puente dinámico (Dynamic API router) que toma un `actionId` y un `payload` generado por el agente para impactar el mundo real (enviar correos, aprobar presupuestos, etc.).

---

## Preguntas Abiertas Pendientes para la Fase 2

1.  **Persistencia del Canvas:** Si el agente va a crear tarjetas dinámicamente, ¿tenemos una base de datos lista para guardar el estado del canvas (posición, tamaño, tipo de tarjeta) por cada nodo de la línea temporal, o prefieres que de momento lo manejemos todo en memoria del navegador?
2.  **El Formato de las Tarjetas:** Para que sea agnóstico, ¿estás de acuerdo en que todas las tarjetas compartan un mismo componente envoltorio (Wrapper) y que el agente simplemente pase un JSON de configuración para decir si adentro va un gráfico, un texto o una tabla?
3.  **Punto de Partida:** ¿Quieres que empecemos a implementar la herramienta (Tool) para el **Estado Pasivo**? Es decir, configurar CopilotKit para que el agente pueda manipular (crear/destruir/modificar) las tarjetas en la pantalla actual mediante un prompt en el chat.
