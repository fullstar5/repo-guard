"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";

import styles from "./landing.module.css";
import {
  FilesMockCard,
  JobsMockCard,
  ReviewMockCard,
} from "./mock-cards";

const SLIDES = [
  { id: "review", label: "Review", Card: ReviewMockCard },
  { id: "files", label: "Files", Card: FilesMockCard },
  { id: "jobs", label: "Jobs", Card: JobsMockCard },
] as const;

const COUNT = SLIDES.length;
const AUTO_MS = 4500;
const IDLE_AFTER_DRAG_MS = 2200;
const PX_PER_SLOT = 240;
const RADIUS = 320;
const TILT = 34;
const SLOT_ANGLE = Math.PI / 3.05;
const SIDE_SCALE = 0.84;
const DRAG_CLICK_PX = 8;

function wrapIndex(index: number) {
  return ((index % COUNT) + COUNT) % COUNT;
}

function wrapRel(index: number, slot: number) {
  let rel = index - slot;
  const half = COUNT / 2;
  while (rel > half) rel -= COUNT;
  while (rel < -half) rel += COUNT;
  return rel;
}

function slideStyle(rel: number, compact: boolean) {
  if (compact) {
    return undefined;
  }

  const abs = Math.abs(rel);
  const angle = rel * SLOT_ANGLE;
  const x = Math.sin(angle) * RADIUS;
  const z = Math.cos(angle) * RADIUS - RADIUS * 0.38;
  const rotateY = rel * -TILT;
  const scale = 1 - Math.min(abs, 1) * (1 - SIDE_SCALE);
  const opacity = 1 - Math.min(abs, 1) * 0.28;

  return {
    transform: `translate(-50%, -50%) translate3d(${x.toFixed(1)}px, 0, ${z.toFixed(1)}px) rotateY(${rotateY.toFixed(2)}deg) scale(${scale.toFixed(3)})`,
    opacity,
    zIndex: Math.round((1 - abs) * 24) + 2,
  };
}

function useCompactCarousel() {
  const [compact, setCompact] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const sync = () => setCompact(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  return compact;
}

type PanOffset = {
  offset: { x: number };
  velocity: { x: number };
};

export function ProductCarousel({ reducedMotion }: { reducedMotion: boolean }) {
  const [active, setActive] = useState(0);
  const [dragSlots, setDragSlots] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [autoDelay, setAutoDelay] = useState(AUTO_MS);
  const draggedRef = useRef(false);
  const compact = useCompactCarousel();
  const slot = active + dragSlots;

  const goTo = useCallback((index: number) => {
    setActive(wrapIndex(index));
    setDragSlots(0);
    setAutoDelay(AUTO_MS);
  }, []);

  useEffect(() => {
    if (reducedMotion || dragging) return;
    const id = window.setTimeout(() => {
      setActive((current) => wrapIndex(current + 1));
      setAutoDelay(AUTO_MS);
    }, autoDelay);
    return () => window.clearTimeout(id);
  }, [active, autoDelay, dragging, reducedMotion]);

  function onPanStart() {
    draggedRef.current = false;
    setDragging(true);
  }

  function onPan(_event: PointerEvent, info: PanOffset) {
    if (Math.abs(info.offset.x) > DRAG_CLICK_PX) {
      draggedRef.current = true;
    }
    setDragSlots(-info.offset.x / PX_PER_SLOT);
  }

  function onPanEnd(_event: PointerEvent, info: PanOffset) {
    const projected =
      active - info.offset.x / PX_PER_SLOT - info.velocity.x / 900;
    const next = wrapIndex(Math.round(projected));
    setDragSlots(0);
    setDragging(false);
    setActive(next);
    setAutoDelay(draggedRef.current ? IDLE_AFTER_DRAG_MS : AUTO_MS);
  }

  function onCardActivate(index: number) {
    if (draggedRef.current) return;
    goTo(index);
  }

  return (
    <div className={styles.scene}>
      <motion.div
        className={`${styles.stage} ${compact ? styles.stageCompact : ""} ${
          dragging ? styles.stageDragging : ""
        }`}
        id="sample-review"
        role="region"
        aria-roledescription="carousel"
        aria-label="Product preview. Drag or swipe to rotate."
        tabIndex={0}
        onPanStart={onPanStart}
        onPan={onPan}
        onPanEnd={onPanEnd}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight") {
            event.preventDefault();
            goTo(active + 1);
          } else if (event.key === "ArrowLeft") {
            event.preventDefault();
            goTo(active - 1);
          }
        }}
      >
        {SLIDES.map((slide, index) => {
          const rel = wrapRel(index, slot);
          const isFront = Math.abs(rel) < 0.45;
          return (
            <div
              key={slide.id}
              className={`${styles.slide} ${isFront ? styles.slideFront : styles.slideSide} ${
                compact ? styles.slideCompact : ""
              } ${dragging ? styles.slideDragging : ""}`}
              style={slideStyle(rel, compact)}
              hidden={compact && !isFront}
              aria-hidden={!isFront}
              aria-label={`${slide.label} preview`}
              onClick={() => onCardActivate(index)}
            >
              <slide.Card />
            </div>
          );
        })}
      </motion.div>

      <div className={styles.dots} role="tablist" aria-label="Preview slides">
        {SLIDES.map((slide, index) => (
          <button
            key={slide.id}
            type="button"
            className={styles.dot}
            role="tab"
            aria-label={slide.label}
            aria-current={index === wrapIndex(Math.round(slot)) ? "true" : undefined}
            onClick={() => goTo(index)}
          />
        ))}
      </div>
    </div>
  );
}
