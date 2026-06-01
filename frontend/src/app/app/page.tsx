"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { SmartWrapper } from "@/components/SmartWrapper";
import { chat, loadCanvas, me, saveCanvas, type Me } from "@/lib/api";
import { getToken, signOut } from "@/lib/auth";
import {
  parseCards,
  stripCardTags,
  nextZoom,
  ZOOM_DIMS,
  type CardState,
} from "@/lib/cards";

interface ChatMsg {
  role: "user" | "assistant";
  text: string;
}

export default function DashboardPage() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Me | null>(null);
  const [cards, setCards] = useState<Record<string, CardState>>({});
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── auth gate + initial load ──────────────────────────────────────────────
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    me()
      .then(setIdentity)
      .catch(() => router.replace("/login"));
    loadCanvas<{ cards: Record<string, CardState> }>().then((state) => {
      if (state?.cards) setCards(state.cards);
    });
  }, [router]);

  const persist = useCallback((nextCards: Record<string, CardState>) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveCanvas({ cards: nextCards });
    }, 600);
  }, []);

  const updateCards = useCallback(
    (updater: (prev: Record<string, CardState>) => Record<string, CardState>) => {
      setCards((prev) => {
        const next = updater(prev);
        persist(next);
        return next;
      });
    },
    [persist],
  );

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const res = await chat(text);
      const prose = stripCardTags(res.response) || "Listo.";
      setMessages((m) => [...m, { role: "assistant", text: prose }]);
      updateCards((prev) => parseCards(res.response, prev));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error";
      if (msg === "UNAUTHENTICATED") {
        signOut();
        router.replace("/login");
        return;
      }
      setMessages((m) => [...m, { role: "assistant", text: `⚠️ ${msg}` }]);
    } finally {
      setBusy(false);
    }
  }

  const logout = () => {
    signOut();
    router.replace("/login");
  };

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-[#0a0a0b] text-white">
      {/* Canvas */}
      <section className="relative flex-1 overflow-hidden">
        <header className="absolute left-0 right-0 top-0 z-50 flex items-center justify-between px-6 py-4">
          <div>
            <span className="text-sm font-semibold tracking-tight">ARIA-OS</span>
            <span className="ml-2 text-xs text-white/40">
              {identity ? `${identity.role} · tenant ${identity.tenant_id.slice(0, 8)}` : "…"}
            </span>
          </div>
          <button onClick={logout} className="text-xs text-white/40 hover:text-white/80">
            salir
          </button>
        </header>

        {Object.keys(cards).length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="max-w-xs text-center text-sm text-white/30">
              Pedile a ARIA que arme tu tablero.<br />
              Ej: <span className="text-white/50">&ldquo;muéstrame mis ventas del mes&rdquo;</span>
            </p>
          </div>
        )}

        {Object.values(cards).map((card) => {
          const dims = ZOOM_DIMS[card.zoom];
          return (
            <SmartWrapper
              key={card.id}
              cardId={card.id}
              zoom={card.zoom}
              clampedX={card.position.x}
              clampedY={card.position.y}
              visualWidth={dims.w}
              visualHeight={dims.h}
              isDragging={draggingId === card.id}
              isResizing={false}
              shouldAnimateLayout={false}
              onDragStart={() => setDraggingId(card.id)}
              onDragEnd={(_e, info) => {
                setDraggingId(null);
                updateCards((prev) => {
                  const c = prev[card.id];
                  if (!c) return prev;
                  return {
                    ...prev,
                    [card.id]: {
                      ...c,
                      position: {
                        x: Math.max(0, c.position.x + info.offset.x),
                        y: Math.max(0, c.position.y + info.offset.y),
                      },
                    },
                  };
                });
              }}
            >
              <button
                onClick={() =>
                  updateCards((prev) => ({
                    ...prev,
                    [card.id]: { ...prev[card.id], zoom: nextZoom(prev[card.id].zoom) },
                  }))
                }
                className="h-full w-full cursor-grab overflow-hidden rounded-[1.75rem] border border-white/10 bg-[#111113]/90 p-5 text-left shadow-2xl backdrop-blur-2xl active:cursor-grabbing"
              >
                <CardBody card={card} />
              </button>
            </SmartWrapper>
          );
        })}
      </section>

      {/* Chat panel */}
      <aside className="flex w-[360px] shrink-0 flex-col border-l border-white/10 bg-[#0d0d0f]">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="mt-8 text-center text-xs text-white/30">
              Hablá con ARIA, tu COO virtual.
            </p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${
                m.role === "user"
                  ? "ml-auto bg-indigo-500/90"
                  : "bg-white/5 text-white/90"
              }`}
            >
              {m.text}
            </div>
          ))}
          {busy && <div className="text-xs text-white/30">ARIA está pensando…</div>}
        </div>
        <div className="border-t border-white/10 p-3">
          <div className="flex items-end gap-2">
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Preguntale a ARIA…"
              className="max-h-32 flex-1 resize-none rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
            <button
              onClick={send}
              disabled={busy}
              className="rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:opacity-40 px-3.5 py-2 text-sm font-medium"
            >
              ↑
            </button>
          </div>
        </div>
      </aside>
    </main>
  );
}

function CardBody({ card }: { card: CardState }) {
  const trendColor =
    card.macroData.trend === "up"
      ? "text-emerald-400"
      : card.macroData.trend === "down"
      ? "text-red-400"
      : "text-white/50";
  return (
    <div className="flex h-full flex-col">
      <span className="text-[0.7rem] uppercase tracking-wide text-white/40">{card.title}</span>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-3xl font-semibold">{card.macroData.value}</span>
        {card.macroData.change && (
          <span className={`text-xs font-medium ${trendColor}`}>{card.macroData.change}</span>
        )}
      </div>
      {card.macroData.subtitle && (
        <span className="text-xs text-white/40">{card.macroData.subtitle}</span>
      )}

      {card.zoom !== "macro" && card.mesoData?.bullets && (
        <ul className="mt-3 space-y-1 text-xs text-white/60">
          {card.mesoData.bullets.slice(0, 5).map((b, i) => (
            <li key={i}>• {b}</li>
          ))}
        </ul>
      )}

      {card.zoom === "micro" && card.microData?.tableRows && (
        <div className="mt-3 overflow-auto">
          <table className="w-full text-left text-[0.7rem]">
            {card.microData.tableHeaders && (
              <thead className="text-white/40">
                <tr>
                  {card.microData.tableHeaders.map((h, i) => (
                    <th key={i} className="pb-1 pr-3 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody className="text-white/70">
              {card.microData.tableRows.slice(0, 8).map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} className="py-0.5 pr-3">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
