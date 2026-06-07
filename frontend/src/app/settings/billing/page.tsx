"use client";
import { useEffect, useState } from "react";

import { billingStatus, type BillingStatus } from "@/lib/api";

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  active: { label: "Activa", tone: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10" },
  trialing: { label: "Prueba", tone: "text-sky-300 border-sky-500/30 bg-sky-500/10" },
  past_due: { label: "Pago pendiente", tone: "text-amber-300 border-amber-500/30 bg-amber-500/10" },
  canceled: { label: "Cancelada", tone: "text-red-300 border-red-500/30 bg-red-500/10" },
};

export default function BillingPage() {
  const [data, setData] = useState<BillingStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    billingStatus()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  const st = data ? STATUS_LABEL[data.subscription_status] ?? STATUS_LABEL.active : null;

  return (
    <main className="min-h-screen bg-[#0a0a0b] text-white px-4 py-12">
      <div className="mx-auto max-w-lg">
        <h1 className="text-2xl font-semibold tracking-tight">Plan y facturación</h1>
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
        {data && (
          <div className="mt-6 rounded-2xl border border-white/10 bg-[#111113]/80 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide text-white/40">Plan</p>
                <p className="text-lg font-medium capitalize">{data.tier}</p>
              </div>
              {st && (
                <span className={`rounded-full border px-3 py-1 text-xs ${st.tone}`}>
                  {st.label}
                </span>
              )}
            </div>
            <button
              className="mt-6 w-full rounded-xl bg-indigo-500 hover:bg-indigo-400 px-4 py-2.5 text-sm font-medium transition-colors"
              onClick={() => alert("La gestión de pago se habilita al conectar Stripe.")}
            >
              {data.subscription_status === "active" ? "Gestionar plan" : "Reactivar plan"}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
