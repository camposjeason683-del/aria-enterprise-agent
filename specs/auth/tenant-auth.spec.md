# Spec — Tenant Authentication (`auth/tenant-auth`)

> Track A · Depende de S1 · Invariante cardinal: sin JWT verificado no hay
> agente; tenant/role se resuelven server-side.

## Story

Como empleado de una empresa, me autentico con InsForge y cada request del
agente corre bajo mi identidad y mi tenant, de modo que solo toco datos de mi
empresa.

## Invariants

- **I1** — Sin un JWT InsForge verificado, el agente no se invoca (401/403).
- **I2** — `tenant_id` + `role` se resuelven **server-side** desde `tenant_users`
  por `auth.uid()`; nunca se toman del cliente (form/headers arbitrarios).
- **I3** — Un usuario sin fila en `tenant_users` es rechazado (403). No hay
  tenant "default".

## Acceptance Criteria (BDD)

```gherkin
Scenario: Request no autenticado rechazado
  Given un POST /api/v1/chat sin header Authorization
  Then require_tenant levanta 401 y el agente nunca se invoca

Scenario: Firma inválida rechazada
  Given un Bearer token firmado con un secreto distinto
  Then verify_insforge_jwt levanta 403

Scenario: JWT válido resuelve tenant y siembra la sesión
  Given un JWT InsForge válido del usuario "u1" miembro del tenant "A" como "employee"
  When require_tenant procesa el request
  Then devuelve TenantContext(user_id="u1", tenant_id="A", role="employee")
  And el contextvar current() expone ese contexto

Scenario: Usuario sin membresía rechazado
  Given un JWT válido de un usuario sin fila en tenant_users
  Then resolve_tenant_membership levanta 403

Scenario: user_id manipulado se ignora
  Given un request con un form user_id="admin-de-B" pero el sub del JWT es "u1"
  Then la identidad resuelta es "u1" (del JWT), no del form
```

## Tests

`tests/auth/test_tenant_auth.py` — JWT real firmado con un secreto de test;
admin client falso para `resolve_tenant_membership`; `require_tenant` con
Request falso. El cableado en `main.py` (dependencia + seed del session state)
se cubre en la tarea de wiring (#10).
