"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { signUp } from "@/lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await signUp(email, password, company);
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#0a0a0b] text-white px-4">
      <div className="w-full max-w-sm rounded-3xl border border-white/10 bg-[#111113]/80 p-8 backdrop-blur-xl shadow-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Creá tu empresa</h1>
        <p className="mt-1 text-sm text-white/50">
          Tu cuenta es admin desde el primer minuto. Sin esperar a nadie.
        </p>

        <form
          className="mt-6 flex flex-col gap-3"
          onSubmit={(ev) => {
            ev.preventDefault();
            submit();
          }}
        >
          <input
            className="rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400"
            type="text"
            placeholder="nombre de tu empresa"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            required
          />
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
            placeholder="contraseña (mín. 8 caracteres)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button
            disabled={busy}
            className="mt-1 rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2.5 text-sm font-medium transition-colors"
          >
            {busy ? "Creando…" : "Crear empresa"}
          </button>
        </form>

        <button
          onClick={() => router.push("/login")}
          className="mt-4 w-full text-center text-xs text-white/40 hover:text-white/70"
        >
          ¿Ya tenés cuenta? Entrar
        </button>
      </div>
    </main>
  );
}
