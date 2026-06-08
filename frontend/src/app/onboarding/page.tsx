"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  connectWooCommerce,
  importFile,
  importPreview,
  type ImportResult,
  type Mapping,
  type PreviewResult,
} from "@/lib/api";

type Method = "choose" | "woo" | "csv";

const CANON: { key: string; label: string }[] = [
  { key: "date", label: "Fecha" },
  { key: "product_name", label: "Producto" },
  { key: "quantity", label: "Cantidad" },
  { key: "price", label: "Precio (opcional)" },
];

const input =
  "rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400";
const primary =
  "rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2.5 text-sm font-medium transition-colors";

export default function OnboardingPage() {
  const router = useRouter();
  const [method, setMethod] = useState<Method>("choose");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<ImportResult | "woo" | null>(null);

  // WooCommerce
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");

  // CSV / Excel
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});

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

  async function onFile(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setBusy(true);
    setError("");
    try {
      const p = await importPreview(f);
      setPreview(p);
      setMapping(p.mapping);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function setMap(field: string, header: string) {
    const next = { ...mapping };
    if (header) next[field] = header;
    else delete next[field];
    setMapping(next);
    if (file) {
      try {
        const p = await importPreview(file, next);
        setPreview({ ...p, mapping: next });
      } catch {
        /* keep showing the prior preview */
      }
    }
  }

  async function confirmImport() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      setDone(await importFile(file, mapping));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#0a0a0b] text-white px-4 py-10">
      <div className="w-full max-w-2xl rounded-3xl border border-white/10 bg-[#111113]/80 p-8 backdrop-blur-xl shadow-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Conectá tu negocio</h1>
        <p className="mt-1 text-sm text-white/50">
          ARIA necesita tus ventas para empezar a proyectar y proponer.
        </p>

        {/* ── Done ── */}
        {done ? (
          <div className="mt-6 flex flex-col gap-4">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
              {done === "woo" ? (
                <>✅ WooCommerce conectado. La primera sincronización corre en breve.</>
              ) : (
                <>
                  ✅ Importadas <strong>{done.imported}</strong> filas · {done.ledger.rows} días de
                  ledger · {done.ledger.products_added} productos.
                </>
              )}
            </div>
            <button className={primary} onClick={() => router.push("/dashboard")}>
              Ver mi tablero →
            </button>
          </div>
        ) : method === "choose" ? (
          /* ── Choose ── */
          <div className="mt-6 flex flex-col gap-3">
            <button className={primary} onClick={() => setMethod("woo")}>
              Conectar WooCommerce
            </button>
            <button
              className="rounded-xl border border-white/15 hover:bg-white/5 px-4 py-2.5 text-sm transition-colors"
              onClick={() => setMethod("csv")}
            >
              Subir un archivo (CSV o Excel)
            </button>
          </div>
        ) : method === "woo" ? (
          /* ── WooCommerce ── */
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
            <p className="text-xs text-white/40">
              ¿Dónde saco mis keys? En WooCommerce → Ajustes → Avanzado → REST API → “Crear clave”
              (permiso de lectura).
            </p>
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button disabled={busy} className={primary}>{busy ? "Conectando…" : "Conectar"}</button>
            <button type="button" className="text-xs text-white/40 hover:text-white/70" onClick={() => setMethod("choose")}>← volver</button>
          </form>
        ) : (
          /* ── CSV / Excel wizard ── */
          <div className="mt-6 flex flex-col gap-4">
            {!preview ? (
              <>
                <p className="text-xs text-white/50">
                  Aceptamos CSV o Excel, con cualquier separador (`,` o `;`) y acentos. Idealmente con
                  columnas de fecha, producto, cantidad y precio.
                </p>
                <input
                  className={input}
                  type="file"
                  accept=".csv,.xlsx,.xls,text/csv"
                  onChange={(e) => onFile(e.target.files?.[0])}
                />
                {busy && <p className="text-sm text-white/40">Leyendo el archivo…</p>}
                {error && <p className="text-xs text-red-400">{error}</p>}
                <button type="button" className="text-xs text-white/40 hover:text-white/70" onClick={() => setMethod("choose")}>← volver</button>
              </>
            ) : (
              <>
                {/* Column mapping */}
                <div>
                  <p className="text-sm font-medium text-white/80">Revisá el mapeo de columnas</p>
                  <p className="text-xs text-white/40">Detectamos {preview.headers.length} columnas. Ajustá si algo no quedó bien.</p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {CANON.map(({ key: f, label }) => (
                      <label key={f} className="flex items-center justify-between gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm">
                        <span className="text-white/60">{label}</span>
                        <select
                          className="bg-transparent text-right text-sm outline-none"
                          value={mapping[f] ?? ""}
                          onChange={(e) => setMap(f, e.target.value)}
                        >
                          <option value="" className="bg-[#111113]">— ninguna —</option>
                          {preview.headers.map((h) => (
                            <option key={h} value={h} className="bg-[#111113]">{h}</option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Stats + rejected */}
                <div className="rounded-xl bg-white/5 p-3 text-sm">
                  <span className="text-emerald-300">{preview.stats.ok} filas OK</span>
                  {preview.stats.rejected > 0 && <span className="text-red-300"> · {preview.stats.rejected} rechazadas</span>}
                  {preview.stats.warned > 0 && <span className="text-amber-300"> · {preview.stats.warned} con avisos</span>}
                  {preview.rejected.length > 0 && (
                    <ul className="mt-2 max-h-24 overflow-auto text-xs text-red-300/80">
                      {preview.rejected.slice(0, 5).map((r) => (
                        <li key={r.index}>fila {r.index + 1}: {r.errors.join("; ")}</li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Duplicate warnings */}
                {preview.possible_duplicates.length > 0 && (
                  <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
                    Posibles duplicados (revisá si son el mismo producto):
                    <ul className="mt-1">
                      {preview.possible_duplicates.map((g, i) => (
                        <li key={i}>· {g.join(" / ")}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Sample */}
                {preview.sample.length > 0 && (
                  <div className="overflow-auto rounded-xl border border-white/10">
                    <table className="w-full text-xs">
                      <thead className="text-white/40">
                        <tr>{CANON.map((c) => <th key={c.key} className="px-2 py-1 text-left">{c.label}</th>)}</tr>
                      </thead>
                      <tbody>
                        {preview.sample.slice(0, 5).map((row, i) => (
                          <tr key={i} className="border-t border-white/5">
                            {CANON.map((c) => <td key={c.key} className="px-2 py-1">{String(row[c.key] ?? "")}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {error && <p className="text-xs text-red-400">{error}</p>}
                <div className="flex gap-2">
                  <button disabled={busy || preview.stats.ok === 0} className={primary} onClick={confirmImport}>
                    {busy ? "Importando…" : `Importar ${preview.stats.ok} filas`}
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-white/15 hover:bg-white/5 px-4 py-2.5 text-sm"
                    onClick={() => {
                      setPreview(null);
                      setFile(null);
                    }}
                  >
                    Otro archivo
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
