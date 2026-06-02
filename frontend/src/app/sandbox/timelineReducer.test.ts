// spec: specs/canvas/timeline-reducer.spec.md
import { describe, expect, it } from "vitest";

import {
  appendTurn,
  breakNode,
  compileMessagesForPath,
  forkTurn,
  getActivePath,
  mergeNodes,
  revertTo,
  type CardState,
  type IdGen,
  type TimelineBranch,
  type TimelineNode,
  type TimelineState,
} from "./timelineReducer";

// Deterministic id generator (counter) so reducer output is reproducible (I5).
function counterIdGen(): IdGen {
  let i = 0;
  return (prefix) => `${prefix}-${++i}`;
}

function node(
  id: string,
  parentId: string | null,
  branchId: string,
  depth: number,
  extra: Partial<TimelineNode> = {},
): TimelineNode {
  return {
    id,
    parentId,
    branchId,
    depth,
    userMessage: { id, role: "user", content: id },
    assistantMessages: [],
    activeCards: {},
    ...extra,
  };
}

function card(id: string, updatedInTurn: string, x = 0): CardState {
  return {
    id,
    title: id,
    type: "kpi",
    macroData: { value: "v" },
    mesoData: {},
    microData: {},
    position: { x, y: 0 },
    zoom: "macro",
    updatedInTurn,
    changeSummary: "",
  };
}

const MAIN: TimelineBranch = { id: "main", name: "Línea Principal", row: 0, color: "#6366F1" };

/** main: A(root) -> B(leaf) */
function linearState(): TimelineState {
  return {
    nodes: {
      A: node("A", null, "main", 0),
      B: node("B", "A", "main", 1),
    },
    branches: [MAIN],
    activeNodeId: "B",
    activeBranchId: "main",
  };
}

describe("appendTurn", () => {
  it("leaf append stays on the active branch", () => {
    const r = appendTurn(linearState(), { text: "hola" }, counterIdGen());
    const created = r.nodes[r.newNodeId];
    expect(created.parentId).toBe("B");
    expect(created.branchId).toBe("main");
    expect(created.depth).toBe(2);
    expect(r.activeNodeId).toBe(r.newNodeId);
    expect(r.activeBranchId).toBe("main");
    expect(r.branches).toHaveLength(1); // no new branch
  });

  it("BUG 1: writing on a past node forks onto a NEW branch, never the parent's", () => {
    const state = { ...linearState(), activeNodeId: "A" }; // A is a non-leaf on main
    const r = appendTurn(state, { text: "explorar otra via" }, counterIdGen());
    const created = r.nodes[r.newNodeId];

    expect(r.branches).toHaveLength(2); // a new branch was created
    const newBranch = r.branches.find((b) => b.id !== "main")!;
    expect(newBranch.forkParentId).toBe("A");

    // The crux: the new node is on the NEW branch, NOT re-derived onto "main".
    expect(created.branchId).toBe(newBranch.id);
    expect(created.branchId).not.toBe("main");
    expect(created.parentId).toBe("A");
    expect(r.activeBranchId).toBe(newBranch.id);
  });

  it("ghost branch: first write parents to the fork point and stays on the ghost branch", () => {
    const ghost: TimelineBranch = { id: "R", name: "Rama", row: 1, color: "#10B981", forkParentId: "A" };
    const state: TimelineState = {
      nodes: { A: node("A", null, "main", 0) },
      branches: [MAIN, ghost],
      activeNodeId: "A",
      activeBranchId: "R",
    };
    const r = appendTurn(state, { text: "primera" }, counterIdGen());
    const created = r.nodes[r.newNodeId];
    expect(created.parentId).toBe("A");
    expect(created.branchId).toBe("R");
    expect(created.depth).toBe(1);
    expect(r.branches).toHaveLength(2); // no extra branch created
  });

  it("inherits the parent's cards by value (deep clone, not shared reference)", () => {
    const state = linearState();
    state.nodes.B.activeCards = { c1: card("c1", "B") };
    const r = appendTurn(state, { text: "x" }, counterIdGen());
    const created = r.nodes[r.newNodeId];
    expect(created.activeCards.c1).toBeDefined();
    created.activeCards.c1.position.x = 999;
    expect(state.nodes.B.activeCards.c1.position.x).toBe(0); // original untouched
  });

  it("first node when the tree is empty becomes a root on the active branch", () => {
    const state: TimelineState = { nodes: {}, branches: [MAIN], activeNodeId: null, activeBranchId: "main" };
    const r = appendTurn(state, { text: "inicio" }, counterIdGen());
    const created = r.nodes[r.newNodeId];
    expect(created.parentId).toBeNull();
    expect(created.depth).toBe(0);
    expect(created.branchId).toBe("main");
  });
});

