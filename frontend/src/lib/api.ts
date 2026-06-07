/**
 * ARIA-OS frontend API client → the FastAPI backend (tenant-scoped via the JWT).
 * Uses the proven /api/v1/chat + /api/v1/canvas + /api/v1/me endpoints, and
 * transparently refreshes an expired access token once on 401/403.
 */
import { getToken, refreshSession } from "./auth";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Fetch with one transparent token-refresh retry on 401/403. */
async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const build = (): RequestInit => ({ ...init, headers: { ...authHeader(), ...(init.headers ?? {}) } });
  let res = await fetch(`${BACKEND}${path}`, build());
  if (res.status === 401 || res.status === 403) {
    if (await refreshSession()) {
      res = await fetch(`${BACKEND}${path}`, build());
    }
  }
  if (res.status === 401 || res.status === 403) {
    throw new Error("UNAUTHENTICATED");
  }
  return res;
}

export interface ChatResult {
  response: string;
  agent: string;
  remaining_requests: number | null;
}

export async function chat(message: string): Promise<ChatResult> {
  const form = new FormData();
  form.append("message", message);
  const res = await request("/api/v1/chat", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? "Chat failed");
  return data;
}

export interface Me {
  user_id: string;
  tenant_id: string;
  role: string;
}

export async function me(): Promise<Me> {
  const res = await request("/api/v1/me");
  return res.json();
}

export async function loadCanvas<T = unknown>(): Promise<T | null> {
  try {
    const res = await request("/api/v1/canvas");
    const data = await res.json();
    return (data?.state as T) ?? null;
  } catch {
    return null;
  }
}

export async function saveCanvas(state: unknown): Promise<void> {
  await request("/api/v1/canvas", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
}

// ── Proposals (HITL approval tray) ──────────────────────────────────────────
// The agent's proactive sweep registers consolidated proposals; the owner
// approves/rejects them here. items/strategy/recommendation were added in 0007.
export type ProposalItem = Record<string, unknown> & {
  name?: string;
  product?: string;
  qty?: number;
  sku?: string;
  proveedor?: string;
  costo_unitario?: number;
  stock_actual?: number;
  stock_inmovilizado?: number;
};

export interface Proposal {
  id: string;
  title: string;
  problem: string | null;
  proposed_action: string | null;
  urgency: string | null;
  status: string;
  category: string | null;
  estimated_impact: string | null;
  risk: string | null;
  strategy: string | null;
  recommendation: string | null;
  items: ProposalItem[] | null;
  created_at: string;
}

export async function listProposals(status = "pending"): Promise<Proposal[]> {
  const res = await request(`/api/v1/proposals?status=${encodeURIComponent(status)}`);
  const data = await res.json();
  return (data?.proposals as Proposal[]) ?? [];
}

export async function approveProposal(id: string): Promise<void> {
  await request(`/api/v1/proposals/${id}/approve`, { method: "POST" });
}

export async function rejectProposal(id: string, reason = ""): Promise<void> {
  await request(`/api/v1/proposals/${id}/reject?reason=${encodeURIComponent(reason)}`, {
    method: "POST",
  });
}

export async function executeProposal(id: string): Promise<void> {
  await request(`/api/v1/proposals/${id}/execute`, { method: "POST" });
}

// ── Ingestion / onboarding (M6) ─────────────────────────────────────────────
export async function connectWooCommerce(
  url: string,
  consumer_key: string,
  consumer_secret: string,
): Promise<{ status: string }> {
  const res = await request("/api/v1/integrations/woocommerce", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, consumer_key, consumer_secret }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? "No se pudo conectar WooCommerce");
  return data;
}

export interface ImportResult {
  imported: number;
  stats: { total: number; ok: number; rejected: number; warned: number };
  ledger: { rows: number; products_added: number };
}

export async function importCsv(text: string): Promise<ImportResult> {
  const res = await request("/api/v1/import/csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? "No se pudo importar el CSV");
  return data;
}

// ── Billing (M7) ────────────────────────────────────────────────────────────
export interface BillingStatus {
  subscription_status: string;
  tier: string;
}

export async function billingStatus(): Promise<BillingStatus> {
  const res = await request("/api/v1/billing/status");
  return res.json();
}

// ── Dashboard / forecast / rules (M8) ───────────────────────────────────────
export interface DashboardSummary {
  pending_proposals: Proposal[];
  pending_count: number;
  product_count: number;
  products: string[];
  latest_ledger_date: string | null;
  anomalies: Array<Record<string, unknown>>;
}

export async function dashboardSummary(): Promise<DashboardSummary> {
  const res = await request("/api/v1/dashboard/summary");
  return res.json();
}

export interface ForecastResult {
  status: string;
  summary?: string;
  proyeccion_total?: number;
  model_used?: string;
  backtest?: { mape?: number; status?: string };
}

export async function forecast(product: string, days = 14, price = 0): Promise<ForecastResult> {
  const qs = new URLSearchParams({ product, days: String(days), price: String(price) });
  const res = await request(`/api/v1/forecast?${qs.toString()}`);
  return res.json();
}

export interface Rule {
  id: string;
  name: string;
  metric: string;
  op: string;
  threshold: number;
  action: string;
  enabled: boolean;
}

export async function listRules(): Promise<Rule[]> {
  const res = await request("/api/v1/automation-rules");
  const data = await res.json();
  return (data?.rules as Rule[]) ?? [];
}

export async function createRule(r: {
  name: string;
  metric: string;
  op: string;
  threshold: number;
  action?: string;
}): Promise<void> {
  const form = new FormData();
  form.append("name", r.name);
  form.append("metric", r.metric);
  form.append("op", r.op);
  form.append("threshold", String(r.threshold));
  form.append("action", r.action ?? "create_proposal");
  await request("/api/v1/automation-rules", { method: "POST", body: form });
}

export async function deleteRule(id: string): Promise<void> {
  await request(`/api/v1/automation-rules/${id}`, { method: "DELETE" });
}
