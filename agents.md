# Aprendizajes y Mejores Prácticas (ARIA-OS + CopilotKit)

Este documento es un registro continuo de errores superados y éxitos arquitectónicos para no volver a cometer los mismos fallos en integraciones futuras. Todo agente que trabaje en este repositorio debe leer estas reglas de integración.

## 1. El Formato Estricto de OpenAI y Vercel AI SDK
**El Error:** `Type validation failed` en el frontend, recibiendo chunks JSON crudos en lugar de eventos de CopilotKit.
**La Causa:** Cuando se usa `OpenAIAdapter` en Next.js, éste usa el SDK oficial de OpenAI y Vercel AI SDK bajo el capó para conectarse a un endpoint compatible (FastAPI). Si el backend emite un SSE (`Server-Sent Events`) al que le faltan campos obligatorios como `created` o `finish_reason`, el SDK falla silenciosamente al parsear el stream de texto y vomita el JSON crudo hacia el frontend.
**La Regla de Oro:** Todo endpoint `chat/completions` simulado en Python DEBE cumplir la especificación estricta:
1. `data: {"id": "...", "object": "chat.completion.chunk", "created": 12345, "model": "...", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}\n\n`
2. `data: {"id": "...", "object": "chat.completion.chunk", "created": 12345, "model": "...", "choices": [{"index": 0, "delta": {"content": "Hola"}, "finish_reason": None}]}\n\n`
3. `data: {"id": "...", "object": "chat.completion.chunk", "created": 12345, "model": "...", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}\n\n`
4. `data: [DONE]\n\n`

## 2. Descubrimiento de Agentes y Endpoints (El error /info)
**El Error:** `useAgent: Agent 'default' not found after runtime sync (runtimeUrl=/api/copilotkit).`
**La Causa:** En versiones modernas (v1.5+), si no se provee un adaptador LLM (como `OpenAIAdapter`), CopilotKit espera que el endpoint remoto devuelva una lista de agentes al hacer un handshake. Si usas Next.js App Router sin exportar explícitamente `export const GET`, el handshake hacia `/info` falla con un 404/405.
**El Parche a Evitar:** Usar `agents__unsafe_dev_only={[{name: 'default'}]}` o `agent="default"` inyectado en el componente `<CopilotKit>` en el frontend causa crash de React (`agent.subscribe is not a function`) porque el motor asume una instancia activa de agente, no un mock.
**La Solución Estructural:** Usar **OpenAIAdapter** en `route.ts`. Este adaptador registra automáticamente la capacidad conversacional por defecto y actúa como el "agente proxy", liberándonos de tener que exponer el discovery protocol completo.

## 3. El error 405 Method Not Allowed (/threads)
**El Problema:** La consola del navegador muestra `GET /api/copilotkit/threads?agentId=default 405 (Method Not Allowed)`.
**El Por qué:** CopilotKit incluye funcionalidades para la persistencia de hilos (CopilotKit Cloud). El manejador `copilotRuntimeNextJSAppRouterEndpoint` no procesa peticiones GET a `/threads` si la persistencia no está configurada.
**La Práctica:** Es un "warning" benigno. El chat en memoria continuará funcionando normalmente. Para un producto puro de producción con persistencia total en ARIA-OS, se debe considerar omitir el wrapper de Next.js y consumir el SDK de Python directo (`CopilotKitSDK` y `add_fastapi_endpoint`) como puerto principal, pero para arquitecturas híbridas Vercel/FastAPI, ignorar este 405 es seguro mientras el flujo POST WebSocket/Stream siga activo.

## 4. El protocolo interno POST de CopilotKit
Cualquier intento manual de hacer `curl -X POST /api/copilotkit -d '{"messages": [...]}'` fallará con `Missing method field`. CopilotKit usa una carga útil tipo GraphQL estricta para la comunicación entre su UI en React y su backend (sea Next.js o Python). Nunca intentes parsear el payload crudo de CopilotKit a mano en Python; siempre delega en sus adaptadores (o imita un servicio base como el de OpenAI usando `OpenAIAdapter` en el medio).

## 5. UI Generativa / Headless en v1.5x (El motor AG-UI)
**El Problema:** Al construir una interfaz completamente personalizada (Headless), funciones clásicas como `appendMessage()` o variables como `visibleMessages` de `useCopilotChat` parecen ignorar las respuestas del asistente, dejando la interfaz congelada.
**La Causa:** En versiones 1.5x+, CopilotKit migró a un motor interno llamado "AG-UI". El hook público `useCopilotChat` expone `visibleMessages`, el cual está marcado en el código fuente como *DEPRECATED (versión vieja no-AG-UI)*. Esto causa que todos los *chunks* modernos (`TEXT_MESSAGE_END`) del asistente sean descartados silenciosamente. Además, `appendMessage` pierde sus capacidades de actualización optimista si el input nativo de CopilotKit no está montado.
**La Solución Estructural Definitiva:**
1. **Evitar `useCopilotChat`:** En arquitecturas Headless puras, importa directamente el motor interno: `import { useCopilotChatInternal } from "@copilotkit/react-core";`
2. **Usar `messages`:** Consume la variable `messages` (del hook interno), la cual sí contiene el arreglo procesado con soporte completo para AG-UI. Olvídate de `visibleMessages`.
3. **Usar `sendMessage`:** En lugar de `appendMessage`, utiliza `sendMessage({ id, role, content })` (o usa la tupla optimista si prefieres). `sendMessage` inyecta instantáneamente el mensaje del usuario en `messages`, eliminando la necesidad de emparchar el estado con `useState` locales para destrabar la UI.
