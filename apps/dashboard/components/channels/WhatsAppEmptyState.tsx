/**
 * WhatsAppEmptyState — visible empty state when no WhatsApp install is
 * present, but the dashboard is rendering the WhatsApp section anyway.
 *
 * Phase D1 (2026-05-06) — per CLAUDE.md §9 cleanup checklist:
 *   "Activity-panel components that render nothing on empty data — every
 *   tab must carry a visible empty-state when its read accessor returns
 *   ``[]``. Silent panels are demo seams disguised as design."
 *
 * Phase W2-C (2026-05-07) — the runbook reference is now a CTA link to
 * `/channels/connect/whatsapp`, the dedicated pairing-instructions page.
 * Operators who want the full step-by-step flow (ToS acknowledgment,
 * docker exec snippet, post-pair polling) follow the link rather than
 * opening the raw markdown runbook. The runbook itself is still
 * cross-linked in the connect page footer for operators who prefer it.
 *
 * Caveat surfaced verbatim from the WhatsAppChannelAdapter status note —
 * the Baileys ToS posture is part of the empty state, not the post-pair
 * card, because the operator decides whether to pair at all here.
 */
import Link from "next/link";

export function WhatsAppEmptyState() {
  return (
    <section
      data-testid="whatsapp-install-empty"
      data-platform="whatsapp"
      style={{
        border: "1px dashed var(--wb-color-sepia-warning-deep)",
        background: "var(--wb-color-paper-deep)",
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          whatsapp · not paired
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          Connect WhatsApp via QR pairing
        </h3>
      </header>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
          color: "var(--wb-color-aged-ink)",
          lineHeight: 1.5,
        }}
      >
        WhatsApp routes through OpenClaw + Baileys (unofficial WhatsApp Web).
        Pairing is one-time per tenant: scan a QR code and the worm joins
        as a bot account. Use a dedicated test number — Baileys is not on
        WhatsApp's official partner list and is ToS-caveated.
      </p>
      <Link
        data-testid="whatsapp-connect-cta"
        href="/channels/connect/whatsapp"
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-aged-ink)",
          background: "var(--wb-color-paper)",
          border: "1px solid var(--wb-color-aged-ink)",
          padding: "6px 12px",
          alignSelf: "flex-start",
          textDecoration: "none",
          letterSpacing: "0.04em",
        }}
      >
        Open pairing instructions →
      </Link>
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
          letterSpacing: "0.04em",
        }}
      >
        runbook · infra/openclaw/WHATSAPP_PAIRING.md
      </span>
    </section>
  );
}
