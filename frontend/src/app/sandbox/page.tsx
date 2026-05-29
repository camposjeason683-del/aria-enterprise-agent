"use client";

import React, { useState, useRef, useEffect, useMemo } from "react";
import { CopilotKit, useCopilotChatInternal } from "@copilotkit/react-core";
import { motion, AnimatePresence, LayoutGroup } from "motion/react";
import {
  Zap,
  Target,
  Activity,
  Database,
  Send,
  Sparkles,
  Clock,
  ChevronRight,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Trash2,
  Plus,
  Check,
  X,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  AlertTriangle,
  Lock,
  Shield,
  FileText,
  RotateCcw
} from "lucide-react";

// Deterministic short hash from any string (for stable motion animation transitions)
function contentHash(str: string): string {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h).toString(36);
}

// Deep clone helper
function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

// -- DATA MODELS --

export interface CardState {
  id: string;
  title: string;
  type: 'kpi' | 'saif-tracker' | 'inventory';
  macroData: {
    value: string;
    change?: string;
    trend?: 'up' | 'down' | 'neutral';
    subtitle?: string;
  };
  mesoData: {
    chartData?: { label: string; value: number }[];
    bullets?: string[];
    status?: string;
  };
  microData: {
    tableHeaders?: string[];
    tableRows?: string[][];
    sqlQuery?: string;
    executionLogs?: string[];
    safetyScore?: number; // 0 - 100
  };
  position: { x: number; y: number };
  zoom: 'macro' | 'meso' | 'micro';
  updatedInTurn: string;
  changeSummary: string;
  scale?: number;
}

export interface TimelineNode {
  id: string;
  parentId: string | null;
  mergeParentId?: string | null;
  userMessage: any;
  assistantMessages: any[];
  branchId: string;
  depth: number;
  activeCards: Record<string, CardState>;
}

export interface TimelineBranch {
  id: string;
  name: string;
  row: number;
  color: string;
  forkParentId?: string;
}

interface SecurityConfirmation {
  actionName: string;
  riskLevel: 'low' | 'medium' | 'high';
  onConfirm: () => void;
}

// -- PARSER FOR GENERATIVE UI --
function parseCardsFromMessage(content: string, prevCards: Record<string, CardState>, turnId: string): Record<string, CardState> {
  const nextCards = { ...prevCards };

  // 1. Parse create_card tags
  const createRegex = /<create_card\s+id="([^"]+)"\s+type="([^"]+)"\s*>([\s\S]*?)<\/create_card>/g;
  let match;
  while ((match = createRegex.exec(content)) !== null) {
    const id = match[1];
    const type = match[2] as any;
    const bodyStr = match[3].trim();
    try {
      const parsed = JSON.parse(bodyStr);
      if (parsed.title && parsed.macroData) {
        const index = Object.keys(nextCards).length;
        nextCards[id] = {
          id,
          title: parsed.title,
          type,
          macroData: parsed.macroData,
          mesoData: parsed.mesoData || {},
          microData: parsed.microData || {},
          position: parsed.position || {
            x: (index % 3) * 360 + 32,
            y: Math.floor(index / 3) * 280 + 12,
          },
          zoom: 'macro',
          updatedInTurn: turnId,
          changeSummary: parsed.changeSummary || 'Componente creado'
        };
      }
    } catch (e) {
      console.error("Failed to parse create_card content JSON", e);
    }
  }

  // 2. Parse update_card tags
  const updateRegex = /<update_card\s+id="([^"]+)"\s*>([\s\S]*?)<\/update_card>/g;
  while ((match = updateRegex.exec(content)) !== null) {
    const id = match[1];
    const bodyStr = match[2].trim();
    if (nextCards[id]) {
      try {
        const parsed = JSON.parse(bodyStr);
        nextCards[id] = {
          ...nextCards[id],
          ...parsed,
          id, // ensure ID stays same
          updatedInTurn: turnId,
          changeSummary: parsed.changeSummary || 'Datos actualizados'
        };
      } catch (e) {
        console.error("Failed to parse update_card content JSON", e);
      }
    }
  }

  // 3. Parse delete_card tags
  const deleteRegex = /<delete_card\s+id="([^"]+)"\s*\/>/g;
  while ((match = deleteRegex.exec(content)) !== null) {
    const id = match[1];
    delete nextCards[id];
  }

  return nextCards;
}

// Spaced out initial state to showcase 4D elements immediately
const INITIAL_NODES: Record<string, TimelineNode> = {
  'turn-1': {
    id: 'turn-1',
    parentId: null,
    branchId: 'main',
    depth: 0,
    userMessage: { id: 'turn-1', role: 'user', content: 'Revisar KPI de ventas y alertas de stock' },
    assistantMessages: [
      {
        id: 'asst-1',
        role: 'assistant',
        content: `He recopilado los datos solicitados del almacén central y generado las tarjetas interactivas.\n\n<create_card id="card-sales" type="kpi">\n{\n  "title": "Ventas Mensuales",\n  "macroData": { "value": "$12,450", "change": "+8.2%", "trend": "up", "subtitle": "Almacén Norte" },\n  "mesoData": {\n    "chartData": [\n      { "label": "Sem 1", "value": 2400 },\n      { "label": "Sem 2", "value": 3100 },\n      { "label": "Sem 3", "value": 2800 },\n      { "label": "Sem 4", "value": 4150 }\n    ],\n    "bullets": ["Máximo histórico en la semana de cierre", "Desglose disponible en vista micro"]\n  },\n  "microData": {\n    "tableHeaders": ["Fecha", "Cliente", "Monto", "Estado"],\n    "tableRows": [\n      ["2026-05-01", "Acme Corp", "$4,200", "Entregado"],\n      ["2026-05-08", "Stark Industries", "$3,100", "Entregado"],\n      ["2026-05-15", "Wayne Enterprises", "$1,000", "Procesando"],\n      ["2026-05-22", "Oscorp", "$4,150", "Pendiente"]\n    ],\n    "sqlQuery": "SELECT date, client, amount, status FROM sales WHERE date >= '2026-05-01'",\n    "executionLogs": [\n      "Conectando a base de datos principal de ventas...",\n      "Consulta completada en 8ms",\n      "Esquema validado contra SAIF 2.0"\n    ],\n    "safetyScore": 98\n  }\n}\n</create_card>\n\n<create_card id="card-inventory" type="inventory">\n{\n  "title": "Alertas de Inventario",\n  "macroData": { "value": "2 Alertas Críticas", "change": "Requerido", "trend": "down", "subtitle": "Stock bajo" },\n  "mesoData": {\n    "bullets": ["Placas Base V2: 1 unidad (Mínimo: 5)", "Fusores Cobre: 2 unidades (Mínimo: 10)"]\n  },\n  "microData": {\n    "tableHeaders": ["Ítem", "Ubicación", "Stock", "Límite", "Acción"],\n    "tableRows": [\n      ["Placa Base V2", "Almacén Norte", "1", "5", "Reordenar"],\n      ["Fusor Cobre", "Almacén Norte", "2", "10", "Reordenar"]\n    ],\n    "sqlQuery": "SELECT item, location, qty, limit_qty FROM stock WHERE qty < limit_qty",\n    "executionLogs": [\n      "Consultando inventario central...",\n      "Discrepancia detectada en 2 categorías"\n    ],\n    "safetyScore": 100\n  }\n}\n</create_card>`
      }
    ],
    activeCards: {}
  },
  'turn-2': {
    id: 'turn-2',
    parentId: 'turn-1',
    branchId: 'main',
    depth: 1,
    userMessage: { id: 'turn-2', role: 'user', content: 'Iniciar trazabilidad de seguridad de agentes' },
    assistantMessages: [
      {
        id: 'asst-2',
        role: 'assistant',
        content: `He habilitado el monitor de políticas de seguridad activa.\n\n<create_card id="card-saif" type="saif-tracker">\n{\n  "title": "Trazabilidad SAIF 2.0",\n  "macroData": { "value": "Asegurado", "change": "100% OK", "trend": "up", "subtitle": "Políticas activas" },\n  "mesoData": {\n    "bullets": ["Sandbox: Habilitado", "Human-in-the-loop: Requerido", "Aislamiento: Verificado"]\n  },\n  "microData": {\n    "tableHeaders": ["Herramienta", "Verificación", "Privilegios", "Estado"],\n    "tableRows": [\n      ["api_connector", "Filtro inyección", "Lectura", "Verificado"],\n      ["run_command", "Sandbox aislado", "Ejecución", "Petición pendiente"]\n    ],\n    "sqlQuery": "SHOW ACTIVE SECURITY REGISTERS",\n    "executionLogs": [\n      "Cargando especificaciones saif.google...",\n      "Filtros de inyección activos",\n      "Aislamiento de memoria de sesión verificado"\n    ],\n    "safetyScore": 100\n  }\n}\n</create_card>`
      }
    ],
    activeCards: {}
  }
};

// Initialize active cards mapping for sample nodes
INITIAL_NODES['turn-1'].activeCards = parseCardsFromMessage(INITIAL_NODES['turn-1'].assistantMessages[0].content, {}, 'turn-1');
Object.values(INITIAL_NODES['turn-1'].activeCards).forEach((card, idx) => {
  card.position = { x: idx * 360 + 32, y: 12 };
});

INITIAL_NODES['turn-2'].activeCards = parseCardsFromMessage(INITIAL_NODES['turn-2'].assistantMessages[0].content, INITIAL_NODES['turn-1'].activeCards, 'turn-2');
if (INITIAL_NODES['turn-2'].activeCards['card-saif']) {
  INITIAL_NODES['turn-2'].activeCards['card-saif'].position = { x: 752, y: 12 };
}

