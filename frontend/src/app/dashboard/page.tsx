"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { dashboardSummary, executeProposal, type DashboardSummary } from "@/lib/api";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");
  const [acting, setActing] = useState<string | null>(null);

  async function load() {
    try {
      setData(await dashboardSummary());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function approveAndExecute(id: string) {
    setActing(id);
    try {
      await executeProposal(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setActing(null);
    }
  }

  const card = "rounded-2xl border border-white/10 bg-[#111113]/80 p-5";

  return (
    <main className="min-h-screen bg-[#0a0a0b] text-white px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Tu negocio hoy</h1>
          <nav className="flex gap-4 text-sm text-white/50">
            <Link href="/whatif" className="hover:text-white">What-if</Link>
            <Link href="/rules" className="hover:text-white">Reglas</Link>
            <Link href="/settings/billing" className="hover:text-white">Plan</Link>
          </nav>
        </header>
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
        {!data ? (
          <p className="mt-8 text-white/40">Cargando…</p>
        ) : (
          <div className="mt-6 grid gap-4">
            <div className="grid grid-cols-3 gap-4">
              <div className={card}>
                <p className="text-xs uppercase tracking-wide text-white/40">Decisiones pendientes</p>
                <p className="mt-1 text-3xl font-semibold">{data.pending_count}</p>
              </div>
              <div className={card}>
                <p className="text-xs uppercase tracking-wide text-white/40">Productos</p>
                <p className="mt-1 text-3xl font-semibold">{data.product_count}</p>
              </div>
              <div className={card}>
                <p className="text-xs uppercase tracking-wide text-white/40">Datos al</p>
                <p className="mt-1 text-lg font-medium">{data.latest_ledger_date ?? "—"}</p>
              </div>
            </div>

            <div className={card}>
              <h2 className="text-sm font-medium text-white/80">Decisiones para aprobar</h2>
              {data.pending_proposals.length === 0 ? (
                <p className="mt-3 text-sm text-white/40">Nada pendiente. ARIA está al día. ✅</p>
              ) : (
                <ul className="mt-3 flex flex-col gap-2">
                  {data.pending_proposals.map((p) => (
                    <li key={p.id} className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3">
                      <div>
                        <p className="text-sm">{p.title}</p>
                        <p className="text-xs text-white/40">{p.category ?? ""} · {p.urgency ?? ""}</p>
                      </div>
                      <button
                        disabled={acting === p.id}
                        onClick={() => approveAndExecute(p.id)}
                        className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-3 py-1.5 text-xs font-medium"
                      >
                        {acting === p.id ? "…" : "Ejecutar"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {data.anomalies.length > 0 && (
              <div className={card}>
                <h2 className="text-sm font-medium text-white/80">Anomalías detectadas</h2>
                <ul className="mt-3 flex flex-col gap-2 text-sm text-white/70">
                  {data.anomalies.map((a, i) => (
                    <li key={i} className="rounded-xl bg-amber-500/10 border border-amber-500/20 px-4 py-2">
                      {String(a.description ?? a.product ?? JSON.stringify(a))}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
