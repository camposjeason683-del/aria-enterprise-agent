"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { connectWooCommerce, importCsv, type ImportResult } from "@/lib/api";

type Method = "choose" | "woo" | "csv";

export default function OnboardingPage() {
  const router = useRouter();
  const [method, setMethod] = useState<Method>("choose");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<ImportResult | "woo" | null>(null);

  // WooCommerce form
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function submitWoo() {
    setBusy(true);
    setError("");
    try {
      await connectWooCommerce(url, key, secret);
      setDone("woo");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function submitCsv() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Elegí un archivo CSV.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const text = await file.text();
      const res = await importCsv(text);
      setDone(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400";
  const primary =
    "rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2.5 text-sm font-medium transition-colors";

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#0a0a0b] text-white px-4">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#111113]/80 p-8 backdrop-blur-xl shadow-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Conectá tu negocio</h1>
        <p className="mt-1 text-sm text-white/50">
          ARIA necesita tus ventas para empezar a proyectar y proponer.
        </p>

        {done ? (
          <div className="mt-6 flex flex-col gap-4">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
              {done === "woo" ? (
                <>✅ WooCommerce conectado. La primera sincronización corre en breve.</>
              ) : (
                <>
                  ✅ Importadas <strong>{done.imported}</strong> filas ·{" "}
                  {done.ledger.rows} días de ledger · {done.ledger.products_added} productos.
                  {done.stats.rejected > 0 && (
                    <span className="text-amber-300"> {done.stats.rejected} filas con problemas.</span>
                  )}
                </>
              )}
            </div>
            <button className={primary} onClick={() => router.push("/dashboard")}>
              Ver mi tablero →
            </button>
          </div>
        ) : method === "choose" ? (
          <div className="mt-6 flex flex-col gap-3">
            <button className={primary} onClick={() => setMethod("woo")}>
              Conectar WooCommerce
            </button>
            <button
              className="rounded-xl border border-white/15 hover:bg-white/5 px-4 py-2.5 text-sm transition-colors"
              onClick={() => setMethod("csv")}
            >
              Subir un CSV de ventas
            </button>
          </div>
        ) : method === "woo" ? (
          <form
            className="mt-6 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              submitWoo();
            }}
          >
            <input className={input} placeholder="https://tu-tienda.com" value={url} onChange={(e) => setUrl(e.target.value)} required />
            <input className={input} placeholder="Consumer key (ck_...)" value={key} onChange={(e) => setKey(e.target.value)} required />
            <input className={input} type="password" placeholder="Consumer secret (cs_...)" value={secret} onChange={(e) => setSecret(e.target.value)} required />
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button disabled={busy} className={primary}>{busy ? "Conectando…" : "Conectar"}</button>
            <button type="button" className="text-xs text-white/40 hover:text-white/70" onClick={() => setMethod("choose")}>← volver</button>
          </form>
        ) : (
          <form
            className="mt-6 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              submitCsv();
            }}
          >
            <p className="text-xs text-white/50">Columnas: fecha, producto, cantidad, precio (ES o EN).</p>
            <input ref={fileRef} className={input} type="file" accept=".csv,text/csv" required />
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button disabled={busy} className={primary}>{busy ? "Importando…" : "Importar"}</button>
            <button type="button" className="text-xs text-white/40 hover:text-white/70" onClick={() => setMethod("choose")}>← volver</button>
          </form>
        )}
      </div>
    </main>
  );
}
