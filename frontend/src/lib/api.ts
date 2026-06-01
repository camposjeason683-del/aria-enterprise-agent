/**
 * ARIA-OS frontend API client → the FastAPI backend (tenant-scoped via the JWT).
 * Uses the proven /api/v1/chat + /api/v1/canvas + /api/v1/me endpoints.
 */
import { getToken } from "./auth";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface ChatResult {
  response: string;
  agent: string;
  remaining_requests: number | null;
}

export async function chat(message: string): Promise<ChatResult> {
  const form = new FormData();
  form.append("message", message);
  const res = await fetch(`${BACKEND}/api/v1/chat`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (res.status === 401) throw new Error("UNAUTHENTICATED");
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
  const res = await fetch(`${BACKEND}/api/v1/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error("UNAUTHENTICATED");
  return res.json();
}

export async function loadCanvas<T = unknown>(): Promise<T | null> {
  const res = await fetch(`${BACKEND}/api/v1/canvas`, { headers: authHeaders() });
  if (!res.ok) return null;
  const data = await res.json();
  return (data?.state as T) ?? null;
}

export async function saveCanvas(state: unknown): Promise<void> {
  await fetch(`${BACKEND}/api/v1/canvas`, {
    method: "PUT",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
}
