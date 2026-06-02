// spec: specs/canvas/timeline-reducer.spec.md
/**
 * Pure timeline tree state-machine for the Sandbox (canvas 4D + git timeline).
 *
 * THE CARDINAL INVARIANT: `nodes` (the tree) is the single source of truth.
 * CopilotKit's LINEAR `messages` array is DERIVED from the active path
 * (getActivePath -> compileMessagesForPath) and must NEVER drive tree structure.
 *
 * These reducers are pure (no React, no CopilotKit, no Date.now/random) so the
 * fork/merge/break/revert logic is unit-testable in isolation. They lock the two
 * production bugs this refactor fixes:
 *   - Bug 1 (fork->write): the new node must stay on the ACTIVE branch, never get
 *     re-derived onto the parent's branch.
 *   - Bug 2 (big revert): branch pruning must read the POST-deletion tree, never a
 *     stale pre-deletion snapshot.
 *
 * Side effects (setMessages / sendMessage / stopGeneration) stay in page.tsx; this
 * module only computes the next {nodes, branches, activeNodeId, activeBranchId}.
 * Page.tsx imports these helpers + reducers and re-exports the types, so the move
 * out of page.tsx is behavior-preserving.
 */

// ---------------------------------------------------------------------------
// Data models (moved verbatim from page.tsx; page.tsx re-exports them)
// ---------------------------------------------------------------------------

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

/** The full tree-of-record. `messages` is derived from this, never the reverse. */
export interface TimelineState {
  nodes: Record<string, TimelineNode>;
  branches: TimelineBranch[];
  activeNodeId: string | null;
  activeBranchId: string;
}

/** appendTurn also reports the id of the node it created (for the pending-turn ref). */
export interface AppendResult extends TimelineState {
  newNodeId: string;
}

/**
 * Injectable id generator so reducers stay deterministic under test. The default
 * uses crypto.randomUUID() — stable + collision-free (replaces the old
 * `'turn-' + Date.now()` which collided when two actions fired in the same ms).
 */
export type IdGen = (prefix: string) => string;
export const defaultIdGen: IdGen = (prefix) => `${prefix}-${crypto.randomUUID()}`;

/** Branch row colors (cycled by row index). Moved from page.tsx `colors`. */
export const BRANCH_COLORS = ['#6366F1', '#10B981', '#F43F5E', '#F59E0B', '#A855F7', '#06B6D4', '#EC4899'];

// ---------------------------------------------------------------------------
// Pure helpers (moved verbatim from page.tsx)
// ---------------------------------------------------------------------------

/** Deterministic short hash from any string (stable motion animation keys). */
export function contentHash(str: string): string {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h).toString(36);
}

export function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

/** Root -> active node, walking parentId. The order is ancestor-first (reversed). */
export function getActivePath(
  activeNodeId: string | null,
  nodes: Record<string, TimelineNode>,
): TimelineNode[] {
  if (!activeNodeId) return [];
  const path: TimelineNode[] = [];
  let current: TimelineNode | undefined = nodes[activeNodeId];
  while (current) {
    path.push(current);
    current = current.parentId ? nodes[current.parentId] : undefined;
  }
  return path.reverse();
}

/** Flatten a path into the linear message list CopilotKit consumes. */
export function compileMessagesForPath(path: TimelineNode[]): any[] {
  const messages: any[] = [];
  for (const node of path) {
    messages.push(node.userMessage);
    messages.push(...node.assistantMessages);
  }
  return messages;
}

/** Strip messages down to a CopilotKit-serializable shape. */
export function makeSerializable(messages: any[]): any[] {
  return messages.map((m: any) => ({
    id: m.id,
    role: m.role,
    content: m.content ?? '',
    ...(m.type && { type: m.type }),
    ...(m.name && { name: m.name }),
    ...(m.toolCalls && { toolCalls: m.toolCalls }),
    ...(m.toolCallId && { toolCallId: m.toolCallId }),
  }));
}

/** Recompute every node's depth from the roots, following parentId only. */
export function recalculateDepths(
  nodesRecord: Record<string, TimelineNode>,
): Record<string, TimelineNode> {
  const nextNodes = deepClone(nodesRecord);
  const roots = Object.values(nextNodes).filter((n) => !n.parentId || !nextNodes[n.parentId]);
  const visited = new Set<string>();

  const assignDepth = (nodeId: string, currentDepth: number) => {
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    if (nextNodes[nodeId]) {
      nextNodes[nodeId].depth = currentDepth;
      const children = Object.values(nextNodes).filter((n) => n.parentId === nodeId);
      children.forEach((child) => {
        assignDepth(child.id, currentDepth + 1);
      });
    }
  };
  roots.forEach((root) => {
    assignDepth(root.id, 0);
  });

  return nextNodes;
}

