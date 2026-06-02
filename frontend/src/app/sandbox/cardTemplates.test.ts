// spec: specs/canvas/card-templates.spec.md
import { describe, expect, it } from "vitest";

import { CARD_TEMPLATES, instantiateTemplate, type CardTemplate } from "./cardTemplates";

const VALID_TYPES = new Set(["kpi", "inventory", "saif-tracker"]);

function counterIdGen(): () => string {
  let i = 0;
  return () => `card-${++i}`;
}

describe("instantiateTemplate", () => {
  const tpl = CARD_TEMPLATES[0];

  it("produces a full CardState with generated id, macro zoom and grid position", () => {
    const card = instantiateTemplate(tpl, counterIdGen(), "turn-X", 0);
    expect(card.id).toBe("card-1");
    expect(card.type).toBe(tpl.type);
    expect(card.title).toBe(tpl.spec.title);
    expect(card.zoom).toBe("macro");
    expect(card.position).toEqual({ x: 32, y: 12 });
    expect(card.updatedInTurn).toBe("turn-X");
    expect(card.changeSummary).toBeTruthy();
    expect(card.macroData).toEqual(tpl.spec.macroData);
  });

  it("lays cards out in a 3-column grid by index", () => {
    const g = counterIdGen();
    const c3 = instantiateTemplate(tpl, g, "t", 3); // row 1, col 0
    expect(c3.position).toEqual({ x: 32, y: 292 });
    const c4 = instantiateTemplate(tpl, g, "t", 4); // row 1, col 1
    expect(c4.position).toEqual({ x: 392, y: 292 });
  });

  it("is deterministic given the same idGen + inputs", () => {
    const a = instantiateTemplate(tpl, counterIdGen(), "t", 0);
    const b = instantiateTemplate(tpl, counterIdGen(), "t", 0);
    expect(a).toEqual(b);
  });

  it("defaults meso/micro to {} when a template omits them", () => {
    const bare: CardTemplate = {
      id: "x", label: "x", description: "x", icon: "Activity", type: "kpi",
      spec: { title: "T", macroData: { value: "1" } },
    };
    const card = instantiateTemplate(bare, counterIdGen(), "t", 0);
    expect(card.mesoData).toEqual({});
    expect(card.microData).toEqual({});
  });
});

describe("CARD_TEMPLATES — repertoire integrity (drift guard vs backend schema)", () => {
  it("ships ~10 curated templates with unique ids", () => {
    expect(CARD_TEMPLATES.length).toBeGreaterThanOrEqual(10);
    const ids = CARD_TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each(CARD_TEMPLATES.map((t) => [t.label, t] as const))(
    "template '%s' satisfies the CardState invariants the backend validator enforces",
    (_label, tpl) => {
      // type
      expect(VALID_TYPES.has(tpl.type)).toBe(true);
      // title
      expect(typeof tpl.spec.title).toBe("string");
      expect(tpl.spec.title.length).toBeGreaterThan(0);
      // macroData.value (required, non-empty) — except the generic table whose value may be "—"
      expect(typeof tpl.spec.macroData.value).toBe("string");
      expect(tpl.spec.macroData.value.length).toBeGreaterThan(0);
      // trend, if present, is a valid enum
      if (tpl.spec.macroData.trend !== undefined) {
        expect(["up", "down", "neutral"]).toContain(tpl.spec.macroData.trend);
      }
      // mesoData has chartData OR bullets so the meso view is never blank
      const meso = tpl.spec.mesoData ?? {};
      const hasChart = Array.isArray(meso.chartData) && meso.chartData.length > 0;
      const hasBullets = Array.isArray(meso.bullets) && meso.bullets.length > 0;
      expect(hasChart || hasBullets).toBe(true);
      // chartData points are {label:string, value:number}
      if (hasChart) {
        for (const p of meso.chartData!) {
          expect(typeof p.label).toBe("string");
          expect(typeof p.value).toBe("number");
        }
      }
      // microData.tableRows are arrays of strings, matching headers length when both present
      const micro = tpl.spec.microData ?? {};
      if (micro.tableRows) {
        for (const row of micro.tableRows) {
          expect(Array.isArray(row)).toBe(true);
          for (const cell of row) expect(typeof cell).toBe("string");
          if (micro.tableHeaders) expect(row.length).toBe(micro.tableHeaders.length);
        }
      }
    },
  );

  it("inventory templates expose a 'Reordenar' action cell (renders the action button)", () => {
    const inv = CARD_TEMPLATES.filter((t) => t.type === "inventory");
    expect(inv.length).toBeGreaterThan(0);
    for (const t of inv) {
      const rows = t.spec.microData?.tableRows ?? [];
      const hasReorder = rows.some((r) => r.includes("Reordenar"));
      expect(hasReorder).toBe(true);
    }
  });
});
