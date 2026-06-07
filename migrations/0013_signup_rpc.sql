-- 0013_signup_rpc.sql
-- Atomic self-serve signup: create a tenant + its admin membership in ONE transaction
-- so a partial failure never leaves an orphan tenant (the F6 bug that got signup
-- disabled). A plpgsql function body is atomic — if the membership insert fails, the
-- tenant insert rolls back. SECURITY DEFINER so the signup endpoint can provision
-- regardless of RLS. App-level idempotency (existing user → reuse membership) lives in
-- the /api/v1/signup handler. ADITIVA (creates a function; reversible).

CREATE OR REPLACE FUNCTION create_tenant_with_admin(p_user_id uuid, p_company_name text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant_id uuid;
  v_slug text;
BEGIN
  v_slug := trim(both '-' from lower(regexp_replace(
              coalesce(nullif(trim(p_company_name), ''), 'tenant'),
              '[^a-zA-Z0-9]+', '-', 'g')))
            || '-' || substr(gen_random_uuid()::text, 1, 8);
  INSERT INTO tenants (name, slug)
    VALUES (coalesce(nullif(trim(p_company_name), ''), 'Mi Empresa'), v_slug)
    RETURNING id INTO v_tenant_id;
  INSERT INTO tenant_users (tenant_id, user_id, role)
    VALUES (v_tenant_id, p_user_id, 'admin');
  RETURN v_tenant_id;
END;
$$;

-- ── Rollback (manual) ───────────────────────────────────────────────────────
-- DROP FUNCTION IF EXISTS create_tenant_with_admin(uuid, text);