/** All descendant ids of `ancestorId`, following parentId AND mergeParentId. */
export function getDescendants(
  ancestorId: string,
  currentNodes: Record<string, TimelineNode>,
): string[] {
  const descendants: string[] = [];
  const queue = [ancestorId];
  const visited = new Set<string>();

  while (queue.length > 0) {
    const currId = queue.shift()!;
    if (visited.has(currId)) continue;
    visited.add(currId);

    Object.values(currentNodes).forEach((n) => {
      if (n.parentId === currId || n.mergeParentId === currId) {
        if (n.id !== ancestorId) {
          descendants.push(n.id);
          queue.push(n.id);
        }
      }
    });
  }
  return Array.from(new Set(descendants));
}

// ---------------------------------------------------------------------------
// Generative-UI parser (moved verbatim from page.tsx)
// ---------------------------------------------------------------------------

/**
 * Parse <create_card>/<update_card>/<delete_card> tags from assistant text into
 * the card map. Tolerant of incomplete JSON (mid-stream chunks): bad JSON is
 * skipped via try/catch, so re-running this from the parent's cards on every
 * streamed chunk converges as the closing tag arrives.
 */
export function parseCardsFromMessage(
  content: string,
  prevCards: Record<string, CardState>,
  turnId: string,
): Record<string, CardState> {
  const nextCards = { ...prevCards };

  // 1. create_card
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
          changeSummary: parsed.changeSummary || 'Componente creado',
        };
      }
    } catch (e) {
      console.error('Failed to parse create_card content JSON', e);
    }
  }

  // 2. update_card
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
          changeSummary: parsed.changeSummary || 'Datos actualizados',
        };
      } catch (e) {
        console.error('Failed to parse update_card content JSON', e);
      }
    }
  }

  // 3. delete_card
  const deleteRegex = /<delete_card\s+id="([^"]+)"\s*\/>/g;
  while ((match = deleteRegex.exec(content)) !== null) {
    const id = match[1];
    delete nextCards[id];
  }

  return nextCards;
}

// ---------------------------------------------------------------------------
// Reducers — the structural state machine. Each is (state, args, idgen?) => state.
// ---------------------------------------------------------------------------

/**
 * Add a user turn. Decides append-vs-fork EXPLICITLY from the tree + active
 * branch (never from `messages`). The new node is created with an EMPTY
 * assistantMessages; the assistant reply is captured later into this same node id.
 *
 * Cases:
 *  - leaf append: write on the tip of the active branch -> child on the same branch.
 *  - fork: write on a PAST node (has children) while on that node's own branch ->
 *    a NEW branch is created and the node lands on it. (Bug-1 fix: branchId is the
 *    active/new branch, NOT the parent's.)
 *  - ghost first write: the active branch is empty but was forked (has forkParentId)
 *    -> the first node parents to the fork point and stays on the ghost branch.
 */
export function appendTurn(
  state: TimelineState,
  { text }: { text: string },
  idgen: IdGen = defaultIdGen,
): AppendResult {
  const { nodes, branches, activeNodeId, activeBranchId } = state;
  const nextNodeId = idgen('turn');

  let branchId = activeBranchId || 'main';
  let parentId: string | null = activeNodeId && nodes[activeNodeId] ? activeNodeId : null;
  let nextBranches = branches;

  const activeBranchObj = branches.find((b) => b.id === activeBranchId);
  const activeBranchIsEmpty = !Object.values(nodes).some((n) => n.branchId === activeBranchId);

  if (activeBranchObj?.forkParentId && activeBranchIsEmpty && nodes[activeBranchObj.forkParentId]) {
    // Ghost branch: first write parents to the fork point, stays on this branch.
    parentId = activeBranchObj.forkParentId;
    branchId = activeBranchId;
  } else {
    const parent = parentId ? nodes[parentId] : null;
    if (parent) {
      const isLeaf = !Object.values(nodes).some((n) => n.parentId === parent.id);
      if (activeBranchId === parent.branchId && !isLeaf) {
        // FORK: writing on a past node on its own branch -> new branch.
        const nextRow = Math.max(...branches.map((b) => b.row), -1) + 1;
        const color = BRANCH_COLORS[nextRow % BRANCH_COLORS.length];
        const newBranchId = idgen('branch');
        const shortName = text.slice(0, 15) + (text.length > 15 ? '...' : '');
        nextBranches = [
          ...branches,
          { id: newBranchId, name: `Rama: ${shortName}`, row: nextRow, color, forkParentId: parent.id },
        ];
        branchId = newBranchId;
      } else {
        // Append on the ACTIVE branch (NOT parent.branchId — that was the bug).
        branchId = activeBranchId;
      }
    } else {
      branchId = activeBranchId || 'main';
      parentId = null;
    }
  }

  const parentNode = parentId ? nodes[parentId] : null;
  const newNode: TimelineNode = {
    id: nextNodeId,
    parentId,
    userMessage: { id: nextNodeId, role: 'user', content: text },
    assistantMessages: [],
    branchId,
    depth: parentNode ? parentNode.depth + 1 : 0,
    activeCards: parentNode ? deepClone(parentNode.activeCards) : {},
  };

  return {
    nodes: { ...nodes, [nextNodeId]: newNode },
    branches: nextBranches,
    activeNodeId: nextNodeId,
    activeBranchId: branchId,
    newNodeId: nextNodeId,
  };
}

