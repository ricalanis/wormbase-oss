import { type ReactNode } from "react";

export interface PageProps {
  children: ReactNode;
  /** Right-side header slot (nav, actions, badges). */
  headerRight?: ReactNode;
  /** Subtitle rendered under the wordmark (mono, hash-gray). */
  subtitle?: ReactNode;
  /** If true, the page renders with no horizontal max — full bleed. */
  fullBleed?: boolean;
}

/**
 * Field Notebook Page shell — serif wordmark "WormBase," dense grid body,
 * thin horizontal rules between sections. This is the outer page frame
 * reused by every dashboard surface.
 */
export function Page({
  children,
  headerRight,
  subtitle,
  fullBleed = false,
}: PageProps) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        position: "relative",
        zIndex: 1,
      }}
    >
      <header
        style={{
          borderBottom: "1px solid var(--wb-color-aged-ink)",
          padding: "var(--wb-space-6) var(--wb-space-8)",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: "var(--wb-space-6)",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <a
            href="/"
            style={{
              textDecoration: "none",
              color: "inherit",
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-xl)",
              fontWeight: 600,
              letterSpacing: "-0.015em",
              lineHeight: 1,
              display: "inline-flex",
              alignItems: "baseline",
              gap: "8px",
            }}
          >
            <span>WormBase</span>
            <span
              className="wb-mono"
              style={{
                fontSize: "var(--wb-text-xs)",
                color: "var(--wb-color-hash-gray)",
                fontWeight: 400,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
              }}
            >
              field notebook
            </span>
          </a>
          {subtitle ? (
            <div
              className="wb-mono"
              style={{
                fontSize: "var(--wb-text-xs)",
                color: "var(--wb-color-hash-gray)",
                letterSpacing: "0.04em",
              }}
            >
              {subtitle}
            </div>
          ) : null}
        </div>
        {headerRight ? <div>{headerRight}</div> : null}
      </header>
      <main
        style={{
          maxWidth: fullBleed ? undefined : "1200px",
          margin: fullBleed ? undefined : "0 auto",
          padding: "var(--wb-space-8)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--wb-space-12)",
        }}
      >
        {children}
      </main>
      <footer
        style={{
          borderTop: "1px solid var(--wb-color-rule-line)",
          padding: "var(--wb-space-6) var(--wb-space-8)",
          textAlign: "center",
          fontFamily: "var(--wb-font-serif)",
          fontSize: "var(--wb-text-xs)",
          color: "var(--wb-color-hash-gray)",
          fontStyle: "italic",
        }}
      >
        WormBase · institutional AI for your data team · the worm remembers.
      </footer>
    </div>
  );
}
