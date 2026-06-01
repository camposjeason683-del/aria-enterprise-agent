-- M4 — RLS helper + tenant-safe raw SQL RPC.
-- spec: specs/tenancy/tenant-isolation.spec.md

-- ── is_tenant_member: SECURITY DEFINER so it does NOT recurse into the RLS of
--    tenant_users (the canonical InsForge pattern to avoid infinite-recursion
--    OOM). Used by every business-table policy. ────────────────────────────────
CREATE OR REPLACE FUNCTION is_tenant_member(p_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT EXISTS (
    SELECT 1 FROM tenant_users
    WHERE tenant_id = p_tenant_id
      AND user_id = (SELECT auth.uid())
  );
$$;

-- ── is_tenant_admin: same, restricted to role='admin' (integration writes) ───
CREATE OR REPLACE FUNCTION is_tenant_admin(p_tenant_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT EXISTS (
    SELECT 1 FROM tenant_users
    WHERE tenant_id = p_tenant_id
      AND user_id = (SELECT auth.uid())
      AND role = 'admin'
  );
$$;

-- ── exec_safe_read: runs an LLM-authored SELECT. CRITICAL: SECURITY INVOKER so
--    it executes as the calling 'authenticated' role → RLS applies and the
--    query can only ever see the caller's tenant rows, even with no WHERE
--    tenant_id filter. The app layer (execute_safe_read_query) still blocks
--    writes and validates columns first (defense in depth). ───────────────────
CREATE OR REPLACE FUNCTION exec_safe_read(q TEXT)
RETURNS SETOF json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
  IF q !~* '^\s*select' THEN
    RAISE EXCEPTION 'exec_safe_read: only SELECT statements are allowed';
  END IF;
  RETURN QUERY EXECUTE 'SELECT row_to_json(_sub) FROM (' || q || ') AS _sub';
END;
$$;

-- Callable by logged-in users only (never anon).
REVOKE ALL ON FUNCTION exec_safe_read(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION exec_safe_read(TEXT) TO authenticated;
