"use client";

import { useEffect, useState } from "react";

import styles from "./landing.module.css";
import { ProductCarousel } from "./product-carousel";

function ShieldMark() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-5"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M12 2.6 20 5.6v6.2c0 5.05-3.3 8.55-8 9.7-4.7-1.15-8-4.65-8-9.7V5.6l8-3Z"
        fill="rgba(34,211,238,0.12)"
        stroke="#22d3ee"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M8.4 12.1 11 14.7l4.7-5.2"
        stroke="#22d3ee"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" className="size-4" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82A7.62 7.62 0 0 1 8 3.5c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  return reduced;
}

export function LandingPage({ loginUrl }: { loginUrl: string }) {
  const reducedMotion = usePrefersReducedMotion();

  return (
    <main className={styles.root} data-reduced={reducedMotion ? "true" : "false"}>
      <div className={styles.atmosphere} aria-hidden="true">
        <div className={styles.orb + " " + styles.orbCyan} />
        <div className={styles.orb + " " + styles.orbEmerald} />
        <div className={styles.orb + " " + styles.orbViolet} />
        <div className={styles.orb + " " + styles.orbSoft} />
        <div className={styles.grid} />
        <div className={styles.vignette} />
      </div>

      <div className={styles.frame}>
        <header className={styles.brand}>
          <ShieldMark />
          <span className="text-sm font-medium tracking-tight text-[#fafafa]">
            CodeGuard AI
          </span>
        </header>

        <section className={styles.hero}>
          <div className={styles.copy}>
            <p className={styles.eyebrow}>
              <span className={styles.eyebrowDot} />
              Quiet guardian for your PRs
            </p>
            <h1 className={styles.headline}>
              AI code review for GitHub pull requests
            </h1>
            <p className={styles.trust}>
              We request <strong>read-only</strong> access to your repositories
              and pull requests. Reviews stay private to your org — nothing
              leaves your GitHub context without your action.
            </p>
            <a className={styles.cta} href={loginUrl}>
              <GitHubMark />
              Continue with GitHub
            </a>
            <div>
              <a className={styles.sample} href="#sample-review">
                See sample review
              </a>
            </div>
            <p className={styles.legal}>
              By continuing you agree to our Terms and Privacy Policy.
              <br />
              GitHub App install required after sign-in.
            </p>
          </div>

          <ProductCarousel reducedMotion={reducedMotion} />
        </section>
      </div>
    </main>
  );
}
