/**
 * ARIA-OS frontend auth (InsForge).
 *
 * Talks directly to the InsForge auth REST API and keeps the access token in
 * localStorage. We deliberately do NOT use the @insforge/sdk session manager
 * here to avoid its navigator.locks-based persistence (a documented deadlock
 * risk); a plain token in localStorage is enough for this app.
 */
const INSFORGE_URL = process.env.NEXT_PUBLIC_INSFORGE_URL ?? "";
const TOKEN_KEY = "aria_token";

export interface AuthUser {
  id: string;
  email: string;
}

function store(token: string) {
  if (typeof window !== "undefined") localStorage.setItem(TOKEN_KEY, token);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function signOut() {
  if (typeof window !== "undefined") localStorage.removeItem(TOKEN_KEY);
}

async function authRequest(path: string, body: object): Promise<AuthUser> {
  const res = await fetch(`${INSFORGE_URL}${path}?client_type=server`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.message ?? "Authentication failed");
  if (!data.accessToken) throw new Error("No access token returned (email verification?)");
  store(data.accessToken);
  return { id: data.user.id, email: data.user.email };
}

export function signIn(email: string, password: string) {
  return authRequest("/api/auth/sessions", { email, password });
}

export function signUp(email: string, password: string, name?: string) {
  return authRequest("/api/auth/users", { email, password, name: name ?? email });
}
