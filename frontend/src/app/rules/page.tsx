"use client";
import { useEffect, useState } from "react";

import { createRule, deleteRule, listRules, type Rule } from "@/lib/api";

const METRICS = [
  { value: "stockout_risk_max", label: "Riesgo de quiebre (máx)" },
  { value: "stockout_risk_critical_count", label: "Productos en riesgo crítico" },
  { value: "net_margin_pct", label: "Margen neto %" },
  { value: "revenue_30d", label: "Ingresos 30 días" },
];

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [metric, setMetric] = useState(METRICS[0].value);
  const [op, setOp] = useState(">");
  const [threshold, setThreshold] = useState(80);

  async function load() {
    try {
      setRules(await listRules());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function add() {
    setError("");
    try {
      await createRule({ name, metric, op, threshold });
      setName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const input =
    "rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm outline-none focus:border-indigo-400";

  return (
    <main className="min-h-screen bg-[#0a0a0b] text-white px-4 py-12">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Reglas automáticas</h1>
        <p className="mt-1 text-sm text-white/50">Si una métrica cruza un umbral, ARIA propone una acción.</p>
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

        <div className="mt-6 rounded-2xl border border-white/10 bg-[#111113]/80 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${input} flex-1 min-w-[140px]`} placeholder="nombre de la regla" value={name} onChange={(e) => setName(e.target.value)} />
            <select className={input} value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <select className={input} value={op} onChange={(e) => setOp(e.target.value)}>
              {[">", "<", ">=", "<=", "=="].map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <input className={`${input} w-24`} type="number" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
            <button onClick={add} disabled={!name} className="rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-medium">
              Crear
            </button>
          </div>
        </div>

        <ul className="mt-4 flex flex-col gap-2">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
              <span>
                <strong>{r.name}</strong> — {r.metric} {r.op} {r.threshold} → {r.action}
              </span>
              <button onClick={() => deleteRule(r.id).then(load)} className="text-xs text-red-400 hover:text-red-300">
                eliminar
              </button>
            </li>
          ))}
          {rules.length === 0 && <li className="text-sm text-white/40">Sin reglas todavía.</li>}
        </ul>
      </div>
    </main>
  );
}
