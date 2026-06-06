"use client";
import { useCallback, useEffect, useState } from "react";

import {
  approveProposal,
  listProposals,
  rejectProposal,
  type Proposal,
  type ProposalItem,
} from "@/lib/api";

const URGENCY: Record<string, { label: string; cls: string }> = {
  alta: { label: "Alta", cls: "bg-red-500/15 text-red-300 border-red-400/30" },
  media: { label: "Media", cls: "bg-amber-500/15 text-amber-300 border-amber-400/30" },
  baja: { label: "Baja", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-400/30" },
};

/** Render one item line tolerantly — the items JSONB shape differs by category
 * (reorder carries qty/costo/proveedor; liquidation carries stock_inmovilizado…). */
function itemLine(it: ProposalItem): string {
  const name = it.name ?? it.product ?? "—";
  const parts: string[] = [];
  if (it.qty != null) parts.push(`${it.qty} u.`);
  if (it.stock_actual != null) parts.push(`stock ${it.stock_actual}`);
  if (it.stock_inmovilizado != null) parts.push(`inmov. ${it.stock_inmovilizado}`);
  if (it.costo_unitario != null) parts.push(`$${it.costo_unitario}/u`);
  if (it.proveedor != null) parts.push(String(it.proveedor));
  return parts.length ? `${name} — ${parts.join(" · ")}` : String(name);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3">
      <p className="mb-0.5 text-xs uppercase tracking-wide text-white/40">{title}</p>
      <p className="whitespace-pre-line text-sm text-white/80">{children}</p>
    </div>
  );
}

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setProposals(await listProposals("pending"));
      setError("");
    } catch {
      setError("No se pudieron cargar las propuestas (¿sesión expirada?).");
      setProposals([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(id: string, action: "approve" | "reject") {
    setBusy(id);
    setError("");
    try {
      if (action === "approve") await approveProposal(id);
      else await rejectProposal(id, "Rechazada desde la bandeja");
      setProposals((ps) => (ps ?? []).filter((p) => p.id !== id));
    } catch {
      setError("La acción falló — solo un administrador puede aprobar o rechazar.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#0a0a0b] px-4 py-10 text-white">
      <div className="mx-auto w-full max-w-3xl">
        <header className="mb-6 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Bandeja de propuestas</h1>
            <p className="mt-1 text-sm text-white/50">
              Propuestas del agente esperando tu aprobación.
            </p>
          </div>
          <button
            onClick={() => void load()}
            className="rounded-xl border border-white/15 px-3 py-1.5 text-xs text-white/70 transition-colors hover:bg-white/5"
          >
            Actualizar
          </button>
        </header>

        {error && (
          <p className="mb-4 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        {proposals === null ? (
          <p className="text-sm text-white/40">Cargando…</p>
        ) : proposals.length === 0 ? (
          <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-10 text-center text-sm text-white/40">
            No hay propuestas pendientes. Pedile al agente un{" "}
            <span className="text-white/70">“barrido proactivo”</span>.
          </div>
        ) : (
          <ul className="flex flex-col gap-4">
            {proposals.map((p) => {
              const u = (p.urgency && URGENCY[p.urgency]) || { label: p.urgency ?? "—", cls: "bg-white/10 text-white/60 border-white/15" };
              return (
                <li
                  key={p.id}
                  className="rounded-3xl border border-white/10 bg-[#111113]/80 p-6 backdrop-blur-xl shadow-xl"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold leading-tight">{p.title}</h2>
                      {p.category && <span className="text-xs text-white/40">{p.category}</span>}
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium ${u.cls}`}>
                      {u.label}
                    </span>
                  </div>

                  {p.problem && <Section title="Problema">{p.problem}</Section>}
                  {p.strategy && <Section title="Estrategia">{p.strategy}</Section>}
                  {p.recommendation && <Section title="Recomendación">{p.recommendation}</Section>}
                  {p.proposed_action && <Section title="Acción propuesta">{p.proposed_action}</Section>}

                  {p.items && p.items.length > 0 && (
                    <div className="mt-3">
                      <p className="mb-1 text-xs uppercase tracking-wide text-white/40">
                        Ítems ({p.items.length})
                      </p>
                      <ul className="divide-y divide-white/5 rounded-xl border border-white/10 bg-white/[0.02] text-sm">
                        {p.items.map((it, i) => (
                          <li key={i} className="px-3 py-1.5 text-white/80">
                            {itemLine(it)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {(p.estimated_impact || p.risk) && (
                    <div className="mt-3 flex flex-wrap gap-4 text-xs text-white/50">
                      {p.estimated_impact && <span>Impacto: {p.estimated_impact}</span>}
                      {p.risk && <span>Riesgo: {p.risk}</span>}
                    </div>
                  )}

                  <div className="mt-5 flex gap-3">
                    <button
                      disabled={busy === p.id}
                      onClick={() => act(p.id, "approve")}
                      className="rounded-xl bg-emerald-500/90 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-400 disabled:opacity-40"
                    >
                      {busy === p.id ? "…" : "Aprobar"}
                    </button>
                    <button
                      disabled={busy === p.id}
                      onClick={() => act(p.id, "reject")}
                      className="rounded-xl border border-white/15 px-4 py-2 text-sm text-white/70 transition-colors hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
                    >
                      Rechazar
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </main>
  );
}
