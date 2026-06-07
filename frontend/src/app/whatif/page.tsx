"use client";
import { useEffect, useState } from "react";

import { forecast, type ForecastResult } from "@/lib/api";

export default function WhatIfPage() {
  const [product, setProduct] = useState("");
  const [price, setPrice] = useState(10);
  const [res, setRes] = useState<ForecastResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Re-forecast when the price slider settles (debounced).
  useEffect(() => {
    if (!product) return;
    const t = setTimeout(async () => {
      setBusy(true);
      setError("");
      try {
        setRes(await forecast(product, 14, price));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      } finally {
        setBusy(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [product, price]);

  return (
    <main className="min-h-screen bg-[#0a0a0b] text-white px-4 py-12">
      <div className="mx-auto max-w-lg">
        <h1 className="text-2xl font-semibold tracking-tight">¿Y si cambio el precio?</h1>
        <p className="mt-1 text-sm text-white/50">
          Mové el precio y mirá cómo se mueve la demanda proyectada (modelo precio→demanda).
        </p>

        <div className="mt-6 rounded-2xl border border-white/10 bg-[#111113]/80 p-6">
          <input
            className="w-full rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm outline-none focus:border-indigo-400"
            placeholder="nombre del producto"
            value={product}
            onChange={(e) => setProduct(e.target.value)}
          />

          <div className="mt-6">
            <div className="flex items-center justify-between text-sm">
              <span className="text-white/50">Precio</span>
              <span className="font-medium">${price.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={1}
              max={100}
              step={0.5}
              value={price}
              onChange={(e) => setPrice(Number(e.target.value))}
              className="mt-2 w-full accent-indigo-500"
            />
          </div>

          <div className="mt-6 min-h-[80px]">
            {error && <p className="text-sm text-red-400">{error}</p>}
            {busy && <p className="text-sm text-white/40">Proyectando…</p>}
            {res && res.status === "success" && (
              <div className="rounded-xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-wide text-white/40">Demanda proyectada (14 días)</p>
                <p className="mt-1 text-3xl font-semibold">
                  {res.proyeccion_total != null ? Math.round(res.proyeccion_total) : "—"}
                </p>
                <p className="mt-2 text-xs text-white/50">
                  {res.model_used}
                  {res.backtest?.mape != null && ` · precisión ~${(100 - res.backtest.mape).toFixed(0)}%`}
                </p>
              </div>
            )}
            {res && res.status !== "success" && (
              <p className="text-sm text-white/40">{res.summary ?? "Sin suficiente historial para este producto."}</p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
