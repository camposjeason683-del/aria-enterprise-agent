# ARIA-OS — Roadmap Oficial (Spec-Driven)
### Migración a InsForge + SaaS Multi-Tenant + Fase 2

> **Fuente única de verdad.** Este documento reemplaza a los planes previos
> (`pendiente_fase2.md` y `saas_packaging_plan.md`, eliminados). Última
> actualización: 2026-06-01.

## Context

ARIA-OS (Google ADK 2.1 + FastAPI + Next.js/CopilotKit) es un agente "COO virtual" **monousuario codeado para Supabase**. Se migra a **InsForge** (BaaS real del usuario, donde ya corre su app "Cinco"), se vuelve **SaaS para ~10 empresas × ~20 empleados (~200 usuarios, pico 10–30 req)** y se le da al agente "manos" sobre el canvas (**Fase 2 Estado Pasivo**).

El InsForge conectado (`mpfn9xu6.us-west.insforge.app`) es **Cinco**, no ARIA-OS → ARIA-OS tendrá su **propio proyecto InsForge**. InsForge = PostgreSQL + PostgREST, RLS estilo Supabase (`auth.uid()`, helpers `SECURITY DEFINER`), REST API (`/api/database/records/{t}`, `/rpc/{fn}`, `/migrations`), JWT HS256, backend branches, compute services (Fly.io). **No hay SDK Python** → el backend usa la REST API vía un adapter httpx.

**Decisiones del usuario:** (1) migrar a InsForge; (2) paralelo SaaS base + Fase 2 Pasivo; (3) billing diferido; (4) canvas en DB por tenant; (5) roles admin/empleado.

---

## Metodología: SpecDD ⇄ BDD ⇄ TDD

Cada feature se entrega en simbiosis:
- **SpecDD** — `specs/<area>/<feature>.spec.md` = fuente de verdad: **Story + Invariants + Acceptance Criteria + Scenarios**.
- **BDD** — cada Acceptance Criterion en **Gherkin** (Given/When/Then), legible por no-técnicos.
- **TDD** — cada Scenario tiene un test literal en `tests/<area>/<feature>.test.{py,ts}` con `# spec: specs/<area>/<feature>.spec.md`. Ciclo **RED → GREEN → REFACTOR**; cada test invoca un helper de aserción de invariante.

**Lenguaje ubicuo:** `tenant` (empresa), `employee`/`admin` (rol), `proposal`, `order`, `inventory ledger`, `canvas card`, `timeline node`, `workspace`.

---

## Catálogo de Specs

| # | Spec | Área | Track | Depende de | Invariante cardinal |
|---|------|------|-------|-----------|---------------------|
| S1 | `data/insforge-adapter` | data | A | — | Lectura de negocio ⇒ cliente tenant-scoped; nunca silencia errores |
| S2 | `auth/tenant-auth` | auth | A | S1 | Sin JWT verificado no hay agente; tenant/role server-side |
| S3 | `tenancy/tenant-isolation` | tenancy | A | S1,S2 | **Ningún path devuelve fila de otro tenant (ni en SQL crudo)** |
| S4 | `infra/persistent-session` | infra | A | S1,S2 | La sesión sobrevive reinicios y multi-instancia |
| S5 | `infra/rate-limiting` | infra | A | S1,S2 | Cuota por tier, contador compartido; nunca drop silencioso |
| S6 | `integrations/tenant-woocommerce` | integrations | A | S3 | El sync de T usa solo creds de T y escribe `tenant_id=T` |
| S7 | `canvas/smart-wrapper` | canvas | B | — | Coords por `animate` (FLIP), sin teletransporte ni remount |
| S8 | `canvas/agent-canvas-tools` | canvas | B | S7 | Tools emiten text-tags válidos; UI agnóstica al negocio |
| S9 | `canvas/canvas-persistence` | canvas | B | S2,S3 | Canvas persiste por (tenant,user), aislado por RLS |

---

## Las Specs

### S1 — `specs/data/insforge-adapter.spec.md`
**Story:** Como backend de ARIA-OS, necesito un adapter que hable la REST API de InsForge preservando la interfaz fluida que las tools ya usan, para que la migración toque 1 módulo y no ~50 funciones.
**Invariants:** (I1) toda lectura de negocio usa cliente tenant-scoped con el JWT del usuario; las de sistema usan el cliente admin. (I2) nunca loguea JWT ni API key. (I3) un error de InsForge se levanta, jamás devuelve `[]`.
```gherkin
Scenario: Select fluido traduce a PostgREST
  Given un cliente tenant para el JWT "jwt-A"
  When la tool llama .table("wc_orders_cache").select("id,total").eq("status","processing").limit(10).execute()
  Then el adapter emite GET /api/database/records/wc_orders_cache?status=eq.processing&select=id,total&limit=10
  And el header Authorization es "Bearer jwt-A"
  And retorna un objeto cuyo .data es el array parseado

Scenario: Error de InsForge se propaga, no se silencia
  Given la REST API responde 400 INVALID_QUERY
  When una tool ejecuta una query
  Then el adapter levanta un error con el código y mensaje de InsForge
  And no retorna lista vacía

Scenario: Secretos nunca se filtran
  When cualquier request del adapter se loguea
  Then el log no contiene ni el JWT ni la API key
```
**Tests:** `tests/data/insforge_adapter.test.py` (mock httpx: URL/headers/error/redacción).

