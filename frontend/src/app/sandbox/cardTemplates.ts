// spec: specs/canvas/card-templates.spec.md
/**
 * Curated card "repertoire" for the Sandbox canvas.
 *
 * Each template is a ready-made card spec (sample/placeholder data) the user can
 * insert with one click — no agent round-trip. The agent can later "fill it with
 * real data" (RLS) via manage_canvas_widgets(update).
 *
 * CANONICAL SCHEMA: the card shape is `CardState` in ./timelineReducer (do not
 * fork it). The backend agent's view of the same schema lives in the
 * CANVAS_PROTOCOL block in src/config.py — keep both in sync with CardState.
 *
 * This module is PURE (no React/JSX, no Date.now/Math.random) so it's unit-testable
 * like timelineReducer.ts. Icons are referenced by NAME (string) and resolved to a
 * lucide component in page.tsx — keeping this file dependency-free.
 *
 * Render contract (from the Macro/Meso/MicroBody renderers in page.tsx):
 *   - macroData.value is ALWAYS present.
 *   - mesoData has chartData[] OR bullets[] (never both empty), so the meso view is
 *     never blank.
 *   - inventory tables use the literal cell value "Reordenar" to render the action button.
 */
import type { CardState } from "./timelineReducer";

export interface CardTemplate {
  /** Template id (NOT the inserted card id, which is generated fresh). */
  id: string;
  /** Palette label. */
  label: string;
  /** One-line palette subtitle. */
  description: string;
  /** lucide icon name, resolved to a component in page.tsx. */
  icon: string;
  type: CardState["type"];
  /** The card body. Position/zoom/ids are filled by instantiateTemplate.
   *  mesoData/microData are optional (instantiateTemplate defaults them to {}). */
  spec: Pick<CardState, "title" | "macroData"> &
    Partial<Pick<CardState, "mesoData" | "microData" | "changeSummary">>;
}

/**
 * Turn a template into a full CardState ready to drop into a node's activeCards.
 * `idGen` is injected for deterministic tests; `index` lays cards out in a 3-col
 * grid (mirrors parseCardsFromMessage in timelineReducer.ts).
 */
export function instantiateTemplate(
  tpl: CardTemplate,
  idGen: () => string,
  turnId: string,
  index: number,
): CardState {
  return {
    id: idGen(),
    title: tpl.spec.title,
    type: tpl.type,
    macroData: tpl.spec.macroData,
    mesoData: tpl.spec.mesoData ?? {},
    microData: tpl.spec.microData ?? {},
    position: {
      x: (index % 3) * 360 + 32,
      y: Math.floor(index / 3) * 280 + 12,
    },
    zoom: "macro",
    updatedInTurn: turnId,
    changeSummary: tpl.spec.changeSummary ?? "Plantilla insertada (datos de muestra)",
  };
}

const SAMPLE_NOTE = "Datos de muestra";
const SAMPLE_SQL = "-- Se completará con datos reales bajo RLS";
const SAMPLE_LOGS = ["Plantilla insertada localmente (sin consulta)"];

