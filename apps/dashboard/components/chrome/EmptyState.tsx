/**
 * EmptyState — chrome primitive for honest empty surfaces.
 *
 * Replaces the family of fixture-fallback panels that used to fake tenant
 * data. Per the no-demo-seams principle: a tab with no rows reads as a
 * tab with no rows, but the panel still tells the operator how to make
 * the rows appear (drop a file in the worm channel, paste a credential
 * in DM, add a source via the form, etc.).
 *
 * Editorial chrome — square corners, wb-mono eyebrow, serif body, sepia
 * dashed border. No Tailwind, no emojis, no rounded corners. Matches the
 * MemberAccessBanner / Receipt visual language so empty states feel of
 * a piece with the rest of the dashboard.
 *
 * Design intent:
 *   - Eyebrow ("no <thing> yet") — small wb-mono uppercase.
 *   - Title — serif, intent-conveying, never "no data".
 *   - Description — italic gray, 1-2 sentences, names the trigger flow.
 *   - CTA — optional; either an in-app link or a directive ("Drop a file
 *     in your worm channel"). Both render as a square button with the
 *     botanical-green accent.
 */

import Link from "next/link";

export interface EmptyStateProps {
  /** Small uppercase eyebrow above the title. e.g. "no kpis yet". */
  eyebrow?: string;
  /** Headline — serif, intent-conveying. e.g. "The worm hasn't proposed any KPIs yet." */
  title: string;
  /** 1-2 sentence honest explanation. Names the trigger flow. */
  description: string;
  /** Optional primary CTA. Either an internal link (`href`) or pure prose. */
  cta?: {
    label: string;
    href?: string;
  };
  /** Secondary CTA, rendered inline next to the primary. */
  secondaryCta?: {
    label: string;
    href?: string;
  };
  /** data-testid on the outer wrapper for unit / e2e tests. */
  testId?: string;
}

export function EmptyState({
  eyebrow,
  title,
  description,
  cta,
  secondaryCta,
  testId,
}: EmptyStateProps) {
  return (
    <section
      data-testid={testId ?? "empty-state"}
      style={{
        border: "1px dashed var(--wb-color-aged-ink)",
        padding: "32px 28px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        background: "var(--wb-color-paper)",
      }}
    >
      {eyebrow ? (
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
      ) : null}
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 22,
          fontWeight: 500,
          letterSpacing: "-0.005em",
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {title}
      </h2>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: 14,
          lineHeight: 1.55,
          color: "var(--wb-color-hash-gray)",
          maxWidth: 640,
        }}
      >
        {description}
      </p>
      {cta || secondaryCta ? (
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 4,
            alignItems: "baseline",
            flexWrap: "wrap",
          }}
        >
          {cta ? <EmptyStateCTA cta={cta} primary /> : null}
          {secondaryCta ? <EmptyStateCTA cta={secondaryCta} /> : null}
        </div>
      ) : null}
    </section>
  );
}

interface CTADef {
  label: string;
  href?: string;
}

function EmptyStateCTA({
  cta,
  primary = false,
}: {
  cta: CTADef;
  primary?: boolean;
}) {
  const baseStyle: React.CSSProperties = {
    display: "inline-block",
    padding: "8px 14px",
    borderRadius: 0,
    fontFamily: "var(--wb-font-serif)",
    fontSize: 13,
    textDecoration: "none",
    border: primary
      ? "1px solid var(--wb-color-botanical-green-deep)"
      : "1px solid var(--wb-color-aged-ink)",
    background: primary ? "var(--wb-color-botanical-green)" : "transparent",
    color: primary ? "var(--wb-color-paper)" : "var(--wb-color-aged-ink)",
    cursor: cta.href ? "pointer" : "default",
  };
  if (cta.href) {
    return (
      <Link href={cta.href} style={baseStyle} data-testid="empty-state-cta">
        {cta.label}
      </Link>
    );
  }
  return (
    <span style={baseStyle} data-testid="empty-state-cta">
      {cta.label}
    </span>
  );
}