### S2 — `specs/auth/tenant-auth.spec.md`
**Story:** Como empleado de una empresa, me autentico con InsForge y cada request del agente corre bajo mi identidad y mi tenant, de modo que solo toco datos de mi empresa.
**Invariants:** (I1) sin JWT InsForge verificado no se invoca el agente. (I2) `tenant_id`+`role` se resuelven server-side desde `tenant_users`, nunca del cliente. (I3) usuario sin fila en `tenant_users` es rechazado (no hay tenant "default").
```gherkin
Scenario: Request no autenticado rechazado
  Given un POST /api/v1/chat sin header Authorization
  Then retorna 401 y el agente nunca se invoca

Scenario: JWT válido resuelve tenant y siembra la sesión
  Given un JWT InsForge válido del usuario "u1" del tenant "A" como "employee"
  When se llama POST /api/v1/chat
  Then el state de la sesión ADK contiene tenant_id="A", user_id="u1", role="employee"
  And el contextvar expone "A" a la capa de datos

Scenario: user_id manipulado se ignora
  Given un request con form user_id="admin-de-B" pero el subject del JWT es "u1"
  Then la identidad se toma del JWT ("u1"), no del form
```
**Tests:** `tests/auth/tenant_auth.test.py`.

### S3 — `specs/tenancy/tenant-isolation.spec.md`  ⚠️ spec crítica de seguridad
**Story:** Como empresa, mis datos son invisibles para toda otra empresa, incluso si el agente escribe SQL crudo que olvida un filtro.
**Invariants:** (I1, cardinal) para cualquier usuario autenticado de tenant T, ningún path devuelve una fila con `tenant_id ≠ T`. (I2) el aislamiento lo fuerza RLS vía `is_tenant_member()`, no `.eq()` app-level. (I3) el path de SQL crudo (`exec_safe_read`) corre `SECURITY INVOKER` bajo el JWT del usuario. (I4) helpers en políticas son `SECURITY DEFINER` (sin RLS recursivo/OOM).
```gherkin
Scenario: Query de tool acotada al tenant
  Given el tenant A tiene 3 órdenes y el tenant B tiene 5
  And un usuario autenticado del tenant A
  When la tool de ventas lista órdenes
  Then se devuelven exactamente 3, todas con tenant_id=A

Scenario: SQL crudo del LLM no cruza tenants
  Given un usuario autenticado del tenant A
  When execute_safe_read_query corre "SELECT * FROM wc_orders_cache" (sin filtro)
  Then solo se devuelven filas del tenant A
  And cero filas del tenant B

Scenario: Agregado sin filtro sigue acotado
  When un usuario de A corre "SELECT count(*) FROM aria_proposals"
  Then el conteo es solo el de las propuestas de A

Scenario: Escritura cross-tenant rechazada
  Given un usuario del tenant A
  When una escritura intenta tenant_id=B (WITH CHECK)
  Then la escritura es rechazada
```
**Tests:** `tests/tenancy/tenant_isolation.test.py` — **el test de aislamiento 2-tenants** (gate de la Fase 3), corrido contra un branch InsForge; cross-check con `GET /api/database/policies`.

### S4 — `specs/infra/persistent-session.spec.md`
**Story:** Como usuario, mi conversación sobrevive reinicios del servidor y funciona entre múltiples instancias del backend.
**Invariants:** (I1) el state persiste en `agent_sessions` por `(tenant_id,user_id,session_id)`. (I2) un reinicio no pierde un hilo en curso. (I3) las filas de sesión están aisladas por RLS.
```gherkin
Scenario: La sesión sobrevive un reinicio
  Given una sesión con turnos previos
  When el proceso del backend reinicia y se reusa el mismo session_id
  Then los turnos previos siguen disponibles para el agente

Scenario: Dos instancias comparten la sesión
  Given la instancia 1 creó una sesión
  When la instancia 2 atiende el siguiente turno
  Then la instancia 2 lee el mismo state
```
**Tests:** `tests/infra/persistent_session.test.py`.

