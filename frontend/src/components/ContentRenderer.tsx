"use client";
/**
 * ContentRenderer — the business-agnostic body painter mounted inside
 * SmartWrapper. It draws a card's data by (type, zoom) via a registry, so a new
 * card type only needs to register its bodies; the physics come from SmartWrapper.
 *
 * The existing Macro/Meso/Micro bodies in sandbox/page.tsx (lines ~2041-2255)
 * register into this during integration via registerCardRenderer().
 * // spec: specs/canvas/smart-wrapper.spec.md
 */
import type { ComponentType } from "react";

export type CardZoom = "macro" | "meso" | "micro";

export interface CardLike {
  type: string;
  zoom: CardZoom;
  title: string;
  macroData?: { value?: string; change?: string; trend?: string; subtitle?: string };
  mesoData?: unknown;
  microData?: unknown;
}

export type CardBody = ComponentType<{ card: CardLike }>;

const REGISTRY: Record<string, Partial<Record<CardZoom, CardBody>>> = {};

/** Register a body component for a (card type, zoom level). */
export function registerCardRenderer(type: string, zoom: CardZoom, body: CardBody): void {
  (REGISTRY[type] ??= {})[zoom] = body;
}

function DefaultBody({ card }: { card: CardLike }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide opacity-60">{card.title}</span>
      <span className="text-2xl font-semibold">{card.macroData?.value ?? "—"}</span>
      {card.macroData?.subtitle ? (
        <span className="text-xs opacity-50">{card.macroData.subtitle}</span>
      ) : null}
    </div>
  );
}

export function ContentRenderer({ card }: { card: CardLike }) {
  const Body = REGISTRY[card.type]?.[card.zoom] ?? DefaultBody;
  return <Body card={card} />;
}