export const CARD_TEMPLATES: CardTemplate[] = [
  {
    id: "tpl-ventas-mensuales",
    label: "Ventas mensuales",
    description: "KPI de revenue con desglose semanal",
    icon: "Activity",
    type: "kpi",
    spec: {
      title: "Ventas Mensuales",
      changeSummary: "Plantilla de ventas (datos de muestra)",
      macroData: { value: "$00,000", change: "+0%", trend: "up", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Sem 1", value: 25 },
          { label: "Sem 2", value: 40 },
          { label: "Sem 3", value: 32 },
          { label: "Sem 4", value: 48 },
        ],
        bullets: ["Rellená con datos reales para ver el detalle"],
      },
      microData: {
        tableHeaders: ["Fecha", "Cliente", "Monto", "Estado"],
        tableRows: [
          ["—", "Cliente A", "$0", "Muestra"],
          ["—", "Cliente B", "$0", "Muestra"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-alerta-inventario",
    label: "Alerta de inventario",
    description: "Ítems por debajo del stock mínimo",
    icon: "Database",
    type: "inventory",
    spec: {
      title: "Alertas de Inventario",
      changeSummary: "Plantilla de inventario (datos de muestra)",
      macroData: { value: "0 Alertas", change: "Muestra", trend: "down", subtitle: SAMPLE_NOTE },
      mesoData: { bullets: ["Producto A: 0 (mínimo 0)", "Producto B: 0 (mínimo 0)"] },
      microData: {
        tableHeaders: ["Ítem", "Ubicación", "Stock", "Límite", "Acción"],
        tableRows: [
          ["Producto A", "Almacén", "0", "0", "Reordenar"],
          ["Producto B", "Almacén", "0", "0", "Reordenar"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-pnl-margenes",
    label: "P&L / Márgenes",
    description: "Estado de resultados resumido",
    icon: "FileText",
    type: "kpi",
    spec: {
      title: "P&L / Márgenes",
      changeSummary: "Plantilla de finanzas (datos de muestra)",
      macroData: { value: "0%", change: "Margen", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Ingresos", value: 100 },
          { label: "COGS", value: 60 },
          { label: "Bruto", value: 40 },
          { label: "Neto", value: 18 },
        ],
      },
      microData: {
        tableHeaders: ["Línea", "Monto", "% Ingresos"],
        tableRows: [
          ["Ingresos", "$0", "100%"],
          ["COGS", "$0", "0%"],
          ["Margen bruto", "$0", "0%"],
          ["Margen neto", "$0", "0%"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-forecast-reorden",
    label: "Forecast & reorden",
    description: "Proyección de demanda y punto de reorden",
    icon: "Target",
    type: "kpi",
    spec: {
      title: "Forecast & Reorden",
      changeSummary: "Plantilla de forecasting (datos de muestra)",
      macroData: { value: "0 días", change: "Cobertura", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Sem 1", value: 30 },
          { label: "Sem 2", value: 28 },
          { label: "Sem 3", value: 35 },
          { label: "Sem 4", value: 33 },
        ],
        bullets: ["Punto de reorden estimado: —"],
      },
      microData: {
        tableHeaders: ["Producto", "Demanda/sem", "Punto reorden", "Días cobertura"],
        tableRows: [
          ["Producto A", "0", "0", "0"],
          ["Producto B", "0", "0", "0"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-top-clientes",
    label: "Top clientes",
    description: "Clientes con mayor revenue",
    icon: "Target",
    type: "kpi",
    spec: {
      title: "Top Clientes",
      changeSummary: "Plantilla de clientes (datos de muestra)",
      macroData: { value: "0 clientes", change: "Top", trend: "up", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Cliente A", value: 50 },
          { label: "Cliente B", value: 35 },
          { label: "Cliente C", value: 28 },
          { label: "Cliente D", value: 20 },
        ],
      },
      microData: {
        tableHeaders: ["Cliente", "Pedidos", "Revenue", "Ticket prom."],
        tableRows: [
          ["Cliente A", "0", "$0", "$0"],
          ["Cliente B", "0", "$0", "$0"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-saif-tracker",
    label: "Trazabilidad SAIF",
    description: "Estado de políticas de seguridad activas",
    icon: "Shield",
    type: "saif-tracker",
    spec: {
      title: "Trazabilidad SAIF 2.0",
      changeSummary: "Plantilla de seguridad (datos de muestra)",
      macroData: { value: "Pendiente", change: "—", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        bullets: ["Sandbox: por verificar", "Human-in-the-loop: por verificar", "Aislamiento: por verificar"],
      },
      microData: {
        tableHeaders: ["Herramienta", "Verificación", "Privilegios", "Estado"],
        tableRows: [
          ["—", "—", "—", "Muestra"],
          ["—", "—", "—", "Muestra"],
        ],
        sqlQuery: "SHOW ACTIVE SECURITY REGISTERS",
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-cuentas-por-cobrar",
    label: "Cuentas por cobrar",
    description: "Aging de facturas pendientes",
    icon: "Clock",
    type: "kpi",
    spec: {
      title: "Cuentas por Cobrar",
      changeSummary: "Plantilla de cobranzas (datos de muestra)",
      macroData: { value: "$00,000", change: "Por cobrar", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        bullets: ["0–30 días: $0", "31–60 días: $0", "61–90 días: $0", "+90 días: $0"],
      },
      microData: {
        tableHeaders: ["Cliente", "Factura", "Monto", "Vencimiento", "Estado"],
        tableRows: [
          ["Cliente A", "—", "$0", "—", "Muestra"],
          ["Cliente B", "—", "$0", "—", "Muestra"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-tabla-generica",
    label: "Tabla genérica",
    description: "Tabla editable de propósito general",
    icon: "FileText",
    type: "kpi",
    spec: {
      title: "Tabla",
      changeSummary: "Plantilla genérica (datos de muestra)",
      macroData: { value: "—", change: "", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: { bullets: ["Editá estos datos o pedile al agente que la complete"] },
      microData: {
        tableHeaders: ["Columna A", "Columna B", "Columna C"],
        tableRows: [
          ["—", "—", "—"],
          ["—", "—", "—"],
          ["—", "—", "—"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-embudo-ventas",
    label: "Embudo de ventas",
    description: "Conversión por etapa del pipeline",
    icon: "Target",
    type: "kpi",
    spec: {
      title: "Embudo de Ventas",
      changeSummary: "Plantilla de pipeline (datos de muestra)",
      macroData: { value: "0%", change: "Conversión", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Leads", value: 100 },
          { label: "Calificados", value: 60 },
          { label: "Propuesta", value: 30 },
          { label: "Cierre", value: 12 },
        ],
      },
      microData: {
        tableHeaders: ["Etapa", "Cantidad", "Conversión"],
        tableRows: [
          ["Leads", "0", "100%"],
          ["Calificados", "0", "0%"],
          ["Propuesta", "0", "0%"],
          ["Cierre", "0", "0%"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
  {
    id: "tpl-comparativa-periodos",
    label: "Comparativa de períodos",
    description: "Período actual vs. anterior",
    icon: "Activity",
    type: "kpi",
    spec: {
      title: "Comparativa de Períodos",
      changeSummary: "Plantilla comparativa (datos de muestra)",
      macroData: { value: "0%", change: "vs. anterior", trend: "neutral", subtitle: SAMPLE_NOTE },
      mesoData: {
        chartData: [
          { label: "Período A", value: 40 },
          { label: "Período B", value: 52 },
        ],
      },
      microData: {
        tableHeaders: ["Métrica", "Período A", "Período B", "Δ"],
        tableRows: [
          ["Revenue", "$0", "$0", "0%"],
          ["Pedidos", "0", "0", "0%"],
          ["Ticket prom.", "$0", "$0", "0%"],
        ],
        sqlQuery: SAMPLE_SQL,
        executionLogs: SAMPLE_LOGS,
        safetyScore: 100,
      },
    },
  },
];
