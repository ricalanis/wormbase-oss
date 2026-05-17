/**
 * WhatsAppGraduationBanner — Wave 3.2 Hole #5 (2026-05-11).
 *
 * Capability-honesty banner pinned to the top of /channels/connect/whatsapp.
 * Distinguishes the five production-ready WhatsApp capabilities (listening,
 * identity-discovery, conversation-sync, history-replay, DMs) from the one
 * preview capability (sending bot replies), and surfaces the 3-step path to
 * graduate Send to production:
 *
 *   1. Operator-approved write scopes via OpenClaw Control UI
 *   2. Channel-adapter docker-host access or upstream HTTP route (OpenClaw #73016)
 *   3. WORMBASE_WHATSAPP_SEND_DISABLE=false in tenant config
 *
 * Renders regardless of pairing state — the message is about send-capability
 * graduation, not about whether the tenant has paired. The `paired` prop is
 * threaded through so future revisions can vary kicker text without changing
 * the banner's reason for existing.
 *
 * Background: CLAUDE.md §3 captures the full preview rationale. OpenClaw issue
 * #73016 tracks the Meta Cloud API upstream rollout that would unblock the
 * second graduation step at the platform layer.
 */
import type { CSSProperties } from "react";

export interface WhatsAppGraduationBannerProps {
  /**
   * Whether this tenant has a WhatsApp install row in the ledger.
   * Surfaces in the kicker so operators reading the banner know which
   * stage of the journey they're at. The banner renders in both states
   * because the message is about send-capability graduation, not pairing.
   */
  paired: boolean;
}

const RUNBOOK_URL =
  "https://github.com/wormbase/docs/whatsapp-graduation";

const PRODUCTION_READY_CAPABILITIES = [
  "Listening",
  "identity-discovery",
  "conversation-sync",
  "history-replay",
  "DMs",
] as const;

export function WhatsAppGraduationBanner({
  paired,
}: WhatsAppGraduationBannerProps) {
  const productionReadyText = formatCapabilityList(
    PRODUCTION_READY_CAPABILITIES,
  );

  return (
    <aside
      aria-label="WhatsApp capability status"
      data-testid="whatsapp-graduation-banner"
      data-paired={paired ? "true" : "false"}
      style={asideStyle}
    >
      <header style={headerStyle}>
        <span className="wb-mono" style={kickerStyle}>
          capability honesty · {paired ? "paired" : "pre-pair"}
        </span>
        <h3 style={titleStyle}>
          WhatsApp · <em style={previewEmStyle}>Preview</em>
        </h3>
      </header>

      <p style={bodyStyle}>
        <strong>
          {productionReadyText} are production-ready.
        </strong>{" "}
        Sending (bot replies) is in <strong>preview</strong> — gated on
        operator-approved write scopes via OpenClaw.
      </p>

      <details
        data-testid="whatsapp-graduation-steps"
        style={detailsStyle}
      >
        <summary style={summaryStyle}>
          How to graduate Send to production
        </summary>
        <ol
          data-testid="whatsapp-graduation-steps-list"
          style={stepsListStyle}
        >
          <li style={stepItemStyle}>
            Operator approves write scopes via OpenClaw Control UI
            (today&rsquo;s device has{" "}
            <code className="wb-mono">operator.read</code> only)
          </li>
          <li style={stepItemStyle}>
            Channel-adapter container has docker-host access OR upstream
            HTTP route ships (OpenClaw issue #73016)
          </li>
          <li style={stepItemStyle}>
            Set{" "}
            <code className="wb-mono">
              WORMBASE_WHATSAPP_SEND_DISABLE=false
            </code>{" "}
            in tenant config
          </li>
        </ol>
      </details>

      <p style={runbookParaStyle}>
        <a
          href={RUNBOOK_URL}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="whatsapp-graduation-runbook-link"
          style={runbookLinkStyle}
        >
          Full graduation runbook →
        </a>
      </p>
    </aside>
  );
}

function formatCapabilityList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

const asideStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  padding: "20px 24px",
  border: "1px solid var(--wb-color-sepia-warning-deep)",
  background: "var(--wb-color-paper-deep)",
  borderRadius: 2,
};

const headerStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const kickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-sepia-warning-deep)",
};

const titleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const previewEmStyle: CSSProperties = {
  fontStyle: "italic",
  fontWeight: 500,
  color: "var(--wb-color-sepia-warning-deep)",
};

const bodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
};

const detailsStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
};

const summaryStyle: CSSProperties = {
  cursor: "pointer",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-aged-ink)",
  padding: "4px 0",
};

const stepsListStyle: CSSProperties = {
  margin: "8px 0 0",
  paddingLeft: 22,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const stepItemStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.55,
};

const runbookParaStyle: CSSProperties = {
  margin: 0,
};

const runbookLinkStyle: CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  letterSpacing: "0.04em",
  color: "var(--wb-color-aged-ink)",
  textUnderlineOffset: 3,
};
