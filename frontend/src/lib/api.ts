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
