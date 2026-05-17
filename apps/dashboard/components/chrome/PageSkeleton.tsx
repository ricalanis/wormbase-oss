/**
 * PageSkeleton — generic chrome skeleton shown inside a Suspense fallback.
 *
 * Editorial intent (W3.A14): the loading state is itself a recognizable
 * field-notebook page, not a generic spinner. Three placeholder cards stack
 * beneath an editorial header; thin paper-edge rules separate them; everything
 * pulses subtly so the operator knows the page is fetching, not stuck.
 *
 * Square corners, wb-mono eyebrow, serif title, sepia dashed border on each
 * card. Mirrors EmptyState chrome so the loading surface feels of a piece with
 * the empty surface — moving from "loading" to "empty" or "loaded" never jars
 * the eye.
 *
 * Used by:
 *   - PageSuspenseBoundary (the default fallback)
 *   - any tab that wants to render a custom Suspense fallback can import the
 *     skeleton primitive directly and pass `lines` for finer control.
 */
import type { CSSProperties } from "react";

export interface PageSkeletonProps {
  /** Override the eyebrow ("loading"); useful if the tab knows the section. */
  eyebrow?: string;
  /** Override the title placeholder copy. */
  title?: string;
  /**
   * Number of skeleton cards rendered beneath the header. Defaults to 3 —
   * enough to feel like a field-notebook page without filling the viewport.
   */
  cards?: number;
  /** data-testid on the wrapper. */
  testId?: string;
}

const PULSE_KEYFRAMES = `
  @keyframes wb-skeleton-pulse {
    0%   { opacity: 0.55; }
    50%  { opacity: 0.95; }
    100% { opacity: 0.55; }
  }
`;

const pulseStyle: CSSProperties = {
  animation: "wb-skeleton-pulse 1.6s ease-in-out infinite",
  background: "var(--wb-color-paper-edge)",
};

export function PageSkeleton({
  eyebrow = "loading",
  title = "Reading the ledger…",
  cards = 3,
  testId,
}: PageSkeletonProps) {
  const cardArray = Array.from({ length: Math.max(1, cards) });
  return (
    <section
      data-testid={testId ?? "page-skeleton"}
      aria-busy="true"
      aria-live="polite"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      <style>{PULSE_KEYFRAMES}</style>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {eyebrow}
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
            letterSpacing: "-0.005em",
            color: "var(--wb-color-aged-ink)",
            opacity: 0.65,
          }}
        >
          {title}
        </h1>
        <div
          aria-hidden
          style={{ ...pulseStyle, height: 8, width: "42%" }}
        />
      </header>
      <div
        style={{ display: "flex", flexDirection: "column", gap: 14 }}
        data-testid="page-skeleton-cards"
      >
        {cardArray.map((_, idx) => (
          <article
            key={idx}
            data-testid={`page-skeleton-card-${idx}`}
            style={{
              border: "1px dashed var(--wb-color-aged-ink)",
              padding: "20px 24px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
              background: "var(--wb-color-paper)",
            }}
          >
            <div
              aria-hidden
              style={{
                ...pulseStyle,
                height: 10,
                width: "28%",
                animationDelay: `${idx * 0.12}s`,
              }}
            />
            <div
              aria-hidden
              style={{
                ...pulseStyle,
                height: 14,
                width: "72%",
                animationDelay: `${idx * 0.12 + 0.05}s`,
              }}
            />
            <div
              aria-hidden
              style={{
                ...pulseStyle,
                height: 10,
                width: "60%",
                animationDelay: `${idx * 0.12 + 0.1}s`,
              }}
            />
          </article>
        ))}
      </div>
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        the worm is reading the ledger
      </span>
    </section>
  );
}
