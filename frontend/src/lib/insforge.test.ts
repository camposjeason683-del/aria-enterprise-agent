// spec: specs/canvas/canvas-persistence.spec.md
import { describe, expect, it } from "vitest";

import { loadWorkspace, saveWorkspace, type WorkspaceState } from "./insforge";

// A minimal fake of the InsForge `database` (chainable + thenable builders).
function fakeDb(selectRow: unknown) {
  const ops: { op: string; table: string; vals: unknown }[] = [];
  const make = (table: string) => {
    const b: Record<string, unknown> = {};
    b.select = () => b;
    b.eq = () => b;
    b.maybeSingle = () => Promise.resolve({ data: selectRow, error: null });
    b.update = (vals: unknown) => {
      ops.push({ op: "update", table, vals });
      return b;
    };
    b.insert = (vals: unknown) => {
      ops.push({ op: "insert", table, vals });
      return b;
    };
    // make `await builder` resolve (PostgREST builders are thenable)
    b.then = (res: (v: unknown) => void) => res({ data: [{}], error: null });
    return b;
  };
  return { db: { from: (t: string) => make(t) }, ops };
}

const sample: WorkspaceState = {
  nodes: { a: 1 },
  branches: [],
  activeNodeId: "n1",
  activeBranchId: "main",
};

describe("canvas persistence (S9)", () => {
  it("loadWorkspace returns the stored state", async () => {
    const { db } = fakeDb({ state: sample });
    expect(await loadWorkspace("u1", db)).toEqual(sample);
  });

  it("loadWorkspace returns null when there is no row", async () => {
    const { db } = fakeDb(null);
    expect(await loadWorkspace("u1", db)).toBeNull();
  });

  it("saveWorkspace inserts when no row exists (new user)", async () => {
    const { db, ops } = fakeDb(null);
    await saveWorkspace("u1", "A", sample, db);
    expect(ops).toHaveLength(1);
    expect(ops[0].op).toBe("insert");
    expect((ops[0].vals as Array<Record<string, unknown>>)[0]).toMatchObject({
      user_id: "u1",
      tenant_id: "A",
    });
  });

  it("saveWorkspace updates when a row already exists", async () => {
    const { db, ops } = fakeDb({ id: "x" });
    await saveWorkspace("u1", "A", sample, db);
    expect(ops).toHaveLength(1);
    expect(ops[0].op).toBe("update");
  });
});
