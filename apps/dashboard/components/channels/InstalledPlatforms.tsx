/**
 * InstalledPlatforms — one card per `Install` row.
 *
 * D3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Live-folded from `emit_install_completed` (active) − `emit_install_revoked`
 * (status flipped). One card per (tenant, platform). Visual language matches
 * the rest of the surface: paper-edge border, square corners, wb-mono caps
 * for metadata, serif for the platform name.
 *
 * Capability honesty: each card carries the platform's capability status
 * (production / preview / coming_soon) read from
 * ``lib/platform-status.ts``. When at least one preview / coming_soon
 * platform is in the install list, the section prepends an info banner
 * explaining what works and what doesn't ("Discord installs are in
 * Preview. The worm lurks but doesn't post yet.").
 *
 * Phase D1 (2026-05-06) — WhatsApp installs render with pairing-status
 * vocabulary (paired / awaiting / expired / disconnected) and a Baileys
 * ToS caveat in the card's title hover. When no WhatsApp install row
 * exists but the env is configured (the OpenClaw `WHATSAPP_ACCOUNT_ID`
 * block ships preview), the page renders a visible empty state pointing
 * at the QR pairing runbook.
 */
import { Receipt } from "../../lib/receipts";
import { chipStyle, statusTone } from "../people/_styles";
import type { InstallRow } from "../../lib/ledger-client.types";
import {
  platformBySlug,
  type Capability,
  type PlatformDescriptor,
  type PlatformSlug,
  type PlatformStatus,
} from "../../lib/platform-status";

/**
 * Per-(platform, capability) tooltip prose. W3-A (2026-05-07) — when a
 * descriptor opts into ``capabilities``, each chip surfaces a small
 * tooltip explaining the capability + the gate that constrains it. Falls
 * back to ``CAPABILITY_TOOLTIPS_GENERIC`` when no platform-specific
 * override exists. Add a new platform's overrides here when its
 * descriptor opts in.
 */
const CAPABILITY_TOOLTIPS_GENERIC: Record<Capability, string> = {
  ingest: "Reads inbound messages from this platform.",
  send: "Sends outbound messages back through this platform.",
  dm: "Receives direct messages and replies in private channels.",
  file_upload: "Receives file attachments uploaded in channels.",
  voice: "Joins voice calls and ingests audio content.",
};

const CAPABILITY_TOOLTIPS_WHATSAPP: Partial<Record<Capability, string>> = {
  ingest: "Inbound DM ingest via OpenClaw Baileys (WhatsApp Web).",
  dm: "Direct messages from paired test number; bot lurks until @-mentioned.",
  send: "Wired via CLI subprocess. Operator write-scope approval required to round-trip live.",
};

const PLATFORM_TOOLTIP_OVERRIDES: Partial<
  Record<PlatformSlug, Partial<Record<Capability, string>>>
> = {
  whatsapp: CAPABILITY_TOOLTIPS_WHATSAPP,
};

function tooltipForCapability(
  platform: PlatformSlug,
  capability: Capability,
): string {
  return (
    PLATFORM_TOOLTIP_OVERRIDES[platform]?.[capability] ??
    CAPABILITY_TOOLTIPS_GENERIC[capability]
  );
}

interface PreviewBanner {
  status: PlatformStatus;
  label: string;
  note: string;
}

function bannersFromInstalls(installs: InstallRow[]): PreviewBanner[] {
  const seen = new Set<string>();
  const banners: PreviewBanner[] = [];
  for (const i of installs) {
    if (seen.has(i.platform)) continue;
    seen.add(i.platform);
    const desc = platformBySlug(i.platform);
    if (!desc) continue;
    if (desc.status === "production") continue;
    banners.push({
      status: desc.status,
      label: desc.label,
      note: desc.statusNote,
    });
  }
  return banners;
}

export function InstalledPlatforms({ installs }: { installs: InstallRow[] }) {
  if (installs.length === 0) {
    return (
      <section
        data-testid="installed-platforms-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: 24,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
          textAlign: "center",
        }}
      >
        No platforms connected. Use the buttons below to bring the worm into a
        channel.
      </section>
    );
  }
  const banners = bannersFromInstalls(installs);
  return (
    <section
      data-testid="installed-platforms"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      {banners.length > 0 ? (
        <div
          data-testid="installed-platforms-honesty-banners"
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          {banners.map((b) => (
            <div
              key={b.label}
              data-testid={`installed-platforms-banner-${b.status}`}
              style={{
                border: "1px solid var(--wb-color-sepia-warning-deep)",
                background: "var(--wb-color-paper-deep)",
                padding: 10,
                display: "flex",
                flexDirection: "column",
                gap: 2,
              }}
            >
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-sepia-warning-deep)",
                }}
              >
                {b.label} installs are in {b.status === "preview" ? "preview" : "coming soon"}
              </span>
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink)",
                  lineHeight: 1.5,
                }}
              >
                {b.note}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {installs.map((i) => (
          <PlatformCard
            key={i.installId}
            install={i}
            descriptor={platformBySlug(i.platform)}
          />
        ))}
      </div>
    </section>
  );
}

