/**
 * InsForge client + canvas workspace persistence (Fase 2, S9).
 *
 * Replaces the localStorage persistence in sandbox/page.tsx: the canvas state
 * (nodes, branches, active) is stored per (tenant, user) in canvas_workspaces,
 * RLS-isolated, so it survives across devices.
 *
 * The client is created lazily (so importing this module never throws on a
 * missing env var), and the workspace helpers accept an injected `database` for
 * unit testing. // spec: specs/canvas/canvas-persistence.spec.md
 */
import { createClient } from "@insforge/sdk";

export interface WorkspaceState {
  nodes: unknown;
  branches: unknown;
  activeNodeId: string | null;
  activeBranchId: string | null;
}

const TABLE = "canvas_workspaces";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Db = { from: (table: string) => any };

let _client: ReturnType<typeof createClient> | null = null;

export function getInsforge() {
  if (!_client) {
    _client = createClient({
      baseUrl: process.env.NEXT_PUBLIC_INSFORGE_URL ?? "",
      anonKey: process.env.NEXT_PUBLIC_INSFORGE_ANON_KEY ?? "",
    });
  }
  return _client;
}

export async function loadWorkspace(
  userId: string,
  database?: Db,
): Promise<WorkspaceState | null> {
  const db = database ?? getInsforge().database;
  const { data, error } = await db
    .from(TABLE)
    .select("state")
    .eq("user_id", userId)
    .maybeSingle();
  if (error || !data) return null;
  return (data as { state?: WorkspaceState }).state ?? null;
}

export async function saveWorkspace(
  userId: string,
  tenantId: string,
  state: WorkspaceState,
  database?: Db,
): Promise<void> {
  const db = database ?? getInsforge().database;
  // The SDK has no upsert → update if a row exists for this user, else insert.
  const { data: existing } = await db
    .from(TABLE)
    .select("id")
    .eq("user_id", userId)
    .maybeSingle();
  if (existing) {
    await db.from(TABLE).update({ state }).eq("user_id", userId);
  } else {
    await db.from(TABLE).insert([{ user_id: userId, tenant_id: tenantId, state }]);
  }
}
