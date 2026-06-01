"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { signIn, signUp } from "@/lib/auth";

const DEMO = { email: "demo@aria.os", password: "AriaDemo2026!" };

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function go(e: string, p: string) {
    setBusy(true);
    setError("");
    try {
      if (mode === "up") await signUp(e, p);
      else await signIn(e, p);
      router.push("/app");
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
          {mode === "in" ? "Ingresá a tu empresa" : "Creá tu cuenta"}
        </p>

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
            {busy ? "…" : mode === "in" ? "Entrar" : "Crear cuenta"}
          </button>
        </form>

        <button
          disabled={busy}
          onClick={() => go(DEMO.email, DEMO.password)}
          className="mt-3 w-full rounded-xl border border-white/15 hover:bg-white/5 px-4 py-2.5 text-sm transition-colors disabled:opacity-50"
        >
          ✨ Entrar como demo
        </button>

        <button
          onClick={() => setMode(mode === "in" ? "up" : "in")}
          className="mt-4 w-full text-center text-xs text-white/40 hover:text-white/70"
        >
          {mode === "in" ? "¿No tenés cuenta? Crear una" : "¿Ya tenés cuenta? Entrar"}
        </button>
      </div>
    </main>
  );
}