### S5 — `specs/infra/rate-limiting.spec.md`
**Story:** Como plataforma, aplico cuotas por plan por `(tenant,user)` de forma consistente entre instancias.
**Invariants:** (I1) contador compartido en `rate_limit_counters`, no en proceso. (I2) la cuota depende del tier (Free 20/día, Pro ilimitado, Enterprise multi-tienda). (I3) exceder devuelve 429 con `remaining=0`; nunca drop silencioso.
```gherkin
Scenario: Tope diario del tier Free
  Given el tenant A en Free (20/día) que ya hizo 20 requests hoy
  When el usuario hace el request 21
  Then retorna 429 y remaining_requests=0

Scenario: Contador consistente entre instancias
  Given 19 requests servidos por la instancia 1
  When la instancia 2 sirve el 20 y el 21
  Then el 21 es rechazado (contador compartido)
```
**Tests:** `tests/infra/rate_limiting.test.py`.

### S6 — `specs/integrations/tenant-woocommerce.spec.md`
**Story:** Como admin, conecto mi propia tienda WooCommerce; el sync usa mis credenciales encriptadas y nunca las de otro tenant.
**Invariants:** (I1) creds encriptadas en `tenant_integrations`, nunca en logs. (I2) solo un admin del tenant puede escribir creds. (I3) el sync de T usa solo creds de T y escribe filas con `tenant_id=T`.
```gherkin
Scenario: Admin conecta su tienda
  Given un admin autenticado del tenant A
  When guarda url+key+secret de WooCommerce en Ajustes
  Then las creds quedan encriptadas bajo el tenant A
  And un employee de A no puede sobrescribirlas

Scenario: El sync aísla tenants
  Given A y B conectaron cada uno su tienda
  When corre el cron de sync
  Then el ledger de A se puebla solo desde la tienda de A
  And toda fila escrita tiene tenant_id=A
```
**Tests:** `tests/integrations/tenant_woocommerce.test.py`.

### S7 — `specs/canvas/smart-wrapper.spec.md`
**Story:** Como usuario, las tarjetas se arrastran, hacen zoom y viajan por la línea de tiempo de forma fluida sin saltos, y cualquier tipo de tarjeta hereda este comportamiento.
**Invariants:** (I1) `x/y/width/height` los maneja `animate` de Framer, no `style` (FLIP preservado, arregla `sandbox/page.tsx:1736`). (I2) al arrastrar, duración 0; en viaje temporal, suave (~0.4s). (I3) el `key` de la tarjeta no cambia en el viaje (sin remount).
```gherkin
Scenario: Viaje temporal anima, no teletransporta
  Given una tarjeta en P1 en el nodo N1
  When el usuario viaja al nodo N2 donde la tarjeta está en P2
  Then la tarjeta anima de P1 a P2 en ~0.4s
  And no salta instantáneamente

Scenario: El arrastre es instantáneo
  When el usuario arrastra una tarjeta
  Then sigue al cursor con duración de transición 0

Scenario: Un tipo nuevo hereda el comportamiento
  Given un tipo de tarjeta nuevo envuelto en SmartWrapper
  Then soporta drag, zoom y animación temporal sin código extra
```
**Tests:** `tests/canvas/smart_wrapper.test.tsx` + Playwright visual del FLIP.

### S8 — `specs/canvas/agent-canvas-tools.spec.md`
**Story:** Como usuario, cuando le pido al agente que arme una vista, crea/actualiza/borra tarjetas en mi canvas (Estado Pasivo).
**Invariants:** (I1) las tools emiten el protocolo text-tag (`<create_card>`/`<update_card>`/`<delete_card>`) que `parseCardsFromMessage` (`:103-167`) ya entiende. (I2) el JSON de tarjeta cumple el schema `CardState`. (I3) las tools son agnósticas al negocio (solo UI); los datos vienen de las tools de analista bajo RLS.
```gherkin
Scenario: El agente crea una tarjeta desde un prompt
  Given un usuario autenticado pide "muéstrame ventas del mes"
  When el agente corre manage_canvas_widgets(action="add", ...)
  Then la respuesta contiene un bloque <create_card type="kpi"> válido
  And el frontend renderiza una nueva tarjeta KPI

Scenario: El agente actualiza una tarjeta existente
  When el agente corre manage_canvas_widgets(action="update", widget_id="card-sales", ...)
  Then se emite <update_card id="card-sales">
  And la tarjeta se parchea, no se duplica

Scenario: Config malformada es rechazada
  Given una llamada con config sin "title"
  Then la tool retorna error de validación y no emite tag
```
**Tests:** `tests/canvas/agent_canvas_tools.test.py`.