function PlatformCard({
  install,
  descriptor,
}: {
  install: InstallRow;
  descriptor: PlatformDescriptor | null;
}) {
  // Pairing-status vocabulary differs by platform. WhatsApp uses
  // paired/awaiting/expired/disconnected (Baileys lifecycle). Slack and
  // others use the OAuth grant's active/revoked → connected/disconnected.
  // Falls back to install.status when the projection didn't supply one.
  const pairing = install.pairingStatus ??
    (install.status === "active"
      ? install.platform === "whatsapp" ? "paired" : "connected"
      : install.platform === "whatsapp" ? "expired" : "disconnected");
  return (
    <article
      data-testid={`platform-card-${install.platform}`}
      data-status={install.status}
      data-capability-status={descriptor?.status ?? "unknown"}
      data-pairing-status={pairing}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 14,
        background:
          install.status === "revoked"
            ? "var(--wb-color-paper-deep)"
            : "var(--wb-color-paper)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        opacity: install.status === "revoked" ? 0.7 : 1,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          {install.platform}
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {descriptor && descriptor.status !== "production" ? (
            <span
              className="wb-mono"
              data-testid={`platform-capability-pill-${install.platform}`}
              // Capability honesty per CLAUDE.md §3 — the descriptor's
              // statusNote carries the per-platform caveat (Baileys ToS
              // for WhatsApp, etc.) and surfaces here as a hover tooltip.
              title={descriptor.statusNote}
              style={{
                fontSize: 9,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-sepia-warning-deep)",
                border: "1px solid var(--wb-color-sepia-warning-deep)",
                padding: "1px 5px",
                cursor: "help",
              }}
            >
              {descriptor.status === "preview" ? "preview" : "coming soon"}
            </span>
          ) : null}
          {install.platform === "whatsapp" ? (
            <span
              className="wb-mono"
              data-testid={`platform-pairing-${install.platform}`}
              style={chipStyle(
                statusTone(pairing === "paired" ? "active" : "archived"),
              )}
            >
              {pairing}
            </span>
          ) : (
            <span
              className="wb-mono"
              data-testid={`platform-status-${install.platform}`}
              style={chipStyle(statusTone(install.status === "active" ? "active" : "archived"))}
            >
              {install.status}
            </span>
          )}
        </div>
      </header>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          rowGap: 4,
          columnGap: 8,
          fontSize: 11,
        }}
      >
        <dt
          className="wb-mono"
          style={{
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          installer
        </dt>
        <dd style={{ margin: 0, fontFamily: "var(--wb-font-serif)" }}>
          {install.installerName ?? install.installerPersonId ?? "—"}
        </dd>
        <dt
          className="wb-mono"
          style={{
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          installed
        </dt>
        <dd
          className="wb-mono"
          style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
        >
          {install.installedAt}
        </dd>
        {install.botUserId ? (
          <>
            <dt
              className="wb-mono"
              style={{
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              bot
            </dt>
            <dd
              className="wb-mono"
              style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
            >
              {install.botUserId}
            </dd>
          </>
        ) : null}
        {install.scopes.length > 0 ? (
          <>
            <dt
              className="wb-mono"
              style={{
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              scopes
            </dt>
            <dd
              className="wb-mono"
              style={{
                margin: 0,
                color: "var(--wb-color-aged-ink)",
                fontSize: 10,
              }}
            >
              {install.scopes.join(", ")}
            </dd>
          </>
        ) : null}
      </dl>
      <CapabilityChips
        platform={install.platform}
        descriptor={descriptor}
      />
      <Receipt
        hash={install.receipt.hash}
        source={install.receipt.source}
        owner={install.receipt.owner}
        classification={install.receipt.classification}
        compact
      />
    </article>
  );
}

/**
 * W3-A (2026-05-07) — capability chips cascade.
 *
 * Renders a small chip per capability declared by the descriptor's
 * optional ``capabilities`` field. Platforms whose descriptor omits the
 * field render nothing — Slack/Discord/Teams/Signal stay byte-identical
 * until they opt in. Each chip carries a per-(platform, capability)
 * tooltip explaining the gate.
 */
function CapabilityChips({
  platform,
  descriptor,
}: {
  platform: string;
  descriptor: PlatformDescriptor | null;
}) {
  if (
    !descriptor ||
    !descriptor.capabilities ||
    descriptor.capabilities.length === 0
  ) {
    return null;
  }
  return (
    <div
      data-testid={`platform-capability-chips-${platform}`}
      style={{ display: "flex", gap: 4, flexWrap: "wrap" }}
    >
      {descriptor.capabilities.map((cap) => (
        <span
          key={cap}
          className="wb-mono"
          data-testid={`platform-capability-chip-${platform}-${cap}`}
          data-capability={cap}
          title={tooltipForCapability(descriptor.platform, cap)}
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
            border: "1px solid var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-deep)",
            padding: "1px 5px",
            cursor: "help",
          }}
        >
          {cap}
        </span>
      ))}
    </div>
  );
}
