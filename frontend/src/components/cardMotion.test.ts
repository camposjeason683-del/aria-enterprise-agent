// spec: specs/canvas/smart-wrapper.spec.md
import { describe, expect, it } from "vitest";

import { computeCardMotion, type CardMotionInput } from "./cardMotion";

const base: CardMotionInput = {
  zoom: "macro",
  clampedX: 100,
  clampedY: 200,
  visualWidth: 320,
  visualHeight: 220,
  isDragging: false,
  isResizing: false,
  shouldAnimateLayout: true,
};

describe("computeCardMotion — the FLIP fix", () => {
  it("never puts x/y/width/height in style (I1)", () => {
    const m = computeCardMotion(base);
    expect(m.style).not.toHaveProperty("x");
    expect(m.style).not.toHaveProperty("y");
    expect(m.style).not.toHaveProperty("width");
    expect(m.style).not.toHaveProperty("height");
    expect(m.style.zIndex).toBe(10);
    expect(m.style.transformOrigin).toBe("top left");
  });

  it("delegates x/y to animate during timeline travel, ~0.4s (I1/I2)", () => {
    const m = computeCardMotion({ ...base, shouldAnimateLayout: true });
    expect(m.animate.x).toBe(100);
    expect(m.animate.y).toBe(200);
    expect((m.transition.x as { duration: number }).duration).toBe(0.4);
  });

  it("drag is instant: no x/y in animate, transition duration 0 (I2)", () => {
    const m = computeCardMotion({ ...base, isDragging: true, shouldAnimateLayout: false });
    expect(m.animate.x).toBeUndefined();
    expect(m.animate.y).toBeUndefined();
    expect((m.transition.x as { duration: number }).duration).toBe(0);
  });

  it("omits width/height from animate while resizing", () => {
    const m = computeCardMotion({ ...base, isResizing: true });
    expect(m.animate.width).toBeUndefined();
    expect(m.animate.height).toBeUndefined();
  });

  it("raises zIndex when zoomed to micro", () => {
    expect(computeCardMotion({ ...base, zoom: "micro" }).style.zIndex).toBe(30);
    expect(computeCardMotion({ ...base, zoom: "meso" }).style.zIndex).toBe(10);
  });
});
