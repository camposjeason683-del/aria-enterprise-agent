/** Card model + the text-tag parser the agent emits (shared by the dashboard). */
export interface CardState {
  id: string;
  title: string;
  type: "kpi" | "saif-tracker" | "inventory";
  macroData: { value: string; change?: string; trend?: "up" | "down" | "neutral"; subtitle?: string };
  mesoData?: { chartData?: { label: string; value: number }[]; bullets?: string[]; status?: string };
  microData?: { tableHeaders?: string[]; tableRows?: string[][]; sqlQuery?: string };
  position: { x: number; y: number };
  zoom: "macro" | "meso" | "micro";
}

export const ZOOM_DIMS: Record<CardState["zoom"], { w: number; h: number }> = {
  macro: { w: 320, h: 220 },
  meso: { w: 450, h: 340 },
  micro: { w: 720, h: 460 },
};

export function nextZoom(z: CardState["zoom"]): CardState["zoom"] {
  return z === "macro" ? "meso" : z === "meso" ? "micro" : "macro";
}

const CREATE_RE = /<create_card\s+id="([^"]+)"\s+type="([^"]+)"\s*>([\s\S]*?)<\/create_card>/g;
const UPDATE_RE = /<update_card\s+id="([^"]+)"\s*>([\s\S]*?)<\/update_card>/g;
const DELETE_RE = /<delete_card\s+id="([^"]+)"\s*\/>/g;

export function parseCards(
  content: string,
  prev: Record<string, CardState>,
): Record<string, CardState> {
  const next = { ...prev };
  let idx = Object.keys(next).length;
  let m: RegExpExecArray | null;

  CREATE_RE.lastIndex = 0;
  while ((m = CREATE_RE.exec(content))) {
    try {
      const p = JSON.parse(m[3].trim());
      next[m[1]] = {
        id: m[1],
        type: (m[2] as CardState["type"]) ?? "kpi",
        title: p.title ?? m[1],
        macroData: p.macroData ?? { value: "—" },
        mesoData: p.mesoData,
        microData: p.microData,
        position: p.position ?? { x: (idx % 3) * 352 + 24, y: Math.floor(idx / 3) * 252 + 24 },
        zoom: "macro",
      };
      idx++;
    } catch {
      /* ignore malformed card json */
    }
  }
  UPDATE_RE.lastIndex = 0;
  while ((m = UPDATE_RE.exec(content))) {
    if (!next[m[1]]) continue;
    try {
      Object.assign(next[m[1]], JSON.parse(m[2].trim()));
    } catch {
      /* ignore */
    }
  }
  DELETE_RE.lastIndex = 0;
  while ((m = DELETE_RE.exec(content))) delete next[m[1]];
  return next;
}

/** Strip the card tags so the chat bubble shows only the prose. */
export function stripCardTags(content: string): string {
  return content
    .replace(CREATE_RE, "")
    .replace(UPDATE_RE, "")
    .replace(DELETE_RE, "")
    .trim();
}
