"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { signIn } from "@/lib/auth";

const DEMO = { email: "demo@aria.os", password: "AriaDemo2026!" };

export default function LoginPage() {
  const router = useRouter();
  // "in" = sign-in form. "up" = access info (no self-serve signup — see below).
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function go(e: string, p: string) {
    setBusy(true);
    setError("");
    try {
      await signIn(e, p);
      router.push("/sandbox");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#0a0a0b] text-white px-4">
      <div className="w-full max-w-sm rounded-3xl border border-white/10 bg-[#111113]/80 p-8 backdrop-blur-xl shadow-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">ARIA-OS</h1>
        <p className="mt-1 text-sm text-white/50">
          {mode === "in" ? "Ingresá a tu empresa" : "Acceso por invitación"}
        </p>

        {mode === "in" ? (
          <form
            className="mt-6 flex flex-col gap-3"
            onSubmit={(ev) => {
              ev.preventDefault();
              go(email, password);
            }}
          >
            <input
              className="rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400"
              type="email"
              placeholder="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              className="rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400"
              type="password"
              placeholder="contraseña"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button
              disabled={busy}
              className="mt-1 rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2.5 text-sm font-medium transition-colors"
            >
              {busy ? "…" : "Entrar"}
            </button>
          </form>
        ) : (
          // F6: self-serve signup created tenant-less (orphan) users that the
          // multi-tenant backend rejects — dropping them into a broken /sandbox.
          // Access is provisioned by a company admin instead, so direct the user
          // there rather than creating an account that can't do anything.
          <div className="mt-6 rounded-xl border border-white/10 bg-white/5 p-4 text-sm leading-relaxed text-white/70">
            El acceso a ARIA-OS lo habilita el <strong className="text-white/90">administrador de tu empresa</strong>.
            Pedile que te agregue con tu email y un rol (admin o empleado). Una vez
            asignado a tu empresa vas a poder entrar con tu usuario acá.
          </div>
        )}

        <button
          disabled={busy}
          onClick={async () => {
            // Demo ALWAYS signs in (the demo user already exists), regardless of mode.
            setBusy(true);
            setError("");
            try {
              await signIn(DEMO.email, DEMO.password);
              router.push("/sandbox");
            } catch (err) {
              setError(err instanceof Error ? err.message : "Error");
              setBusy(false);
            }
          }}
          className="mt-3 w-full rounded-xl border border-white/15 hover:bg-white/5 px-4 py-2.5 text-sm transition-colors disabled:opacity-50"
        >
          ✨ Entrar como demo
        </button>

        <button
          onClick={() => {
            setError("");
            setMode(mode === "in" ? "up" : "in");
          }}
          className="mt-4 w-full text-center text-xs text-white/40 hover:text-white/70"
        >
          {mode === "in" ? "¿No tenés acceso? Cómo obtenerlo" : "¿Ya tenés cuenta? Entrar"}
        </button>
      </div>
    </main>
  );
}