describe("revertTo", () => {
  /** main: A->B->C ; branch R forked at B with B1->B2 */
  function forkedState(): TimelineState {
    const R: TimelineBranch = { id: "R", name: "Rama", row: 1, color: "#10B981", forkParentId: "B" };
    return {
      nodes: {
        A: node("A", null, "main", 0),
        B: node("B", "A", "main", 1),
        C: node("C", "B", "main", 2),
        B1: node("B1", "B", "R", 2),
        B2: node("B2", "B1", "R", 3),
      },
      branches: [MAIN, R],
      activeNodeId: "C",
      activeBranchId: "main",
    };
  }

  it("BUG 2: deletes the whole subtree and prunes orphan branches via the POST-deletion tree", () => {
    const r = revertTo(forkedState(), { ancestorId: "A" });
    expect(Object.keys(r.nodes).sort()).toEqual(["A"]);
    expect(r.branches.map((b) => b.id)).toEqual(["main"]); // R pruned (no nodes + forkParent B gone)
    expect(r.activeNodeId).toBe("A");
    expect(r.activeBranchId).toBe("main");
  });

  it("reverting to B removes its descendants but keeps R as a ghost (fork point B survives)", () => {
    const r = revertTo(forkedState(), { ancestorId: "B" });
    expect(Object.keys(r.nodes).sort()).toEqual(["A", "B"]); // C, B1, B2 deleted
    // R has no nodes left, but its forkParentId (B) survives -> retained as a ghost branch.
    expect(r.branches.map((b) => b.id)).toEqual(["main", "R"]);
  });

  it("retains a ghost branch whose fork point survives the revert", () => {
    // Ghost R forked at A (no nodes of its own); reverting to A must keep R because A survives.
    const R: TimelineBranch = { id: "R", name: "Rama", row: 1, color: "#10B981", forkParentId: "A" };
    const state: TimelineState = {
      nodes: { A: node("A", null, "main", 0), B: node("B", "A", "main", 1) },
      branches: [MAIN, R],
      activeNodeId: "B",
      activeBranchId: "main",
    };
    const r = revertTo(state, { ancestorId: "A" });
    expect(Object.keys(r.nodes).sort()).toEqual(["A"]);
    expect(r.branches.map((b) => b.id).sort()).toEqual(["R", "main"]); // R kept: forkParent A alive
  });
});

describe("mergeNodes", () => {
  it("creates a merge node parented to B with mergeParentId A and selects it", () => {
    const state: TimelineState = {
      nodes: {
        A: node("A", null, "x", 2, { activeCards: { c1: card("c1", "A", 5) } }),
        B: node("B", null, "main", 1, { activeCards: { c1: card("c1", "B", 9) } }),
      },
      branches: [MAIN, { id: "x", name: "X", row: 1, color: "#10B981" }],
      activeNodeId: "B",
      activeBranchId: "main",
    };
    const r = mergeNodes(state, { nodeAId: "A", nodeBId: "B" }, counterIdGen());
    const merge = r.nodes[r.activeNodeId!];
    expect(merge.parentId).toBe("B");
    expect(merge.mergeParentId).toBe("A");
    expect(merge.branchId).toBe("main");
    // A's card is deeper (depth 2 > 1) -> its data wins, but keeps B's position.
    expect(merge.activeCards.c1.updatedInTurn).toBe(merge.id);
    expect(merge.activeCards.c1.position.x).toBe(9);
  });
});

describe("breakNode", () => {
  it("detaches the node and recomputes contiguous depths from the new roots", () => {
    const state: TimelineState = {
      nodes: {
        A: node("A", null, "main", 0),
        B: node("B", "A", "main", 1),
        C: node("C", "B", "main", 2),
      },
      branches: [MAIN],
      activeNodeId: "C",
      activeBranchId: "main",
    };
    const r = breakNode(state, { nodeId: "B" });
    expect(r.nodes.B.parentId).toBeNull();
    expect(r.nodes.A.depth).toBe(0);
    expect(r.nodes.B.depth).toBe(0); // B is now its own root
    expect(r.nodes.C.depth).toBe(1);
  });
});

describe("forkTurn", () => {
  it("adds an empty branch off the node and selects the fork point", () => {
    const r = forkTurn(linearState(), { nodeId: "A" }, counterIdGen());
    expect(r.branches).toHaveLength(2);
    const nb = r.branches.find((b) => b.id !== "main")!;
    expect(nb.forkParentId).toBe("A");
    expect(r.activeNodeId).toBe("A");
    expect(r.activeBranchId).toBe(nb.id);
    expect(Object.keys(r.nodes).sort()).toEqual(["A", "B"]); // no node added yet
  });
});

describe("invariants", () => {
  it("I4: userMessage.id === node.id for every node a reducer creates", () => {
    const r = appendTurn(linearState(), { text: "x" }, counterIdGen());
    for (const n of Object.values(r.nodes)) {
      expect(n.userMessage.id).toBe(n.id);
    }
  });

  it("getActivePath + compileMessagesForPath round-trips the active chain in order", () => {
    const r = appendTurn(linearState(), { text: "x" }, counterIdGen());
    const path = getActivePath(r.activeNodeId, r.nodes);
    expect(path.map((n) => n.id)).toEqual(["A", "B", r.newNodeId]);
    const msgs = compileMessagesForPath(path);
    expect(msgs[0].id).toBe("A");
    expect(msgs[msgs.length - 1].id).toBe(r.newNodeId);
  });

  it("I5: same inputs + same idgen produce deep-equal output (no Date.now leakage)", () => {
    const a = appendTurn({ ...linearState(), activeNodeId: "A" }, { text: "y" }, counterIdGen());
    const b = appendTurn({ ...linearState(), activeNodeId: "A" }, { text: "y" }, counterIdGen());
    expect(a).toEqual(b);
  });
});