### S9 — `specs/canvas/canvas-persistence.spec.md`
**Story:** Como usuario, mi canvas (tarjetas + timeline) se guarda en mi cuenta y está disponible en cualquier dispositivo.
**Invariants:** (I1) el estado persiste en `canvas_workspaces` por `(tenant_id,user_id)`, aislado por RLS. (I2) cargar en otro dispositivo restaura el mismo estado. (I3) ningún tenant lee el workspace de otro.
```gherkin
Scenario: El canvas persiste entre dispositivos
  Given un usuario acomodó tarjetas en el dispositivo 1
  When abre ARIA-OS en el dispositivo 2
  Then se restauran las mismas tarjetas y timeline

Scenario: El workspace está aislado por tenant
  Given un usuario del tenant A guardó un workspace
  When un usuario del tenant B consulta workspaces
  Then B no ve ninguno de A
```
**Tests:** `tests/canvas/canvas_persistence.test.ts`.

---

## Secuencia de ejecución (RED→GREEN por spec, DB-first)

**Fase 0 — Verificación previa.** Crear proyecto InsForge de ARIA-OS (`cli create`+`link`), obtener keys/`JWT_SECRET`. Verificar: (a) DSN Postgres directo (decide session service); (b) acceso a Compute private preview (si no, backend en Cloud Run/Fly como capa externa); (c) si hay data Supabase real a exportar.

**Fase 1 — Datos + visual (paralelo, sin auth aún).** S1 (adapter) + migraciones M1–M4 (schema net-new + funciones, sin activar RLS) ‖ S7 (SmartWrapper + fix FLIP). Cada uno RED→GREEN.

**Fase 2 — Identidad + tenancy.** S2 (auth+middleware) → S4 (sesión) → S5 (rate limit). Habilita el resto.

**Fase 3 — ⚠️ Aislamiento (gate).** S3 en un **backend branch**: M5 (ENABLE RLS + políticas) + flip a `get_tenant_client()`. El test 2-tenants de S3 debe estar **verde** antes de `branch merge`.

**Fase 4 — Canvas + integraciones.** S8 (canvas tools) + S9 (persistencia) + S6 (WooCommerce por tenant) + login admin/empleado + Ajustes + deploy (`compute deploy . --name aria-os --port 8000`).

---

## Archivos (crear / modificar / reusar)

**Crear:** `src/infra/insforge.py` (adapter REST), `src/infra/session_insforge.py`, `src/tools/canvas.py`, migraciones InsForge (M1–M5), `frontend/src/components/SmartWrapper.tsx`, `ContentRenderer.tsx`, `frontend/src/lib/insforge.ts`, panel de Ajustes, helper de encriptación de creds, y los 9 `specs/**` + 9 `tests/**`.
**Modificar:** `src/infra/db.py`→deprecar, `src/infra/auth.py` (JWT InsForge + wire en chat), `src/infra/rate_limiter.py`, `src/infra/artifacts.py` (storage InsForge), `src/main.py` (auth dep, middleware, session, seed state), `src/tools/dynamic_execution.py` (RPC `exec_safe_read`), `src/graph/skill_retriever.py` (canvas tools), todas las `src/tools/*.py` (cliente tenant), `src/specs/db_schema.json`, `frontend/src/app/{sandbox,page}.tsx`, `route.ts` (AGENT_URL), `Dockerfile`; **eliminar** `cloud-run-service.yaml`. Limpiar `SUPABASE_*`→`INSFORGE_*` y los 2 bugs incidentales (`proposal_comments`↔`aria_proposals_comments`, paths `c:/dashboard`).
**Reusar:** `src/infra/auth.py`, `inject_ham_memory`, `parseCardsFromMessage`, `plugins/registry.py` (stubs `tenant_plugins`), `get_tools_for_node`, el Dockerfile. **Mantener** `google-genai`/`FallbackGemini` (InsForge AI queda como opción futura).

---

## Paso de mayor riesgo

**Fase 3 / S3 — Cutover RLS.** Único flip no-incremental: una call-site olvidada devuelve filas vacías (no error); un desliz `DEFINER/INVOKER` en `exec_safe_read` filtra entre empresas en silencio. **Mitigación InsForge:** hacerlo en un **backend branch** (DB fresca, mismo `JWT_SECRET`) y exigir el test de aislamiento 2-tenants de S3 **verde** antes de `branch merge`; grep exhaustivo del path de datos + `GET /api/database/policies`.

---

## Fuera de alcance (fases posteriores, documentadas)

Estados **Reactivo/Proactivo** de Fase 2 (agente crea nodos desde webhooks/real-time → normalizar `canvas_workspaces`); **Stripe Billing** (nativo InsForge — `insforge payments`; hooks/cuotas listos en S5); endurecer `execute_business_action`; observabilidad avanzada (SLO/RED), idempotency keys financieras. Cada uno tendrá su propia spec cuando se aborde.
