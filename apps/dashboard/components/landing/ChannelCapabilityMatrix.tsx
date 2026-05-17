/**
 * ChannelCapabilityMatrix — W2-B of the WhatsApp dashboard surfacing wave.
 *
 * Composed onto `/security` after the `SecurityPosture` proof points. The
 * panel renders the channel-platform capability + transport + compliance
 * posture as a table, keyed on the canonical `PLATFORMS` array from
 * `lib/platform-status.ts`. Drift between the table and the platform
 * descriptors is impossible — when a new platform graduates capabilities,
 * the contract test on the descriptor source asserts the change, and the
 * row here renders automatically.
 *
 * Honest claims only — same posture as `SecurityPosture`:
 *   - "Production. SOC-2 ready." for Slack (the audit primitives are real;
 *     the SOC-2 control track is in progress per plate v above)
 *   - "Preview. Baileys ToS caveat — use on dedicated test numbers only."
 *     for WhatsApp (the C-wave wired send via subprocess; production
 *     graduation pending operator scopes + Meta Cloud API)
 *   - "Coming soon." for Discord / Teams (stub adapters; no production wire)
 *
 * One-line ingest pricing note follows the table — preview-tier ingest is
 * free; production-tier pricing follows post-Meta-Cloud-API rollout.
 *
 * Visible to ALL roles — `/security` is the public unauthenticated trust
 * page, so no role-gate at the component or composition level.
 */
import type { CSSProperties } from "react";

import {
  PLATFORMS,
  type Capability,
  type PlatformDescriptor,
} from "../../lib/platform-status";

interface CapabilityRow {
  /** Slug used for testid + DOM anchor; matches the descriptor's `platform`. */
  slug: string;
  /** Display label — "Slack", "WhatsApp", or grouped "Discord, Teams". */
  label: string;
  /**
   * Transport prose. Hand-rolled per row — the descriptor's envHint is too
   * terse and the statusNote is too verbose. This is the editorial summary
   * of HOW the platform's wire actually works.
   */
  transport: string;
  /**
   * Capabilities to render as comma-separated chips. Read from the
   * descriptor's `capabilities` field when present; falls back to a
   * curated dash for stub adapters.
   */
  capabilities: string;
  /** One-line compliance posture; status grade made human-readable. */
  posture: string;
  /** True for the WhatsApp row to surface the ToS caveat in a tooltip. */
  caveat?: string;
}

/**
 * Build the matrix rows from the canonical PLATFORMS array. Order:
 * production rows first, preview next, coming_soon grouped last.
 *
 * Rendering rules:
 *   - Slack — full capability list from descriptor; transport prose
 *     describes the OAuth bot + Socket Mode wire.
 *   - WhatsApp — capabilities from descriptor (post-C-wave: ingest, dm,
 *     send); transport names OpenClaw + Baileys; posture surfaces the
 *     Baileys ToS caveat.
 *   - Discord + Teams — grouped into one row labeled "Coming soon" with
 *     no capability chips. The descriptors carry `status="preview"` /
 *     `coming_soon` per platform-status.ts; the matrix collapses them
 *     for editorial brevity (both are stub adapters until v1.5).
 */
function buildRows(platforms: PlatformDescriptor[]): CapabilityRow[] {
  const slack = platforms.find((p) => p.platform === "slack");
  const whatsapp = platforms.find((p) => p.platform === "whatsapp");
  const discord = platforms.find((p) => p.platform === "discord");
  const teams = platforms.find((p) => p.platform === "teams");

  const rows: CapabilityRow[] = [];

  if (slack) {
    rows.push({
      slug: slack.platform,
      label: slack.label,
      transport: "OAuth bot, Socket Mode",
      capabilities: formatCapabilities(slack.capabilities) ?? "ingest, send, dm, file_upload",
      posture: "Production. SOC-2 ready.",
    });
  }

  if (whatsapp) {
    rows.push({
      slug: whatsapp.platform,
      label: whatsapp.label,
      transport: "OpenClaw Baileys (WhatsApp Web)",
      capabilities: formatCapabilities(whatsapp.capabilities) ?? "ingest, dm, send",
      posture: "Preview. Baileys ToS caveat — use on dedicated test numbers only.",
      caveat: whatsapp.statusNote,
    });
  }

  // Group the stub adapters into one row. We render whichever exist; in
  // practice both ship in PLATFORMS today.
  const stubs: string[] = [];
  if (discord) stubs.push(discord.label);
  if (teams) stubs.push(teams.label);
  if (stubs.length > 0) {
    rows.push({
      slug: "stubs",
      label: stubs.join(", "),
      transport: "Stub adapters",
      capabilities: "—",
      posture: "Coming soon.",
    });
  }

  return rows;
}

