/**
 * ARIA-OS frontend auth (InsForge).
 *
 * Talks directly to the InsForge auth REST API and keeps the access + refresh
 * tokens in localStorage. We deliberately do NOT use the @insforge/sdk session
 * manager (it persists via navigator.locks — a documented deadlock risk).
 * Access tokens are short-lived (~15 min); refreshSession() rotates them.
 */
const INSFORGE_URL = process.env.NEXT_PUBLIC_INSFORGE_URL ?? "";
const TOKEN_KEY = "aria_token";
const REFRESH_KEY = "aria_refresh";

export interface AuthUser {
  id: string;
  email: string;
}

function store(accessToken: string, refreshToken?: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
  // Also a cookie, so same-origin requests to /api/copilotkit carry the JWT
  // (CopilotKit's runtime proxy forwards it to the backend).
  document.cookie = `${TOKEN_KEY}=${accessToken}; path=/; max-age=900; samesite=lax`;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

function getRefresh(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function signOut() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  document.cookie = `${TOKEN_KEY}=; path=/; max-age=0`;
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
  store(data.accessToken, data.refreshToken);
  return { id: data.user.id, email: data.user.email };
}

export function signIn(email: string, password: string) {
  return authRequest("/api/auth/sessions", { email, password });
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

/**
 * Self-serve signup (M5). Hits the backend, which creates the auth user AND a
 * tenant + admin membership atomically, so the user never lands tenant-less (the
 * F6 orphan that made us disable signup). Stores the returned session token.
 */
export async function signUp(
  email: string,
  password: string,
  companyName: string,
): Promise<AuthUser> {
  const res = await fetch(`${BACKEND_URL}/api/v1/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, company_name: companyName }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? "No se pudo crear la cuenta");
  if (!data.accessToken)
    throw new Error("Cuenta creada. Verificá tu email para iniciar sesión.");
  store(data.accessToken, data.refreshToken);
  return { id: data.user_id, email };
}

/** Rotate the access token using the stored refresh token. Returns success. */
export async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefresh();
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${INSFORGE_URL}/api/auth/refresh?client_type=server`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (!data.accessToken) return false;
    store(data.accessToken, data.refreshToken);
    return true;
  } catch {
    return false;
  }
}