/** Gesture fork: create a new (empty) branch off `nodeId`; select the fork point. */
export function forkTurn(
  state: TimelineState,
  { nodeId }: { nodeId: string },
  idgen: IdGen = defaultIdGen,
): TimelineState {
  const { nodes, branches } = state;
  const nodeA = nodes[nodeId];
  if (!nodeA) return state;

  const nextRow = Math.max(...branches.map((b) => b.row), -1) + 1;
  const color = BRANCH_COLORS[nextRow % BRANCH_COLORS.length];
  const newBranchId = idgen('branch');
  const content: string = nodeA.userMessage?.content ?? '';
  const shortName = content.slice(0, 15) + (content.length > 15 ? '...' : '');
  const newBranch: TimelineBranch = {
    id: newBranchId,
    name: `Rama: ${shortName}`,
    row: nextRow,
    color,
    forkParentId: nodeId,
  };

  return {
    nodes,
    branches: [...branches, newBranch],
    activeNodeId: nodeId,
    activeBranchId: newBranchId,
  };
}

/** Gesture merge A->B: a merge node parented to B, mergeParentId A, cards fused. */
export function mergeNodes(
  state: TimelineState,
  { nodeAId, nodeBId }: { nodeAId: string; nodeBId: string },
  idgen: IdGen = defaultIdGen,
): TimelineState {
  const { nodes, branches } = state;
  const nodeA = nodes[nodeAId];
  const nodeB = nodes[nodeBId];
  if (!nodeA || !nodeB) return state;

  const branchA = branches.find((b) => b.id === nodeA.branchId);
  const branchB = branches.find((b) => b.id === nodeB.branchId);
  const nameA = branchA ? branchA.name : 'Desconocida';
  const nameB = branchB ? branchB.name : 'Desconocida';

  const mergeNodeId = idgen('merge');
  const mergedCards = deepClone(nodeB.activeCards);

  // For each of A's cards: add if absent, or upgrade if A's version is deeper.
  Object.values(nodeA.activeCards).forEach((card) => {
    const activeCard = mergedCards[card.id];
    if (!activeCard) {
      mergedCards[card.id] = {
        ...deepClone(card),
        updatedInTurn: mergeNodeId,
        changeSummary: `Fusión desde rama "${nameA}"`,
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
          changeSummary: `Fusión y actualización de datos desde rama "${nameA}"`,
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
      content: `Fusión gestual: Incorporar "${nameA}" en "${nameB}"`,
    },
    assistantMessages: [
      {
        id: 'asst-' + mergeNodeId,
        role: 'assistant',
        content: `Ramas fusionadas gestualmente. Se unió la línea temporal de "${nameA}" con "${nameB}".`,
      },
    ],
    activeCards: mergedCards,
  };

  const nodesNext = recalculateDepths({ ...nodes, [mergeNodeId]: newMergeNode });
  return {
    nodes: nodesNext,
    branches,
    activeNodeId: mergeNodeId,
    activeBranchId: newMergeNode.branchId,
  };
}

/** Gesture break: detach `nodeId` from its parent; subtree re-roots, depths recompute. */
export function breakNode(
  state: TimelineState,
  { nodeId }: { nodeId: string },
): TimelineState {
  const { nodes } = state;
  if (!nodes[nodeId]) return state;
  const detached: Record<string, TimelineNode> = {
    ...nodes,
    [nodeId]: { ...nodes[nodeId], parentId: null },
  };
  return { ...state, nodes: recalculateDepths(detached) };
}

/**
 * Revert to an ancestor: atomically delete its whole descendant subtree and prune
 * orphan branches. Bug-2 fix: branch pruning reads the POST-deletion tree
 * (`nodesNext`), not the stale pre-deletion `nodes`.
 */
export function revertTo(
  state: TimelineState,
  { ancestorId }: { ancestorId: string },
): TimelineState {
  const { nodes, branches } = state;
  const ancestorNode = nodes[ancestorId];
  if (!ancestorNode) return state;

  const descendantSet = new Set(getDescendants(ancestorId, nodes));

  const remaining: Record<string, TimelineNode> = {};
  for (const [id, n] of Object.entries(nodes)) {
    if (!descendantSet.has(id)) remaining[id] = n;
  }
  const nodesNext = recalculateDepths(remaining);

  const branchesNext = branches.filter((b) => {
    if (b.id === 'main') return true;
    const hasNode = Object.values(nodesNext).some((n) => n.branchId === b.id);
    const forkParentAlive = b.forkParentId ? !!nodesNext[b.forkParentId] : false;
    return hasNode || forkParentAlive;
  });

  return {
    nodes: nodesNext,
    branches: branchesNext,
    activeNodeId: ancestorId,
    activeBranchId: ancestorNode.branchId,
  };
}