/**
 * Render a capability set as a comma-separated string. Returns null when
 * the descriptor doesn't carry a `capabilities` field — caller falls back
 * to its hand-rolled label.
 */
function formatCapabilities(caps: Capability[] | undefined): string | null {
  if (!caps || caps.length === 0) return null;
  return caps.join(", ");
}

export function ChannelCapabilityMatrix() {
  const rows = buildRows(PLATFORMS);

  return (
    <section
      data-testid="channel-capability-matrix"
      aria-labelledby="channel-capability-matrix-headline"
      style={sectionStyle}
    >
      <div style={innerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate vi.b · channel capability matrix
        </p>
        <h2
          id="channel-capability-matrix-headline"
          data-testid="channel-capability-matrix-headline"
          style={headlineStyle}
        >
          Channel transport &amp; capability honesty.
        </h2>
        <p style={subheadStyle}>
          Each row mirrors the canonical adapter declaration in
          {" "}
          <code className="wb-mono">apps/dashboard/lib/platform-status.ts</code>
          {" "}— the same source the channels picker reads. When an adapter
          graduates capabilities upstream the row updates automatically; the
          pinned-mirror contract test fails loudly if the dashboard lags.
        </p>

        <div style={tableScrollStyle}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th scope="col" style={thStyle}>Platform</th>
                <th scope="col" style={thStyle}>Transport</th>
                <th scope="col" style={thStyle}>Capabilities</th>
                <th scope="col" style={thStyle}>Compliance posture</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.slug}
                  data-testid={`capability-row-${row.slug}`}
                  style={rowStyle}
                >
                  <th scope="row" style={tdLabelStyle}>
                    {row.label}
                  </th>
                  <td style={tdStyle}>{row.transport}</td>
                  <td style={tdCapsStyle}>
                    <code className="wb-mono" style={capsCodeStyle}>
                      {row.capabilities}
                    </code>
                  </td>
                  <td style={tdStyle} title={row.caveat ?? undefined}>
                    {row.posture}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p
          data-testid="capability-matrix-pricing-note"
          className="wb-mono"
          style={pricingNoteStyle}
        >
          WhatsApp ingest is free during preview; production tier
          (post-Meta-Cloud-API) gets full pricing.
        </p>
      </div>
    </section>
  );
}

const sectionStyle: CSSProperties = {
  width: "100%",
  padding: "0 24px 96px",
  background: "var(--wb-color-paper)",
};

const innerStyle: CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const eyebrowStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(22px, 2.6vw, 30px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.2,
  maxWidth: 820,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const tableScrollStyle: CSSProperties = {
  width: "100%",
  overflowX: "auto",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
  marginTop: 12,
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink)",
};

const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "12px 16px",
  borderBottom: "1px solid var(--wb-color-rule-line)",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 11,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  fontWeight: 600,
  background: "var(--wb-color-paper-deep)",
  whiteSpace: "nowrap",
};

const rowStyle: CSSProperties = {
  borderTop: "1px solid var(--wb-color-rule-line)",
};

const tdLabelStyle: CSSProperties = {
  padding: "14px 16px",
  textAlign: "left",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  whiteSpace: "nowrap",
};

const tdStyle: CSSProperties = {
  padding: "14px 16px",
  lineHeight: 1.5,
  verticalAlign: "top",
};

const tdCapsStyle: CSSProperties = {
  padding: "14px 16px",
  verticalAlign: "top",
};

const capsCodeStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-paper-edge)",
  padding: "2px 8px",
  borderRadius: 2,
  whiteSpace: "nowrap",
};

const pricingNoteStyle: CSSProperties = {
  margin: "16px 0 0",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
  lineHeight: 1.55,
};
