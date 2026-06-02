"use client";
/**
 * SmartWrapper — the agnostic "magic box" that owns all drag/zoom/timeline
 * physics, so any card type wrapped in it inherits smooth dragging and FLIP
 * timeline interpolation with no extra code (Fase 2, SmartWrapper pattern).
 *
 * Coordinates/size are driven by `animate` (via computeCardMotion), never by
 * `style` — this is the fix for the teleport bug documented at
 * sandbox/page.tsx:1736. // spec: specs/canvas/smart-wrapper.spec.md
 */
import { motion } from "motion/react";
import type { ReactNode } from "react";

import { computeCardMotion, type Zoom } from "./cardMotion";

export interface SmartWrapperProps {
  cardId: string;
  zoom: Zoom;
  clampedX: number;
  clampedY: number;
  visualWidth: number;
  visualHeight: number;
  isDragging: boolean;
  isResizing: boolean;
  shouldAnimateLayout: boolean;
  dragConstraints?: false | Partial<{ top: number; left: number; right: number; bottom: number }>;
  onDragStart?: () => void;
  onDragEnd?: (event: PointerEvent, info: { offset: { x: number; y: number } }) => void;
  className?: string;
  children: ReactNode;
}

export function SmartWrapper(props: SmartWrapperProps) {
  const { animate, transition, style } = computeCardMotion(props);

  return (
    <motion.div
      // The key MUST stay stable across timeline travel so the card animates
      // (does not remount / pop-in). // invariant I3
      key={props.cardId}
      data-card-id={props.cardId}
      data-role="outer-card"
      // initial={false}: render directly in the animate state (no from-0 enter
      // animation). This keeps cards visible even if the entrance animation can't
      // run (e.g. a background tab where requestAnimationFrame is throttled),
      // while position/size still animate on interaction (drag, zoom, timeline).
      initial={false}
      animate={animate}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={transition}
      drag
      dragMomentum={false}
      dragConstraints={props.dragConstraints}
      dragElastic={0.05}
      onDragStart={props.onDragStart}
      onDragEnd={props.onDragEnd as never}
      style={{ ...style, position: "absolute", left: 0, top: 0 }}
      className={props.className ?? "absolute left-0 top-0"}
    >
      {props.children}
    </motion.div>
  );
}
