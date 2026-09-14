"use client";

import { useCallback, useEffect, useState } from "react";

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

const AUTO_MS = 4500;
const RADIUS = 280;
const TILT = 38;

function relativeSlot(index: number, active: number) {
  let rel = (index - active) % SLIDES.length;
  if (rel < 0) rel += SLIDES.length;
  if (rel === SLIDES.length - 1) rel = -1;
  return rel;
}

function slideStyle(rel: number, compact: boolean) {
  if (compact) {
    const isFront = rel === 0;
    return {
      transform: `translate(-50%, -50%) scale(${isFront ? 1 : 0.94})`,
      opacity: isFront ? 1 : 0,
      filter: "none",
      pointerEvents: isFront ? "auto" : "none",
    } as const;
  }

  const angle = rel * (Math.PI / 3.05);
  const x = Math.sin(angle) * RADIUS;
  const z = Math.cos(angle) * RADIUS - RADIUS * 0.38;
  const rotateY = rel * -TILT;
  const scale = rel === 0 ? 1 : 0.84;
  const opacity = rel === 0 ? 1 : 0.48;
  const brightness = rel === 0 ? 1 : 0.68;

  return {
    transform: `translate(-50%, -50%) translateX(${x}px) translateZ(${z}px) rotateY(${rotateY}deg) scale(${scale})`,
    opacity,
    filter: `brightness(${brightness})`,
    pointerEvents: "auto",
  } as const;
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

export function ProductCarousel({ reducedMotion }: { reducedMotion: boolean }) {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const compact = useCompactCarousel();

  const goTo = useCallback((index: number) => {
    setActive(((index % SLIDES.length) + SLIDES.length) % SLIDES.length);
  }, []);

  useEffect(() => {
    if (reducedMotion || paused) return;
    const id = window.setInterval(() => {
      setActive((current) => (current + 1) % SLIDES.length);
    }, AUTO_MS);
    return () => window.clearInterval(id);
  }, [reducedMotion, paused, active]);

  return (
    <div
      className={styles.scene}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setPaused(false);
        }
      }}
    >
      <div
        className={styles.stage}
        id="sample-review"
        role="region"
        aria-roledescription="carousel"
        aria-label="Product preview"
      >
        {SLIDES.map((slide, index) => {
          const rel = relativeSlot(index, active);
          const isFront = rel === 0;
          return (
            <button
              key={slide.id}
              type="button"
              className={`${styles.slide} ${isFront ? styles.slideFront : styles.slideSide} appearance-none border-0 bg-transparent p-0 text-left`}
              style={slideStyle(rel, compact)}
              tabIndex={isFront ? 0 : -1}
              aria-label={`${slide.label} preview`}
              aria-current={isFront ? "true" : undefined}
              onClick={() => goTo(index)}
            >
              <slide.Card />
            </button>
          );
        })}
      </div>

      <div className={styles.dots} role="tablist" aria-label="Preview slides">
        {SLIDES.map((slide, index) => (
          <button
            key={slide.id}
            type="button"
            className={styles.dot}
            role="tab"
            aria-label={slide.label}
            aria-current={index === active ? "true" : undefined}
            onClick={() => goTo(index)}
          />
        ))}
      </div>
    </div>
  );
}
