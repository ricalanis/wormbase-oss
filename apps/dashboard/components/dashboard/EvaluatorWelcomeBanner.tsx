/**
 * EvaluatorWelcomeBanner — Phase 4C welcome state.
 *
 * Renders when /dashboard receives ``?welcome=email`` (magic-link
 * evaluator) or any future welcome source. The banner explains the
 * read-only seeded-demo posture so evaluators don't try to write
 * data and assume it's broken when admin operations don't fire.
 *
 * Render rules:
 *   - source='email' → email-evaluator copy
 *   - source=any other value → render nothing (forward-compat for
 *     future welcome sources like ?welcome=slack-fresh).
 */
import type { CSSProperties } from "react";

export interface EvaluatorWelcomeBannerProps {
  /** Welcome-source code from the URL (e.g. 'email'). */
  source: string | undefined;
  /** Tenant display name to surface in the banner. Optional fallback. */
  tenantDisplayName?: string;
}

export function EvaluatorWelcomeBanner({
  source,
  tenantDisplayName,
}: EvaluatorWelcomeBannerProps) {
  if (source !== "email") return null;
  const tenantName = tenantDisplayName ?? "the seeded demo tenant";
  return (
    <aside
      data-testid="evaluator-welcome-banner"
      role="status"
      aria-live="polite"
      style={bannerStyle}
    >
      <span className="wb-mono" style={eyebrowStyle}>
        magic link · evaluator session
      </span>
      <h2 style={headlineStyle}>Welcome — you&rsquo;re in {tenantName}.</h2>
      <p style={subheadStyle}>
        You arrived via a magic link, so we put you in a seeded demo tenant
        with read-only access. Browse the lake, the KPI tree, the trace
        ledger, and the worm&rsquo;s activity. To install on your own Slack
        workspace and start a fresh tenant, follow the &ldquo;connect to
        Slack&rdquo; CTA on the landing page.
      </p>
    </aside>
  );
}

const bannerStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "16px 20px",
  border: "1px dashed var(--wb-color-rule-line)",
  background: "var(--wb-color-botanical-green-soft)",
  color: "var(--wb-color-aged-ink)",
};

const eyebrowStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 20,
  fontWeight: 500,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-aged-ink-soft)",
};
