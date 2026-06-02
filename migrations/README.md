# ARIA-OS — InsForge Migrations

Source of truth for the ARIA-OS schema on **its own InsForge project** (not the
Cinco project). Tables here are net-new in InsForge.

## Order

| File | What | When |
|------|------|------|
| `0001_tenancy_core.sql` | tenants, tenant_users(role), tenant_integrations, tenant_plugins | Fase 1 |
| `0002_business_tables.sql` | business tables, each with `tenant_id` + indexes | Fase 1 |
| `0003_system_tables.sql` | system_config, usage log, rate_limit_counters, agent_sessions, canvas_workspaces | Fase 1 |
| `0004_functions.sql` | `is_tenant_member()`/`is_tenant_admin()` (SECURITY DEFINER), `exec_safe_read()` (SECURITY INVOKER) | Fase 1 |
| `0005_rls_policies.sql` | **RLS cutover** — ENABLE RLS + `tenant_isolation` policies | **Fase 3, in a branch** |

## How to apply

Prereq: ARIA-OS InsForge project created + linked (`npx @insforge/cli create` / `link`).

```bash
# Per-file via CLI:
npx @insforge/cli db query < migrations/0001_tenancy_core.sql
# ...0002, 0003, 0004

# 0005 (RLS) — do it in an isolated branch, test, then merge:
npx @insforge/cli branch create rls-cutover --mode schema-only
#   (switch env to the branch, then)
npx @insforge/cli db query < migrations/0005_rls_policies.sql
python3 -m pytest tests/tenancy            # the 2-tenant isolation gate MUST be green
npx @insforge/cli branch merge rls-cutover --dry-run
npx @insforge/cli branch merge rls-cutover
```

Or via REST: `POST /api/database/migrations` with `{version, name, sql}` (admin
key). Do **not** wrap statements in BEGIN/COMMIT — InsForge wraps each migration
in its own transaction.

## Notes

- `auth.users(id)`, `auth.uid()`, `system.update_updated_at()` are InsForge
  built-ins.
- The admin client (backend system writes) bypasses RLS by design; RLS protects
  the tenant-JWT data path, including the LLM-authored SQL via `exec_safe_read`.