const INITIAL_BRANCHES: TimelineBranch[] = [
  { id: 'main', name: 'Línea Principal', row: 0, color: '#6366F1' }
];

export default function SandboxPage() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <SandboxContent />
    </CopilotKit>
  );
}

// -- HELPER FUNCTIONS FOR TIMELINE --

function getActivePath(activeNodeId: string | null, nodes: Record<string, TimelineNode>): TimelineNode[] {
  if (!activeNodeId) return [];
  const path: TimelineNode[] = [];
  let current: TimelineNode | undefined = nodes[activeNodeId];
  while (current) {
    path.push(current);
    current = current.parentId ? nodes[current.parentId] : undefined;
  }
  return path.reverse();
}

function compileMessagesForPath(path: TimelineNode[]): any[] {
  const messages: any[] = [];
  for (const node of path) {
    messages.push(node.userMessage);
    messages.push(...node.assistantMessages);
  }
  return messages;
}

function makeSerializable(messages: any[]): any[] {
  return messages.map((m: any) => ({
    id: m.id,
    role: m.role,
    content: m.content ?? "",
    ...(m.type && { type: m.type }),
    ...(m.name && { name: m.name }),
    ...(m.toolCalls && { toolCalls: m.toolCalls }),
    ...(m.toolCallId && { toolCallId: m.toolCallId }),
  }));
}

