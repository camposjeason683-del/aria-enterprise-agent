/**
 * Pure motion-prop computation for canvas cards (Fase 2).
 *
 * Encodes the FLIP fix from specs/canvas/smart-wrapper.spec.md: x/y/width/height
 * live ONLY in `animate`, never in `style`, so Framer Motion interpolates
 * position on timeline travel instead of teleporting — fixing the documented bug
 * at frontend/src/app/sandbox/page.tsx:1736.
 *
 * Kept as a pure function so the invariant is unit-testable without rendering
 * Framer Motion. // spec: specs/canvas/smart-wrapper.spec.md
 */
export type Zoom = "macro" | "meso" | "micro";

export interface CardMotionInput {
  zoom: Zoom;
  clampedX: number;
  clampedY: number;
  visualWidth: number;
  visualHeight: number;
  isDragging: boolean;
  isResizing: boolean;
  /** true while travelling the timeline (cinematic 0.4s), false on manual drag. */
  shouldAnimateLayout: boolean;
}

export interface CardMotion {
  animate: Record<string, number>;
  transition: Record<string, unknown>;
  /** Only stacking + origin — never x/y/width/height (the FLIP fix). */
  style: { zIndex: number; transformOrigin: string };
}

const LAYOUT_TWEEN = { type: "tween", ease: "easeOut", duration: 0.4 } as const;
const INSTANT = { duration: 0 } as const;
const SIZE_TWEEN = { type: "tween", ease: "easeOut", duration: 0.3 } as const;

export function computeCardMotion(i: CardMotionInput): CardMotion {
  const animate: Record<string, number> = { scale: 1, opacity: 1 };

  // Position is delegated to Framer (via animate) only when the card is NOT being
  // dragged/resized; during interaction the drag gesture / resize handler own it.
  if (!i.isDragging && !i.isResizing) {
    animate.x = i.clampedX;
    animate.y = i.clampedY;
  }
  if (!i.isResizing) {
    animate.width = i.visualWidth;
    animate.height = i.visualHeight;
  }

  return {
    animate,
    transition: {
      // Timeline travel → cinematic; manual drag → instant (no input lag).
      x: i.shouldAnimateLayout ? LAYOUT_TWEEN : INSTANT,
      y: i.shouldAnimateLayout ? LAYOUT_TWEEN : INSTANT,
      width: SIZE_TWEEN,
      height: SIZE_TWEEN,
      opacity: { duration: 0.25 },
      scale: { duration: 0.25 },
    },
    // FLIP FIX: no x/y/width/height here — only stacking + transform origin.
    style: { zIndex: i.zoom === "micro" ? 30 : 10, transformOrigin: "top left" },
  };
}