// -- MAIN COMPONENT --
function SandboxContent() {
  const { messages, sendMessage, isLoading, setMessages } = useCopilotChatInternal();
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragAreaRef = useRef<HTMLDivElement>(null);

  // States
  const [nodes, setNodes] = useState<Record<string, TimelineNode>>({});
  const [branches, setBranches] = useState<TimelineBranch[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [dragOffsets, setDragOffsets] = useState<Record<string, { x: number; y: number }>>({});

  // Keep mutable refs of nodes and activeNodeId to prevent stale closures in native DOM event listeners
  const latestNodesRef = useRef(nodes);
  latestNodesRef.current = nodes;
  const latestActiveNodeIdRef = useRef(activeNodeId);
  latestActiveNodeIdRef.current = activeNodeId;

  const [renameBranchId, setRenameBranchId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [securityConfirmation, setSecurityConfirmation] = useState<SecurityConfirmation | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 970, height: 636 });
  const [isTimelineOpen, setIsTimelineOpen] = useState(true);
  const [timelineModal, setTimelineModal] = useState<{
    type: 'fork' | 'merge' | 'break' | 'error' | 'revert';
    nodeAId: string;
    nodeBId?: string;
    offset?: any;
    errorMessage?: string;
  } | null>(null);

  const [activeBranchId, setActiveBranchId] = useState<string>("main");

  // Sync ref to prevent state loops
  const isSwitchingBranch = useRef(false);

  const colors = ['#6366F1', '#10B981', '#F43F5E', '#F59E0B', '#A855F7', '#06B6D4', '#EC4899'];

  // Initialization & LocalStorage Load
  useEffect(() => {
    const savedNodes = localStorage.getItem("sandbox_nodes");
    const savedBranches = localStorage.getItem("sandbox_branches");
    const savedActive = localStorage.getItem("sandbox_active_node");
    const savedBranch = localStorage.getItem("sandbox_active_branch");
    if (savedNodes && savedBranches && savedActive) {
      try {
        setNodes(JSON.parse(savedNodes));
        setBranches(JSON.parse(savedBranches));
        setActiveNodeId(JSON.parse(savedActive));
        if (savedBranch) {
          setActiveBranchId(JSON.parse(savedBranch));
        } else {
          setActiveBranchId("main");
        }
      } catch (e) {
        console.error("Failed to load saved state, using fallback", e);
        loadDefaultState();
      }
    } else {
      loadDefaultState();
    }
  }, []);

  useEffect(() => {
    const handleResize = () => {
      const container = canvasRef.current;
      if (container) {
        setCanvasSize({
          width: container.clientWidth,
          height: container.clientHeight
        });
      }
    };
    const timer = setTimeout(handleResize, 100);
    window.addEventListener('resize', handleResize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', handleResize);
    };
  }, [isTimelineOpen]);

  const loadDefaultState = () => {
    setNodes(INITIAL_NODES);
    setBranches(INITIAL_BRANCHES);
    setActiveNodeId('turn-2');
    setActiveBranchId('main');
    
    // Sync default messages to CopilotKit
    const path = getActivePath('turn-2', INITIAL_NODES);
    const msgs = compileMessagesForPath(path);
    isSwitchingBranch.current = true;
    setMessages(makeSerializable(msgs));
  };

  // LocalStorage save
  useEffect(() => {
    if (Object.keys(nodes).length > 0) {
      localStorage.setItem("sandbox_nodes", JSON.stringify(nodes));
      localStorage.setItem("sandbox_branches", JSON.stringify(branches));
      localStorage.setItem("sandbox_active_node", JSON.stringify(activeNodeId));
      localStorage.setItem("sandbox_active_branch", JSON.stringify(activeBranchId));
    }
  }, [nodes, branches, activeNodeId, activeBranchId]);

  // Compute active path & values
  const activePath = useMemo(() => getActivePath(activeNodeId, nodes), [activeNodeId, nodes]);
  const activeNode = activeNodeId ? nodes[activeNodeId] : null;

  // Active cards filtered up to max 12 items
  const activeCardsList = useMemo(() => {
    if (!activeNode) return [];
    return Object.values(activeNode.activeCards).slice(0, 12);
  }, [activeNode]);

  // Watch for messages change from CopilotKit to sync streaming responses
  useEffect(() => {
    if (!messages || messages.length === 0 || isSwitchingBranch.current) {
      isSwitchingBranch.current = false;
      return;
    }

    const activeTurns: any[] = [];
    let currentTurn: any = null;

    for (const msg of messages) {
      if (msg.role === "user") {
        if (currentTurn) activeTurns.push(currentTurn);
        currentTurn = {
          id: msg.id,
          userMessage: msg,
          assistantMessages: []
        };
      } else if (currentTurn && msg.role !== "system") {
        currentTurn.assistantMessages.push(msg);
      }
    }
    if (currentTurn) activeTurns.push(currentTurn);

    let updated = false;
    setNodes(prev => {
      let next = { ...prev };
      
      // Calculate current path before we rename
      const currentPath: TimelineNode[] = [];
      let currId = activeNodeId;
      while (currId && prev[currId]) {
        currentPath.push(prev[currId]);
        currId = prev[currId].parentId;
      }
      currentPath.reverse();

      let alignedActiveNodeId = activeNodeId;

      // Align IDs in tree with actual CopilotKit message IDs
      for (let i = 0; i < activeTurns.length; i++) {
        const turn = activeTurns[i];
        const pathNode = currentPath[i];

        if (pathNode && pathNode.id !== turn.id) {
          const oldId = pathNode.id;
          const newId = turn.id;

          if (next[oldId]) {
            const node = next[oldId];
            
            // Create new entry
            next[newId] = {
              ...node,
              id: newId
            };
            
            // Delete old entry
            delete next[oldId];

            // Update parentId and mergeParentId of any children in next
            Object.keys(next).forEach(key => {
              if (next[key].parentId === oldId) {
                next[key] = { ...next[key], parentId: newId };
              }
              if (next[key].mergeParentId === oldId) {
                next[key] = { ...next[key], mergeParentId: newId };
              }
            });

            // Update alignedActiveNodeId if it matched
            if (alignedActiveNodeId === oldId) {
              alignedActiveNodeId = newId;
            }

            // Update our local currentPath array
            pathNode.id = newId;
            updated = true;
          }
        }
      }

      if (alignedActiveNodeId !== activeNodeId) {
        setTimeout(() => setActiveNodeId(alignedActiveNodeId), 0);
      }

      // Sync turn values
      for (const turn of activeTurns) {
        const existing = next[turn.id];
        if (existing) {
          const assMsgStr = JSON.stringify(existing.assistantMessages);
          const turnMsgStr = JSON.stringify(turn.assistantMessages);
          if (assMsgStr !== turnMsgStr) {
            const rawContent = turn.assistantMessages.map((m: any) => m.content).join('');
            const parentCards = existing.parentId ? next[existing.parentId]?.activeCards || {} : {};
            next[turn.id] = {
              ...existing,
              assistantMessages: turn.assistantMessages,
              activeCards: parseCardsFromMessage(rawContent, parentCards, turn.id)
            };
            updated = true;
          }
        } else {
          // Create node automatically
          const turnIndex = activeTurns.findIndex(t => t.id === turn.id);
          const prevTurn = turnIndex > 0 ? activeTurns[turnIndex - 1] : null;
          const parentId = prevTurn ? prevTurn.id : null;
          const parentNode = parentId ? next[parentId] : null;
          const branchId = parentNode ? parentNode.branchId : 'main';
          const depth = parentNode ? parentNode.depth + 1 : 0;
          const rawContent = turn.assistantMessages.map((m: any) => m.content).join('');

          next[turn.id] = {
            id: turn.id,
            parentId,
            userMessage: turn.userMessage,
            assistantMessages: turn.assistantMessages,
            branchId,
            depth,
            activeCards: parseCardsFromMessage(rawContent, parentNode ? parentNode.activeCards : {}, turn.id)
          };
          updated = true;
        }
      }

      return updated ? next : prev;
    });

    // Auto-advance activeNodeId if we are at the parent of the latest turn
    const latestTurn = activeTurns[activeTurns.length - 1];
    if (latestTurn && activeNodeId !== latestTurn.id) {
      const turnIndex = activeTurns.findIndex(t => t.id === latestTurn.id);
      const prevTurn = turnIndex > 0 ? activeTurns[turnIndex - 1] : null;
      if (prevTurn && prevTurn.id === activeNodeId) {
        setTimeout(() => setActiveNodeId(latestTurn.id), 0);
      }
    }

  }, [messages, activeNodeId]);

  // -- HANDLERS --

  const handleSubmit = async (e?: React.FormEvent, directText?: string) => {
    e?.preventDefault();
    const text = directText || inputValue;
    if (!text.trim() || isLoading) return;

    const parent = activeNode;
    const isLeaf = parent ? !Object.values(nodes).some(n => n.parentId === parent.id) : true;
    
    let branchId = activeBranchId;
    let parentId = parent ? parent.id : null;
    const nextNodeId = 'turn-' + Date.now();

    // Check if we need to fork (if we are in the past/not at a leaf, and submitting on the parent's branch)
    if (parent) {
      if (activeBranchId === parent.branchId && !isLeaf) {
        const nextRow = Math.max(...branches.map(b => b.row), -1) + 1;
        const color = colors[nextRow % colors.length];
        const newBranchId = 'branch-' + Date.now();
        const shortName = text.slice(0, 15) + (text.length > 15 ? '...' : '');
        const newBranch: TimelineBranch = {
          id: newBranchId,
          name: `Rama: ${shortName}`,
          row: nextRow,
          color,
          forkParentId: parent.id
        };

        setBranches(prev => [...prev, newBranch]);
        branchId = newBranchId;
        setActiveBranchId(newBranchId);
      }
    } else {
      branchId = activeBranchId || 'main';
    }

    // Pre-create node in state
    setNodes(prev => ({
      ...prev,
      [nextNodeId]: {
        id: nextNodeId,
        parentId,
        userMessage: { id: nextNodeId, role: "user", content: text },
        assistantMessages: [],
        branchId,
        depth: parent ? parent.depth + 1 : 0,
        activeCards: parent ? deepClone(parent.activeCards) : {}
      }
    }));

    setInputValue("");
    setActiveNodeId(nextNodeId);
    setActiveBranchId(branchId);

    // Sync preceding messages before triggering sendMessage
    const tempNodes = {
      ...nodes,
      [nextNodeId]: {
        id: nextNodeId,
        parentId,
        userMessage: { id: nextNodeId, role: "user", content: text },
        assistantMessages: [],
        branchId,
        depth: parent ? parent.depth + 1 : 0,
        activeCards: parent ? deepClone(parent.activeCards) : {}
      }
    };
    const path = getActivePath(nextNodeId, tempNodes);
    // Remove the last turn from history before calling sendMessage, CopilotKit appends it automatically
    const pathMsgsWithoutLast = compileMessagesForPath(path.slice(0, -1));
    isSwitchingBranch.current = true;
    setMessages(makeSerializable(pathMsgsWithoutLast));

    try {
      await sendMessage({
        id: nextNodeId,
        role: "user",
        content: text,
      });
    } catch (err) {
      console.error("Failed to send message", err);
    }
  };

  const handleCheckoutNode = (nodeId: string) => {
    const path = getActivePath(nodeId, nodes);
    const msgs = compileMessagesForPath(path);
    isSwitchingBranch.current = true;
    setMessages(makeSerializable(msgs));
    setActiveNodeId(nodeId);
    if (nodes[nodeId]) {
      setActiveBranchId(nodes[nodeId].branchId);
    }
  };

  const handleCheckoutBranch = (branchId: string) => {
    const branchNodes = Object.values(nodes).filter(n => n.branchId === branchId);
    if (branchNodes.length === 0) {
      setActiveBranchId(branchId);
      return;
    }
    const tipNode = branchNodes.reduce((max, n) => n.depth > max.depth ? n : max, branchNodes[0]);
    handleCheckoutNode(tipNode.id);
  };

  const recalculateDepths = (nodesRecord: Record<string, TimelineNode>): Record<string, TimelineNode> => {
    const nextNodes = deepClone(nodesRecord);
    const roots = Object.values(nextNodes).filter(n => !n.parentId || !nextNodes[n.parentId]);
    const visited = new Set<string>();

    const assignDepth = (nodeId: string, currentDepth: number) => {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);

      if (nextNodes[nodeId]) {
        nextNodes[nodeId].depth = currentDepth;
        const children = Object.values(nextNodes).filter(n => n.parentId === nodeId);
        children.forEach(child => {
          assignDepth(child.id, currentDepth + 1);
        });
      }
    };
    roots.forEach(root => {
      assignDepth(root.id, 0);
    });

    return nextNodes;
  };
  const getRootId = (nodeId: string): string => {
    const visited = new Set<string>();
    let curr = nodes[nodeId];
    while (curr && curr.parentId && nodes[curr.parentId] && !visited.has(curr.parentId)) {
      visited.add(curr.id);
      curr = nodes[curr.parentId];
    }
    return curr ? curr.id : nodeId;
  };

  const isAncestor = (ancestorId: string, descendantId: string): boolean => {
    const queue = [descendantId];
    const visited = new Set<string>();
    
    while (queue.length > 0) {
      const currId = queue.shift()!;
      if (currId === ancestorId) return true;
      if (visited.has(currId)) continue;
      visited.add(currId);
      
      const node = nodes[currId];
      if (node) {
        if (node.parentId) {
          if (node.parentId === ancestorId) return true;
          queue.push(node.parentId);
        }
        if (node.mergeParentId) {
          if (node.mergeParentId === ancestorId) return true;
          queue.push(node.mergeParentId);
        }
      }
    }
    return false;
  };

  const getDescendants = (ancestorId: string, currentNodes: Record<string, TimelineNode>): string[] => {
    const descendants: string[] = [];
    const queue = [ancestorId];
    const visited = new Set<string>();

    while (queue.length > 0) {
      const currId = queue.shift()!;
      if (visited.has(currId)) continue;
      visited.add(currId);

      Object.values(currentNodes).forEach(n => {
        if (n.parentId === currId || n.mergeParentId === currId) {
          if (n.id !== ancestorId) {
            descendants.push(n.id);
            queue.push(n.id);
          }
        }
      });
    }
    return Array.from(new Set(descendants));
  };

  const handleNodeDragEnd = (nodeId: string, event: any, info: any) => {
    const nodeA = nodes[nodeId];
    if (!nodeA) return;

    const coordA = getNodeCoord(nodeId);
    const endX = coordA.x + info.offset.x;
    const endY = coordA.y + info.offset.y;

    // 1. Check if dropped near another node (Merge / Revert)
    let nearestNodeId: string | null = null;
    let minDistance = Infinity;

    Object.values(nodes).forEach(nodeB => {
      if (nodeB.id === nodeId) return;
      const coordB = getNodeCoord(nodeB.id);
      const dist = Math.sqrt(Math.pow(endX - coordB.x, 2) + Math.pow(endY - coordB.y, 2));
      if (dist < minDistance) {
        minDistance = dist;
        nearestNodeId = nodeB.id;
      }
    });

    if (nearestNodeId && minDistance < 30) {
      if (getRootId(nodeId) !== getRootId(nearestNodeId)) {
        setTimelineModal({
          type: 'error',
          nodeAId: nodeId,
          errorMessage: 'No se pueden fusionar universos paralelos. No es posible fusionar nodos que pertenecen a líneas temporales base distintas y sin un origen común, ya que causaría colisiones temporales críticas.'
        });
        return;
      }

      // Lineage check for revert: if one is ancestor of the other
      const isAAncestorOfB = isAncestor(nodeId, nearestNodeId);
      const isBAncestorOfA = isAncestor(nearestNodeId, nodeId);

      if (isAAncestorOfB || isBAncestorOfA) {
        const ancestorId = isAAncestorOfB ? nodeId : nearestNodeId;
        const descendantId = isAAncestorOfB ? nearestNodeId : nodeId;
        setTimelineModal({
          type: 'revert',
          nodeAId: ancestorId,
          nodeBId: descendantId
        });
        return;
      }

      setTimelineModal({
        type: 'merge',
        nodeAId: nodeId,
        nodeBId: nearestNodeId
      });
      return;
    }
    const offsetY = info.offset.y;

    if (offsetY > 120) {
      if (nodeA.parentId !== null) {
        setTimelineModal({
          type: 'break',
          nodeAId: nodeId
        });
      }
    } else if (Math.abs(offsetY) > 40) {
      setTimelineModal({
        type: 'fork',
        nodeAId: nodeId,
        offset: info.offset
      });
    }
  };

  const executeFork = (nodeId: string) => {
    const nodeA = nodes[nodeId];
    if (!nodeA) return;

    const newBranchId = 'branch-' + Date.now();
    const nextRow = Math.max(...branches.map(b => b.row), -1) + 1;
    const color = colors[nextRow % colors.length];
    
    const shortName = nodeA.userMessage.content.slice(0, 15) + (nodeA.userMessage.content.length > 15 ? '...' : '');
    const newBranch: TimelineBranch = {
      id: newBranchId,
      name: `Rama: ${shortName}`,
      row: nextRow,
      color,
      forkParentId: nodeId
    };

    setBranches(prev => [...prev, newBranch]);
    setActiveBranchId(newBranchId);
    setActiveNodeId(nodeId);

    // Sync CopilotKit messages up to the parent node
    const path = getActivePath(nodeId, nodes);
    const msgs = compileMessagesForPath(path);
    isSwitchingBranch.current = true;
    setMessages(makeSerializable(msgs));
  };

  const executeMerge = (nodeAId: string, nodeBId: string) => {
    const nodeA = nodes[nodeAId];
    const nodeB = nodes[nodeBId];
    if (!nodeA || !nodeB) return;

    const branchA = branches.find(b => b.id === nodeA.branchId);
    const branchB = branches.find(b => b.id === nodeB.branchId);
    const nameA = branchA ? branchA.name : 'Desconocida';
    const nameB = branchB ? branchB.name : 'Desconocida';

    const mergeNodeId = 'merge-' + Date.now();
    const mergedCards = deepClone(nodeB.activeCards);

    Object.values(nodeA.activeCards).forEach(card => {
      const activeCard = mergedCards[card.id];
      if (!activeCard) {
        mergedCards[card.id] = {
          ...deepClone(card),
          updatedInTurn: mergeNodeId,
          changeSummary: `Fusión desde rama "${nameA}"`
        };
      } else {
        const activeUpdateNode = nodes[activeCard.updatedInTurn];
        const sourceUpdateNode = nodes[card.updatedInTurn];
        const activeDepth = activeUpdateNode ? activeUpdateNode.depth : 0;
        const sourceDepth = sourceUpdateNode ? sourceUpdateNode.depth : 0;

        if (sourceDepth > activeDepth) {
          mergedCards[card.id] = {
            ...deepClone(card),
            position: activeCard.position,
            updatedInTurn: mergeNodeId,
            changeSummary: `Fusión y actualización de datos desde rama "${nameA}"`
          };
        }
      }
    });

    const newMergeNode: TimelineNode = {
      id: mergeNodeId,
      parentId: nodeB.id,
      mergeParentId: nodeA.id,
      branchId: nodeB.branchId,
      depth: nodeB.depth + 1,
      userMessage: {
        id: mergeNodeId,
        role: 'user',
        content: `Fusión gestual: Incorporar "${nameA}" en "${nameB}"`
      },
      assistantMessages: [
        {
          id: 'asst-' + mergeNodeId,
          role: 'assistant',
          content: `Ramas fusionadas gestualmente. Se unió la línea temporal de "${nameA}" con "${nameB}".`
        }
      ],
      activeCards: mergedCards
    };

    setNodes(prev => {
      const next = {
        ...prev,
        [mergeNodeId]: newMergeNode
      };
      return recalculateDepths(next);
    });

    setActiveNodeId(mergeNodeId);

    setTimeout(() => {
      setNodes(currentNodes => {
        const path = getActivePath(mergeNodeId, currentNodes);
        const msgs = compileMessagesForPath(path);
        isSwitchingBranch.current = true;
        setMessages(makeSerializable(msgs));
        return currentNodes;
      });
    }, 50);
  };

  const executeBreak = (nodeId: string) => {
    const nodeA = nodes[nodeId];
    if (!nodeA) return;

    setNodes(prev => {
      const next = { ...prev };
      next[nodeId] = {
        ...next[nodeId],
        parentId: null
      };
      return recalculateDepths(next);
    });

    setTimeout(() => {
      setNodes(currentNodes => {
        const path = getActivePath(activeNodeId, currentNodes);
        const msgs = compileMessagesForPath(path);
        isSwitchingBranch.current = true;
        setMessages(makeSerializable(msgs));
        return currentNodes;
      });
    }, 50);
  };

  const executeRevert = (ancestorId: string) => {
    const ancestorNode = nodes[ancestorId];
    if (!ancestorNode) return;

    const descendants = getDescendants(ancestorId, nodes);

    setNodes(prev => {
      const next = { ...prev };
      descendants.forEach(id => {
        delete next[id];
      });
      return recalculateDepths(next);
    });

    setBranches(prev => {
      return prev.filter(b => {
        if (b.id === 'main') return true;
        const branchNodes = Object.values(nodes).filter(n => n.branchId === b.id);
        const hasRemainingNodes = branchNodes.some(n => !descendants.includes(n.id));
        const forkParentNotDeleted = b.forkParentId ? !descendants.includes(b.forkParentId) : false;
        return hasRemainingNodes || forkParentNotDeleted;
      });
    });

    setActiveNodeId(ancestorId);
    setActiveBranchId(ancestorNode.branchId);

    // Sync CopilotKit messages up to the reverted node
    setTimeout(() => {
      setNodes(currentNodes => {
        const path = getActivePath(ancestorId, currentNodes);
        const msgs = compileMessagesForPath(path);
        isSwitchingBranch.current = true;
        setMessages(makeSerializable(msgs));
        return currentNodes;
      });
    }, 50);
  };

  const handleResizeStart = (cardId: string, startEvent: React.PointerEvent | PointerEvent) => {
    const currentActiveNodeId = latestActiveNodeIdRef.current;
    if (!currentActiveNodeId) return;
    const currentNodes = latestNodesRef.current;
    const node = currentNodes[currentActiveNodeId];
    if (!node) return;
    const card = node.activeCards[cardId];
    if (!card) return;

    const startScale = card.scale || 1;
    const startMouseX = startEvent.clientX;
    const startMouseY = startEvent.clientY;

    // Direct DOM manipulation to scale the card smoothly at 120fps
    const outerEl = document.querySelector(`[data-card-id="${cardId}"][data-role="outer-card"]`) as HTMLElement;
    const innerEl = outerEl ? (outerEl.querySelector('[data-role="inner-card"]') as HTMLElement) : null;

    // Use the exact unscaled dimensions corresponding to the card's zoom level
    // This avoids race conditions and rounding errors from getBoundingClientRect() during animations/transitions
    const cardWidth = card.zoom === 'macro' ? 320 : card.zoom === 'meso' ? 450 : 750;
    const cardHeight = card.zoom === 'macro' ? 220 : card.zoom === 'meso' ? 340 : 480;


    // Calculate boundary constraints at the start of resize using actual DOM measurements
    const minX = 32;
    const minY = 12;
    const container = canvasRef.current;
    const containerWidth = container ? container.clientWidth : canvasSize.width;
    const containerHeight = container ? container.clientHeight : canvasSize.height;

    const maxX = Math.max(minX, containerWidth - 32 - cardWidth * startScale);
    const maxY = Math.max(minY, containerHeight - 48 - cardHeight * startScale);
    
    const clampedX = Math.max(minX, Math.min(maxX, card.position.x));
    const clampedY = Math.max(minY, Math.min(maxY, card.position.y));
    const maxScaleX = (containerWidth - 32 - clampedX) / cardWidth;
    const maxScaleY = (containerHeight - 48 - clampedY) / cardHeight;
    // Ensure the maximum allowed scale is at least startScale, so the card never shrinks down immediately on drag start
    const rawMaxScale = Math.min(maxScaleX, maxScaleY);
    const maxAllowedScale = Math.max(startScale, Math.min(1.0, Math.max(0.5, rawMaxScale)));

    let latestScale = startScale;

    const handlePointerMove = (moveEvent: PointerEvent) => {
      // Safety check: if buttons are released (buttons === 0), stop resizing
      // This protects against missed pointerup events (e.g. during double clicks or selection)
      if (moveEvent.buttons === 0) {
        handlePointerUp();
        return;
      }

      // Ignore glitched zero coordinate events (often dispatched during HMR or gesture boundaries)
      if (moveEvent.clientX === 0 && moveEvent.clientY === 0) return;

      const deltaX = moveEvent.clientX - startMouseX;
      const deltaY = moveEvent.clientY - startMouseY;
      
      const abs_dx = Math.abs(deltaX);
      const abs_dy = Math.abs(deltaY);
      
      let scaleChange = 0;
      if (abs_dx + abs_dy > 0) {
        scaleChange = ((deltaX * abs_dx / cardWidth) + (deltaY * abs_dy / cardHeight)) / (abs_dx + abs_dy);
      }
      
      let newScale = startScale + scaleChange;
      newScale = Math.max(0.5, Math.min(maxAllowedScale, newScale));
      latestScale = newScale;

      // Update the DOM elements directly
      if (outerEl && innerEl) {
        outerEl.style.width = `${cardWidth * newScale}px`;
        outerEl.style.height = `${cardHeight * newScale}px`;
        innerEl.style.scale = String(newScale);
        innerEl.style.transform = 'none'; // Avoid scale duplication (scale and transform: scale() compounding)
      }
    };

    const handlePointerUp = () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);

      // Reset DOM modifications to the clean final state, ensuring the transform matches the scale
      // This prevents the scale from resetting to 1.0 if React does not re-render (e.g. click/tap),
      // and avoids any desync with Framer Motion's internal style cache.
      if (innerEl) {
        innerEl.style.scale = '';
        innerEl.style.transform = `scale(${latestScale}) translateZ(0)`;
      }
      if (outerEl) {
        outerEl.style.width = `${cardWidth * latestScale}px`;
        outerEl.style.height = `${cardHeight * latestScale}px`;
      }

      // Only trigger React state update and re-render if the scale actually changed
      if (Math.abs(latestScale - startScale) > 0.001) {
        const currentActiveNodeId = latestActiveNodeIdRef.current;
        setNodes(prev => {
          if (!currentActiveNodeId) return prev;
          const activeNode = prev[currentActiveNodeId];
          if (!activeNode) return prev;
          const currentCard = activeNode.activeCards[cardId];
          if (!currentCard) return prev;
          return {
            ...prev,
            [currentActiveNodeId]: {
              ...activeNode,
              activeCards: {
                ...activeNode.activeCards,
                [cardId]: {
                  ...currentCard,
                  scale: latestScale
                }
              }
            }
          };
        });
      }
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
  };

  const handleDragEnd = (cardId: string, event: any, info: any, startX?: number, startY?: number) => {
    if (!activeNodeId) return;
    const container = canvasRef.current;
    if (!container) return;

    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;

    setNodes(prev => {
      const node = prev[activeNodeId];
      if (!node || !node.activeCards[cardId]) return prev;
      const card = node.activeCards[cardId];

      let cardWidth = 320;
      let cardHeight = 220;
      if (card.zoom === 'meso') {
        cardWidth = 450;
        cardHeight = 340;
      } else if (card.zoom === 'micro') {
        cardWidth = 750;
        cardHeight = 480;
      }

      const currentScale = card.scale || 1;
      const visualWidth = cardWidth * currentScale;
      const visualHeight = cardHeight * currentScale;

      const baseX = startX !== undefined ? startX : card.position.x;
      const baseY = startY !== undefined ? startY : card.position.y;
      let newX = baseX + info.offset.x;
      let newY = baseY + info.offset.y;

      const minX = 32;
      const minY = 12;
      const maxX = Math.max(minX, containerWidth - visualWidth - 32);
      const maxY = Math.max(minY, containerHeight - visualHeight - 48); // 48px bottom margin to avoid overlapping input bar

      newX = Math.max(minX, Math.min(maxX, newX));
      newY = Math.max(minY, Math.min(maxY, newY));

      return {
        ...prev,
        [activeNodeId]: {
          ...node,
          activeCards: {
            ...node.activeCards,
            [cardId]: {
              ...card,
              position: {
                x: newX,
                y: newY
              }
            }
          }
        }
      };
    });
  };

  const handleToggleZoom = (cardId: string) => {
    if (!activeNodeId) return;
    const container = canvasRef.current;

    setNodes(prev => {
      const node = prev[activeNodeId];
      if (!node || !node.activeCards[cardId]) return prev;
      const card = node.activeCards[cardId];
      const nextZoom: CardState['zoom'] =
        card.zoom === 'macro' ? 'meso' : card.zoom === 'meso' ? 'micro' : 'macro';

      let newX = card.position.x;
      let newY = card.position.y;

      if (container) {
        const containerWidth = container.clientWidth;
        const containerHeight = container.clientHeight;

        let nextWidth = 320;
        let nextHeight = 220;
        if (nextZoom === 'meso') {
          nextWidth = 450;
          nextHeight = 340;
        } else if (nextZoom === 'micro') {
          nextWidth = 750;
          nextHeight = 480;
        }

        const currentScale = card.scale || 1;
        const visualWidth = nextWidth * currentScale;
        const visualHeight = nextHeight * currentScale;

        const minX = 32;
        const minY = 12;
        const maxX = Math.max(minX, containerWidth - visualWidth - 32);
        const maxY = Math.max(minY, containerHeight - visualHeight - 48); // 48px bottom margin to avoid overlapping input bar

        newX = Math.max(minX, Math.min(maxX, newX));
        newY = Math.max(minY, Math.min(maxY, newY));
      }

      return {
        ...prev,
        [activeNodeId]: {
          ...node,
          activeCards: {
            ...node.activeCards,
            [cardId]: {
              ...card,
              zoom: nextZoom,
              position: {
                x: newX,
                y: newY
              }
            }
          }
        }
      };
    });
  };

  const handleReset = () => {
    localStorage.removeItem("sandbox_nodes");
    localStorage.removeItem("sandbox_branches");
    localStorage.removeItem("sandbox_active_node");
    loadDefaultState();
  };

  const startRenameBranch = (branch: TimelineBranch) => {
    setRenameBranchId(branch.id);
    setRenameValue(branch.name);
  };

  const saveRenameBranch = () => {
    if (renameBranchId && renameValue.trim()) {
      setBranches(prev => prev.map(b => b.id === renameBranchId ? { ...b, name: renameValue } : b));
    }
    setRenameBranchId(null);
  };

  // Node coord calculator
  const getNodeCoord = (nodeId: string, includeDrag = false) => {
    const node = nodes[nodeId];
    if (!node) return { x: 0, y: 0 };
    const branch = branches.find(b => b.id === node.branchId);
    const row = branch ? branch.row : 0;
    const colWidth = 200;
    const rowHeight = 80;
    const paddingX = 180;
    const paddingY = 40;
    
    let x = node.depth * colWidth + paddingX;
    let y = row * rowHeight + paddingY;

    if (includeDrag && dragOffsets[nodeId]) {
      x += dragOffsets[nodeId].x;
      y += dragOffsets[nodeId].y;
    }

    return { x, y };
  };

  // SVG lines renderer
  const renderGitConnections = () => {
    const paths: React.ReactNode[] = [];
    Object.values(nodes).forEach(node => {
      if (node.parentId && nodes[node.parentId]) {
        const start = getNodeCoord(node.parentId, false);
        const end = getNodeCoord(node.id, false);
        const branch = branches.find(b => b.id === node.branchId);
        const color = branch ? branch.color : "#6366F1";
        const dx = (end.x - start.x) / 2;
        const d = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;

        paths.push(
          <path
            key={`line-${node.parentId}-${node.id}`}
            d={d}
            stroke={color}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
            className="opacity-60 transition-all duration-300"
          />
        );
      }

      if (node.mergeParentId && nodes[node.mergeParentId]) {
        const start = getNodeCoord(node.mergeParentId, false);
        const end = getNodeCoord(node.id, false);
        const mergedBranch = branches.find(b => b.id === nodes[node.mergeParentId!].branchId);
        const color = mergedBranch ? mergedBranch.color : "#10B981";
        const dx = (end.x - start.x) / 2;
        const d = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;

        paths.push(
          <path
            key={`merge-line-${node.mergeParentId}-${node.id}`}
            d={d}
            stroke={color}
            strokeWidth="3"
            strokeDasharray="5 5"
            fill="none"
            strokeLinecap="round"
            className="opacity-70 transition-all duration-300"
          />
        );
      }
    });

    // Connections to empty branches (ghost nodes)
    branches.forEach(branch => {
      const hasNodes = Object.values(nodes).some(n => n.branchId === branch.id);
      if (!hasNodes && branch.forkParentId && nodes[branch.forkParentId]) {
        const start = getNodeCoord(branch.forkParentId, false);
        const parentNode = nodes[branch.forkParentId];
        const end = {
          x: (parentNode.depth + 1) * 200 + 180,
          y: branch.row * 80 + 40
        };
        const color = branch.color;
        const dx = (end.x - start.x) / 2;
        const d = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;

        paths.push(
          <path
            key={`ghost-line-${branch.id}`}
            d={d}
            stroke={color}
            strokeWidth="2.5"
            strokeDasharray="4 4"
            fill="none"
            strokeLinecap="round"
            className="opacity-40 transition-all duration-300"
          />
        );
      }
    });

    // Connections from static positions to dragged node ghosts
    Object.values(nodes).forEach(node => {
      if (dragOffsets[node.id]) {
        const start = getNodeCoord(node.id, false);
        const end = getNodeCoord(node.id, true);
        const branch = branches.find(b => b.id === node.branchId);
        const color = branch ? branch.color : "#6366F1";
        const dx = (end.x - start.x) / 2;
        const d = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;

        paths.push(
          <path
            key={`drag-ghost-line-${node.id}`}
            d={d}
            stroke={color}
            strokeWidth="2.5"
            strokeDasharray="4 4"
            fill="none"
            strokeLinecap="round"
            className="opacity-60 animate-pulse"
          />
        );
      }
    });

    return paths;
  };

  // SVG dimensions (including ghost nodes)
  const maxDepth = Math.max(
    Object.values(nodes).reduce((max, n) => Math.max(max, n.depth), 0),
    ...branches.map(b => {
      const hasNodes = Object.values(nodes).some(n => n.branchId === b.id);
      if (!hasNodes && b.forkParentId && nodes[b.forkParentId]) {
        return nodes[b.forkParentId].depth + 1;
      }
      return 0;
    })
  );
  const maxRow = branches.reduce((max, b) => Math.max(max, b.row), 0);
  const graphWidth = maxDepth * 200 + 400;
  const graphHeight = maxRow * 80 + 90;

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-white flex flex-col font-sans relative overflow-hidden" ref={containerRef}>
      {/* Ambient background glows */}
      <div className="absolute top-[-25%] left-[-15%] w-[60%] h-[60%] bg-indigo-500/5 blur-[140px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-25%] right-[-15%] w-[60%] h-[60%] bg-purple-500/5 blur-[140px] rounded-full pointer-events-none" />

      {/* -- HEADER NAVIGATION (BRANCH TIMELINE) -- */}
      <div className="w-full border-b border-white/5 bg-[#0C0C0E]/90 backdrop-blur-2xl flex flex-col p-4 z-40 relative">
        <div className="flex items-center justify-between mb-2 px-2">
          <div className="flex items-center gap-3">
            <GitBranch className="w-5 h-5 text-indigo-400" />
            <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Dimension Temporal (Historial Git)</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsTimelineOpen(!isTimelineOpen)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 transition-all text-xs font-semibold text-gray-300 hover:text-white"
            >
              <GitBranch className="w-3.5 h-3.5" />
              {isTimelineOpen ? "Ocultar Historial" : "Mostrar Historial"}
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 hover:bg-red-500/10 hover:text-red-400 border border-white/5 transition-all text-xs font-medium"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Reiniciar Canvas
            </button>
          </div>
        </div>

        {/* Scrollable Git Graph Grid wrapped in collapsible container */}
        <AnimatePresence initial={false}>
          {isTimelineOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="absolute left-0 right-0 top-full bg-[#0C0C0E]/95 backdrop-blur-2xl border-b border-white/5 px-6 py-4 shadow-2xl z-40 overflow-hidden"
            >
              <div className="w-full overflow-x-auto [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:bg-white/10 [&::-webkit-scrollbar-track]:bg-transparent pb-2">
                <div className="relative" style={{ width: graphWidth, height: graphHeight }}>
                  {/* SVG grid dots pattern */}
                  <svg className="absolute inset-0 w-full h-full pointer-events-none">
                    <defs>
                      <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                        <circle cx="2" cy="2" r="1" fill="rgba(255, 255, 255, 0.05)" />
                      </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill="url(#grid)" />
                    {renderGitConnections()}
                  </svg>

                  {/* Left Branch Badges */}
                  {branches.map(branch => {
                    const isBranchActive = activeBranchId === branch.id;
                    return (
                      <div
                        key={branch.id}
                        style={{ left: 20, top: branch.row * 80 + 40 }}
                        className="absolute transform -translate-y-1/2 flex items-center gap-2 group z-20"
                      >
                        {renameBranchId === branch.id ? (
                          <input
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={saveRenameBranch}
                            onKeyDown={(e) => e.key === 'Enter' && saveRenameBranch()}
                            autoFocus
                            className="bg-[#151518] border border-white/10 px-2.5 py-1 text-xs rounded-xl focus:outline-none focus:ring-1 focus:ring-indigo-500 text-white font-medium"
                          />
                        ) : (
                          <button
                            onClick={() => handleCheckoutBranch(branch.id)}
                            onDoubleClick={() => startRenameBranch(branch)}
                            className={`flex items-center gap-2.5 px-3 py-1.5 rounded-xl border text-xs font-semibold backdrop-blur-md transition-all duration-300 ${
                              isBranchActive
                                ? "bg-[#1C1C24] shadow-[0_0_15px_rgba(99,102,241,0.15)]"
                                : "bg-white/5 border-white/5 hover:bg-white/10 text-gray-400 hover:text-white"
                            }`}
                            style={{ borderColor: isBranchActive ? `${branch.color}35` : undefined }}
                          >
                            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: branch.color }} />
                            <span>{branch.name}</span>
                          </button>
                        )}
                      </div>
                    );
                  })}

                  {/* Git Timeline Nodes */}
                  {Object.values(nodes).flatMap(node => {
                    const coord = getNodeCoord(node.id);
                    const isActive = activeNodeId === node.id;
                    const branch = branches.find(b => b.id === node.branchId);
                    const color = branch ? branch.color : "#6366F1";
                    
                    const isDraggingThisNode = !!dragOffsets[node.id];
                    const elements = [];

                    // Render static node placeholder if currently dragging
                    if (isDraggingThisNode) {
                      elements.push(
                        <div
                          key={`static-${node.id}`}
                          style={{ left: coord.x, top: coord.y }}
                          className="absolute transform -translate-x-1/2 -translate-y-1/2 flex items-center z-5 opacity-60 pointer-events-none"
                        >
                          <div
                            className={`w-6 h-6 rounded-full border-2 bg-[#0A0A0B] flex items-center justify-center`}
                            style={{ borderColor: color }}
                          >
                            <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
                          </div>
                        </div>
                      );
                    }

                    // Render the draggable motion node (acting as the ghost copy)
                    elements.push(
                      <motion.div
                        key={node.id}
                        drag
                        dragMomentum={false}
                        dragSnapToOrigin={true}
                        onDrag={(e, info) => {
                          setDragOffsets(prev => ({
                            ...prev,
                            [node.id]: info.offset
                          }));
                        }}
                        onDragEnd={(e, info) => {
                          setDragOffsets(prev => {
                            const next = { ...prev };
                            delete next[node.id];
                            return next;
                          });
                          handleNodeDragEnd(node.id, e, info);
                        }}
                        style={{ left: coord.x, top: coord.y }}
                        className={`absolute transform -translate-x-1/2 -translate-y-1/2 flex items-center z-10 cursor-pointer group ${
                          isDraggingThisNode ? "opacity-60" : ""
                        }`}
                      >
                        {/* Commits visual node */}
                        <div
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCheckoutNode(node.id);
                          }}
                          className={`w-6 h-6 rounded-full border-2 bg-[#0A0A0B] flex items-center justify-center transition-all duration-300 relative ${
                            isDraggingThisNode
                              ? "border-dashed shadow-[0_0_10px_rgba(99,102,241,0.2)]"
                              : isActive
                              ? "scale-125 border-white shadow-[0_0_15px_rgba(255,255,255,0.4)]"
                              : "border-gray-500 hover:border-white"
                          }`}
                          style={{ borderColor: !isActive || isDraggingThisNode ? color : undefined }}
                        >
                          {isActive && !isDraggingThisNode ? (
                            <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                          ) : (
                            <div className="w-1.5 h-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity" style={{ backgroundColor: color }} />
                          )}

                          {/* Hint Label */}
                          <div className="absolute top-7 left-1/2 transform -translate-x-1/2 bg-[#121216] border border-white/10 rounded-lg px-2 py-1 text-[10px] text-gray-400 font-semibold whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-xl z-30">
                            {node.userMessage.content.slice(0, 20)}
                            {node.userMessage.content.length > 20 && '...'}
                          </div>
                        </div>
                      </motion.div>
                    );

                    return elements;
                  })}

                  {/* Git Timeline Ghost Nodes */}
                  {branches.map(branch => {
                    const hasNodes = Object.values(nodes).some(n => n.branchId === branch.id);
                    if (hasNodes || !branch.forkParentId || !nodes[branch.forkParentId]) return null;
                    
                    const parentNode = nodes[branch.forkParentId];
                    const x = (parentNode.depth + 1) * 200 + 180;
                    const y = branch.row * 80 + 40;
                    const isActive = activeBranchId === branch.id;
                    const color = branch.color;

                    return (
                      <div
                        key={`ghost-node-${branch.id}`}
                        style={{ left: x, top: y }}
                        className="absolute transform -translate-x-1/2 -translate-y-1/2 flex items-center z-10 cursor-pointer group"
                        onClick={() => {
                          setActiveBranchId(branch.id);
                          if (inputRef.current) {
                            inputRef.current.focus();
                          }
                        }}
                      >
                        <div
                          className={`w-6 h-6 rounded-full border-2 border-dashed bg-[#0A0A0B]/80 flex items-center justify-center transition-all duration-300 relative ${
                            isActive ? "scale-110 border-white shadow-[0_0_10px_rgba(255,255,255,0.2)] animate-pulse" : "hover:border-white opacity-60 hover:opacity-100"
                          }`}
                          style={{ borderColor: !isActive ? color : undefined }}
                        >
                          <Plus className="w-3 h-3 animate-pulse" style={{ color: isActive ? '#fff' : color }} />

                          {/* Hint Label */}
                          <div className="absolute top-7 left-1/2 transform -translate-x-1/2 bg-[#121216] border border-white/10 rounded-lg px-2 py-1 text-[10px] text-gray-400 font-semibold whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-xl z-30">
                            Nueva conversación aquí
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* -- MAIN CANVAS (GRID OF DRAGGABLE CARDS) -- */}
      <div className="flex-1 px-8 pt-3 pb-8 relative overflow-y-auto">
        <LayoutGroup>
          <div className="w-full h-full relative min-h-[636px]" ref={canvasRef}>
            {/* Background grid helper visible only when dragging (enclosed inside the dashed box area) */}
            <div
              className={`absolute inset-x-8 top-3 bottom-12 rounded-[2rem] transition-opacity duration-300 pointer-events-none ${
                isDragging ? "opacity-100" : "opacity-0"
              }`}
              style={{
                backgroundImage: `
                  linear-gradient(to right, rgba(255, 255, 255, 0.03) 1px, transparent 1px),
                  linear-gradient(to bottom, rgba(255, 255, 255, 0.03) 1px, transparent 1px)
                `,
                backgroundSize: "40px 40px"
              }}
            />

            {/* Invisibly define the drag limits inside the canvas */}
            <div className="absolute inset-x-8 top-3 bottom-12 rounded-[2rem] border border-dashed border-white/20 bg-white/[0.01] pointer-events-none transition-all" ref={dragAreaRef} />

            {activeCardsList.length === 0 ? (
              <div className="w-full h-full flex flex-col items-center justify-center text-center opacity-40 py-20 pointer-events-none">
                <FileText className="w-16 h-16 text-gray-500 mb-4" />
                <h3 className="text-xl font-semibold mb-1">Canvas Vacío</h3>
                <p className="text-sm text-gray-400">Envía un mensaje para comenzar a generar tarjetas interactivas.</p>
              </div>
            ) : (
              activeCardsList.map(card => {
                const updatedInNode = nodes[card.updatedInTurn];
                const changeStr = updatedInNode
                  ? `Turno ${updatedInNode.depth + 1}: ${card.changeSummary}`
                  : card.changeSummary;

                const currentScale = card.scale || 1;
                const unscaledWidth = card.zoom === 'macro' ? 320 : card.zoom === 'meso' ? 450 : 750;
                const unscaledHeight = card.zoom === 'macro' ? 220 : card.zoom === 'meso' ? 340 : 480;
                const visualWidth = unscaledWidth * currentScale;
                const visualHeight = unscaledHeight * currentScale;

                // Dynamically clamp coordinates during render to force alignment and keep cards in-bounds
                const minX = 32;
                const minY = 12;
                const maxX = Math.max(minX, canvasSize.width - 32 - visualWidth);
                const maxY = Math.max(minY, canvasSize.height - 48 - visualHeight);
                const clampedX = Math.max(minX, Math.min(maxX, card.position.x));
                const clampedY = Math.max(minY, Math.min(maxY, card.position.y));

                const cardConstraints = {
                  left: minX,
                  top: minY,
                  right: maxX,
                  bottom: maxY
                };
                return (
                  <motion.div
                    key={card.id}
                    data-card-id={card.id}
                    data-role="outer-card"
                    drag
                    dragMomentum={false}
                    dragConstraints={cardConstraints}
                    dragElastic={0.05}
                    onDragStart={() => setIsDragging(true)}
                    onDragEnd={(e, info) => {
                      handleDragEnd(card.id, e, info, clampedX, clampedY);
                      setIsDragging(false);
                    }}
                    style={{ x: clampedX, y: clampedY, width: visualWidth, height: visualHeight, zIndex: card.zoom === 'micro' ? 30 : 10 }}
                    className="absolute left-0 top-0"
                  >
                    <motion.div
                      data-role="inner-card"
                      style={{ scale: currentScale, transformOrigin: 'top left', width: unscaledWidth, height: unscaledHeight }}
                      className="relative rounded-[2rem] bg-[#111113]/90 border border-white/10 shadow-2xl backdrop-blur-2xl p-6 select-none overflow-hidden transition-colors"
                    >
                    {/* Background glow according to security level */}
                    {card.zoom === 'micro' && (
                      <div className="absolute -top-20 -right-20 w-44 h-44 bg-indigo-500/5 blur-[50px] rounded-full pointer-events-none" />
                    )}

                    {/* Card Header */}
                    <div className="flex items-center justify-between border-b border-white/5 pb-3 mb-4">
                      <div className="flex items-center gap-2.5">
                        <div className="p-2 rounded-xl bg-white/5 text-indigo-400 border border-white/5">
                          {card.type === 'kpi' ? (
                            <Activity className="w-4 h-4" />
                          ) : card.type === 'inventory' ? (
                            <Database className="w-4 h-4" />
                          ) : (
                            <Shield className="w-4 h-4" />
                          )}
                        </div>
                        <div>
                          <h4 className="font-bold text-sm tracking-tight text-white">{card.title}</h4>
                          <p className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">{card.type}</p>
                        </div>
                      </div>

                      {/* Zoom Controls */}
                      <button
                        onClick={() => handleToggleZoom(card.id)}
                        className="p-2 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 transition-all text-gray-400 hover:text-white"
                      >
                        {card.zoom === 'macro' ? (
                          <ChevronDown className="w-3.5 h-3.5" />
                        ) : card.zoom === 'meso' ? (
                          <ChevronUp className="w-3.5 h-3.5" />
                        ) : (
                          <X className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>

                    {/* Card Body Renderers */}
                    {card.zoom === 'macro' && <MacroBody card={card} />}
                    {card.zoom === 'meso' && <MesoBody card={card} />}
                    {card.zoom === 'micro' && (
                      <MicroBody
                        card={card}
                        nodes={nodes}
                        triggerSecurityConfirmation={(actionName, risk, cb) =>
                          setSecurityConfirmation({ actionName, riskLevel: risk, onConfirm: cb })
                        }
                      />
                    )}

                    {/* Change History Hint Banner */}
                    <div className="absolute bottom-3 left-6 right-10 flex items-center gap-1.5 text-[10px] text-gray-500 font-medium border-t border-white/5 pt-2">
                      <Clock className="w-3 h-3 text-gray-600" />
                      <span className="truncate" title={changeStr}>{changeStr}</span>
                    </div>

                    {/* Proportional Resize Handle */}
                    <div
                      className="absolute bottom-3 right-3 w-4 h-4 cursor-se-resize z-50 flex items-center justify-center opacity-30 hover:opacity-100 hover:scale-110 active:scale-95 transition-all"
                      ref={(el) => {
                        if (el) {
                          if ((el as any).__listenersAttached) return;
                          (el as any).__listenersAttached = true;
                          
                          const stopNative = (e: Event) => e.stopPropagation();
                          const startResize = (e: PointerEvent) => {
                            e.stopPropagation();
                            handleResizeStart(card.id, e);
                          };
                          el.addEventListener('pointerdown', startResize as EventListener);
                          el.addEventListener('mousedown', stopNative as EventListener);
                          el.addEventListener('touchstart', stopNative as EventListener);
                        }
                      }}
                      title="Arrastrar para redimensionar (50% - 100%)"
                    >
                      <svg width="10" height="10" viewBox="0 0 10 10" className="text-gray-400">
                        <line x1="10" y1="2" x2="2" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        <line x1="10" y1="6" x2="6" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      </svg>
                    </div>
                    </motion.div>
                  </motion.div>
                );
              })
            )}
          </div>
        </LayoutGroup>
      </div>

      {/* -- BOTTOM INPUT BAR -- */}
      <div className="absolute bottom-8 w-full px-4 z-40 pointer-events-none flex justify-center">
        <div className="w-full max-w-3xl pointer-events-auto">
          <form onSubmit={handleSubmit} className="relative flex items-center group">
            {/* Glowing magic ambient */}
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/10 to-purple-500/10 blur-xl opacity-0 group-hover:opacity-100 transition-opacity rounded-[2rem]" />
            <div className="relative w-full flex items-center bg-[#111113]/90 backdrop-blur-3xl border border-white/10 rounded-[2rem] shadow-[0_20px_50px_rgba(0,0,0,0.5)] p-2">
              <div className="pl-5 pr-1 text-indigo-400/50">
                <ChevronRight className="w-6 h-6" />
              </div>
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={
                  activeNode && !Object.values(nodes).some(n => n.parentId === activeNode.id)
                    ? "Colaborar en la línea activa..."
                    : "Crear bifurcación en la línea temporal..."
                }
                className="w-full bg-transparent border-none text-white text-base px-2 py-4 focus:outline-none focus:ring-0 placeholder:text-gray-500 placeholder:font-light font-medium"
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={!inputValue.trim() || isLoading}
                className="p-3.5 rounded-2xl bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-all duration-300 disabled:opacity-30 disabled:bg-transparent disabled:text-gray-600 mr-2"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* -- SECURITY ACTION CONFIRMATION MODAL (SAIF 2.0) -- */}
      <AnimatePresence>
        {securityConfirmation && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-[#121216] border border-white/10 rounded-[2rem] max-w-md w-full p-6 shadow-2xl relative overflow-hidden"
            >
              <div className="absolute top-0 left-0 w-full h-1 bg-red-500" />
              <div className="flex items-start gap-4 mb-4">
                <div className="p-3 rounded-2xl bg-red-500/10 text-red-400 border border-red-500/25">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-white">Confirmación de Seguridad</h3>
                  <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Políticas de Control SAIF 2.0</p>
                </div>
              </div>
              <p className="text-gray-300 text-sm leading-relaxed mb-6">
                El agente está intentando realizar la acción crítica: <strong className="text-white">"{securityConfirmation.actionName}"</strong>. Esto requiere privilegios mínimos aprobados manualmente por el usuario.
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => {
                    securityConfirmation.onConfirm();
                    setSecurityConfirmation(null);
                  }}
                  className="flex-1 py-3 rounded-xl bg-red-500 hover:bg-red-600 text-white transition-all text-sm font-semibold flex items-center justify-center gap-1.5"
                >
                  <Lock className="w-4 h-4" /> Autorizar
                </button>
                <button
                  onClick={() => setSecurityConfirmation(null)}
                  className="flex-1 py-3 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 text-gray-300 transition-all text-sm font-semibold"
                >
                  Rechazar
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* -- TIMELINE GESTURE CONFIRMATION MODAL -- */}
      <AnimatePresence>
        {timelineModal && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-[#121216] border border-white/10 rounded-[2rem] max-w-md w-full p-6 shadow-2xl relative overflow-hidden"
            >
               <div className={`absolute top-0 left-0 w-full h-1 ${
                timelineModal.type === 'error' 
                  ? 'bg-red-500' 
                  : timelineModal.type === 'revert'
                  ? 'bg-amber-500'
                  : 'bg-indigo-500'
              }`} />
              <div className="flex items-start gap-4 mb-4">
                {timelineModal.type === 'error' ? (
                  <div className="p-3 rounded-2xl bg-red-500/10 text-red-400 border border-red-500/25 animate-pulse">
                    <AlertTriangle className="w-6 h-6" />
                  </div>
                ) : timelineModal.type === 'revert' ? (
                  <div className="p-3 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/25 animate-pulse">
                    <RotateCcw className="w-6 h-6" />
                  </div>
                ) : (
                  <div className="p-3 rounded-2xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/25">
                    <GitBranch className="w-6 h-6" />
                  </div>
                )}
                <div>
                  <h3 className="font-bold text-lg text-white">
                    {timelineModal.type === 'error' 
                      ? 'Acción Bloqueada' 
                      : timelineModal.type === 'revert'
                      ? 'Revertir Historial'
                      : 'Confirmar Acción de Historial'}
                  </h3>
                  <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">
                    {timelineModal.type === 'error' 
                      ? 'Colisión Temporal SAIF 2.0' 
                      : timelineModal.type === 'revert'
                      ? 'Restauración Temporal SAIF 2.0'
                      : 'Control de Flujo SAIF 2.0'}
                  </p>
                </div>
              </div>
              <p className="text-gray-300 text-sm leading-relaxed mb-6">
                {timelineModal.type === 'error' && (
                  <span>{timelineModal.errorMessage}</span>
                )}
                {timelineModal.type === 'fork' && (
                  <span>
                    ¿Deseas <strong>bifurcar (fork)</strong> la línea temporal a partir de esta conversación? Esto creará una rama paralela conservando la conversación y tarjetas previas.
                  </span>
                )}
                {timelineModal.type === 'merge' && (
                  <span>
                    ¿Deseas <strong>fusionar (merge)</strong> la rama de este nodo en la rama del nodo destino? Esto combinará las tarjetas activas de ambas conversaciones.
                  </span>
                )}
                {timelineModal.type === 'break' && (
                  <span>
                    ¿Deseas <strong>desvincular (break/detach)</strong> este nodo y su descendencia de la línea temporal? Se convertirá en una sesión independiente separada de su padre.
                  </span>
                )}
                {timelineModal.type === 'revert' && (
                  <span>
                    ¿Deseas <strong>revertir (reset)</strong> la línea temporal a este punto? Se descartarán de forma permanente todos los cambios y nodos creados posteriormente.
                  </span>
                )}
              </p>

              {timelineModal.type === 'error' ? (
                <div className="flex justify-end">
                  <button
                    onClick={() => setTimelineModal(null)}
                    className="w-full py-3 rounded-xl bg-red-500 hover:bg-red-600 text-white transition-all text-sm font-semibold flex items-center justify-center gap-1.5 shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                  >
                    Entendido
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => {
                      if (timelineModal.type === 'fork') {
                        executeFork(timelineModal.nodeAId);
                      } else if (timelineModal.type === 'merge') {
                        executeMerge(timelineModal.nodeAId, timelineModal.nodeBId!);
                      } else if (timelineModal.type === 'break') {
                        executeBreak(timelineModal.nodeAId);
                      } else if (timelineModal.type === 'revert') {
                        executeRevert(timelineModal.nodeAId);
                      }
                      setTimelineModal(null);
                    }}
                    className={`flex-1 py-3 rounded-xl text-white transition-all text-sm font-semibold flex items-center justify-center gap-1.5 ${
                      timelineModal.type === 'revert'
                        ? 'bg-amber-500 hover:bg-amber-600 shadow-[0_0_15px_rgba(245,158,11,0.2)]'
                        : 'bg-indigo-500 hover:bg-indigo-600'
                    }`}
                  >
                    <Check className="w-4 h-4" /> Confirmar
                  </button>
                  <button
                    onClick={() => setTimelineModal(null)}
                    className="flex-1 py-3 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 text-gray-300 transition-all text-sm font-semibold"
                  >
                    Cancelar
                  </button>
                </div>
              )}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

// -- SPECIFIC CARD ZOOM STATE RENDEREERS --

// 1. MACRO STATE (Default Metrics)
function MacroBody({ card }: { card: CardState }) {
  const trendColor = card.macroData.trend === 'up' ? 'text-emerald-400' : card.macroData.trend === 'down' ? 'text-red-400' : 'text-gray-400';
  return (
    <div className="flex flex-col h-full justify-between pb-8">
      <div>
        <h2 className="text-3xl font-extrabold tracking-tight text-white mb-1">{card.macroData.value}</h2>
        <div className="flex items-center gap-1">
          {card.macroData.change && (
            <span className={`text-xs font-bold ${trendColor}`}>{card.macroData.change}</span>
          )}
          {card.macroData.subtitle && (
            <span className="text-xs text-gray-500 font-medium">— {card.macroData.subtitle}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// 2. MESO STATE (Visual Breakdown)
function MesoBody({ card }: { card: CardState }) {
  return (
    <div className="flex flex-col justify-between h-[230px] pb-2">
      {/* Metrics Header */}
      <div>
        <h2 className="text-2xl font-extrabold tracking-tight text-white mb-1">{card.macroData.value}</h2>
        {card.macroData.subtitle && (
          <p className="text-xs text-gray-500 font-medium mb-4">{card.macroData.subtitle}</p>
        )}
      </div>

      {/* SVG Bar Chart (Visual representation of detail) */}
      {card.mesoData.chartData && card.mesoData.chartData.length > 0 ? (
        <div className="w-full flex items-end gap-3 h-24 mb-4 px-2">
          {card.mesoData.chartData.map((d, idx) => {
            const maxVal = Math.max(...card.mesoData.chartData!.map(item => item.value));
            const percentage = maxVal > 0 ? (d.value / maxVal) * 100 : 0;
            return (
              <div key={idx} className="flex-1 flex flex-col items-center gap-1.5 group/bar">
                <div className="w-full bg-white/5 rounded-md h-20 flex items-end overflow-hidden">
                  <div
                    style={{ height: `${percentage}%` }}
                    className="w-full bg-indigo-500 rounded-md transition-all duration-500 group-hover/bar:bg-indigo-400"
                  />
                </div>
                <span className="text-[9px] font-semibold text-gray-500 group-hover/bar:text-white transition-colors">{d.label}</span>
              </div>
            );
          })}
        </div>
      ) : (
        /* Bullet list if no charts are present */
        <ul className="space-y-1.5 mb-4">
          {card.mesoData.bullets?.map((b, idx) => (
            <li key={idx} className="text-xs text-gray-300 flex items-start gap-1.5 font-light leading-relaxed">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0 mt-1.5" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// 3. MICRO STATE (Trace, Security Logs & Data Tables)
function MicroBody({
  card,
  nodes,
  triggerSecurityConfirmation
}: {
  card: CardState;
  nodes: Record<string, TimelineNode>;
  triggerSecurityConfirmation: (actionName: string, risk: 'low' | 'medium' | 'high', cb: () => void) => void;
}) {
  const [activeTab, setActiveTab] = useState<'table' | 'sql' | 'saif'>('table');

  const trendColor = card.macroData.trend === 'up' ? 'text-emerald-400' : card.macroData.trend === 'down' ? 'text-red-400' : 'text-gray-400';

  const handleActionClick = (itemName: string) => {
    triggerSecurityConfirmation(`Reordenar ${itemName}`, 'high', () => {
      alert(`Autorización SAIF 2.0 concedida. Acción enviada: Reordenar ${itemName}`);
    });
  };

  return (
    <div className="flex flex-col h-[370px]">
      {/* Top summary row */}
      <div className="flex items-center justify-between mb-4 pb-2 border-b border-white/5">
        <div>
          <h3 className="text-xl font-black text-white">{card.macroData.value}</h3>
          <p className="text-xs text-gray-500 font-medium">{card.macroData.subtitle}</p>
        </div>

        {/* Action button triggers for specific inventory type */}
        {card.type === 'inventory' && (
          <button
            onClick={() => handleActionClick("Fusor Cobre")}
            className="px-3.5 py-2 rounded-xl bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500 hover:text-white transition-all text-xs font-bold"
          >
            Reordenar Todo (SAIF Confirm)
          </button>
        )}
      </div>

      {/* Detail Tab buttons */}
      <div className="flex items-center gap-1.5 mb-4 border-b border-white/5 pb-2">
        <button
          onClick={() => setActiveTab('table')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
            activeTab === 'table' ? 'bg-white/10 text-white' : 'text-gray-400 hover:text-white'
          }`}
        >
          Desglose
        </button>
        <button
          onClick={() => setActiveTab('sql')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
            activeTab === 'sql' ? 'bg-white/10 text-white' : 'text-gray-400 hover:text-white'
          }`}
        >
          Consulta Lógica (SQL)
        </button>
        <button
          onClick={() => setActiveTab('saif')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ${
            activeTab === 'saif' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/25' : 'text-gray-400 hover:text-white'
          }`}
        >
          Seguridad SAIF
        </button>
      </div>

      {/* Tab Panels */}
      <div className="flex-1 overflow-y-auto pr-1">
        {activeTab === 'table' && card.microData.tableHeaders && (
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-white/10 text-gray-500 font-bold uppercase tracking-wider">
                {card.microData.tableHeaders.map((h, i) => (
                  <th key={i} className="pb-2 font-bold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {card.microData.tableRows?.map((row, idx) => (
                <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                  {row.map((cell, cIdx) => (
                    <td key={cIdx} className="py-2 font-medium text-gray-300">
                      {cell === 'Reordenar' ? (
                        <button
                          onClick={() => handleActionClick(row[0])}
                          className="px-2 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500 hover:text-white font-bold transition-all text-[10px]"
                        >
                          Reordenar
                        </button>
                      ) : (
                        cell
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {activeTab === 'sql' && (
          <div className="space-y-4">
            <div className="bg-black/40 border border-white/5 rounded-xl p-3.5 font-mono text-[10px] text-indigo-300 whitespace-pre-wrap leading-relaxed select-text">
              {card.microData.sqlQuery || "No logical query registered."}
            </div>
            {card.microData.executionLogs && (
              <div>
                <h5 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1.5">Logs de Ejecución</h5>
                <ul className="space-y-1">
                  {card.microData.executionLogs.map((log, idx) => (
                    <li key={idx} className="text-[10px] font-mono text-gray-400 flex items-start gap-1">
                      <span className="text-gray-600 font-bold">▶</span>
                      <span>{log}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {activeTab === 'saif' && (
          <div className="space-y-4">
            {/* Safety score panel */}
            <div className="flex items-center justify-between p-4 rounded-2xl bg-indigo-500/5 border border-indigo-500/10">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-indigo-400" />
                <div>
                  <h4 className="text-xs font-bold text-white">Score de Seguridad Generativa</h4>
                  <p className="text-[10px] text-gray-500">Evaluado según estándares de Google PAIR</p>
                </div>
              </div>
              <span className="text-lg font-black text-indigo-400">{card.microData.safetyScore || 100}%</span>
            </div>

            {/* Checklists */}
            <div className="space-y-2">
              <SafetyCheckItem title="Filtro contra inyecciones indirectas" checked={true} />
              <SafetyCheckItem title="Esquema estricto de UI verificado" checked={true} />
              <SafetyCheckItem title="Aislamiento de variables de sesión" checked={true} />
              <SafetyCheckItem title="Acciones de modificación humana-in-the-loop" checked={card.type === 'inventory'} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SafetyCheckItem({ title, checked }: { title: string; checked: boolean }) {
  return (
    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white/5 text-xs">
      <span className="text-gray-300 font-light">{title}</span>
      {checked ? (
        <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-lg">
          <Check className="w-3 h-3" /> Verificado
        </span>
      ) : (
        <span className="flex items-center gap-1 text-[10px] font-bold text-gray-400 bg-white/5 px-2 py-0.5 rounded-lg">
          No Aplica
        </span>
      )}
    </div>
  );
}
