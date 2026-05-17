/**
 * /channels — top-level channels surface.
 *
 * D3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Sections:
 *   - InstalledPlatforms — one card per `Install` (folded from
 *     `emit_install_completed` / `emit_install_revoked`).
 *   - WhatsAppEmptyState — visible per CLAUDE.md §9 when no WhatsApp
 *     install row exists yet (Phase D1, 2026-05-06). Silent panels
 *     are demo seams disguised as design; the operator must see the
 *     pairing affordance regardless of whether they paired yet.
 *   - ChannelRoster — the existing per-channel talkativeness dial.
 *   - ConnectPlatformButtons — Slack ready; Discord/Teams/WhatsApp ship
 *     preview; Signal coming_soon.
 */
import {
  getChannels,
  getConversationSyncs,
  getInstalls,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { InstalledPlatforms } from "../../../components/channels/InstalledPlatforms";
import { ChannelRoster } from "../../../components/channels/ChannelRoster";
import { ConnectPlatformButtons } from "../../../components/channels/ConnectPlatformButtons";
import { WhatsAppEmptyState } from "../../../components/channels/WhatsAppEmptyState";
import { RecentSyncsPanel } from "../../../components/channels/RecentSyncsPanel";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Channels" };

export default async function ChannelsPage() {
  const companyId = await getCurrentCompanyId();
  const [installs, channels, recentSyncs] = await Promise.all([
    getInstalls(companyId),
    getChannels(companyId),
    // Phase D3 — cross-channel "Recent syncs" mini-panel feeds off the same
    // conversation_sync projection the per-channel detail page reads.
    // Fetched here at the top so the most-recent reconnects surface
    // without operators having to drill into each channel.
    getConversationSyncs(companyId),
  ]);
  // Phase D1 — surface a visible WhatsApp empty state when no whatsapp
  // install exists yet. The pairing-status vocabulary surfaces inside
  // PlatformCard when an install row IS present; this empty state covers
  // the "before pairing" surface so operators always see the QR-pairing
  // affordance (CLAUDE.md §9 — no silent panels).
  const hasWhatsApp = installs.some((i) => i.platform === "whatsapp");

  return (
    <PageBoundary surface="channels" traceQuery="?surface=channels">
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. X · Channels
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Channels · {channels.length}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          One card per platform install. Per-channel talkativeness — lurker,
          responsive, proactive — writes a{" "}
          <span className="wb-mono">policy_applied</span> ledger entry on
          every change.
        </p>
      </header>

      <section
        aria-label="connected platforms"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          connected platforms · {installs.length}
        </span>
        <InstalledPlatforms installs={installs} />
        {hasWhatsApp ? null : <WhatsAppEmptyState />}
      </section>

      <section
        aria-label="channel roster"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          channel roster · {channels.length}
        </span>
        <ChannelRoster channels={channels} />
      </section>

      <section
        aria-label="recent syncs"
        data-testid="channels-recent-syncs"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          recent syncs · {Math.min(recentSyncs.length, 5)}
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          The five most-recent <span className="wb-mono">conversation_sync</span>{" "}
          PEVR cycles across every channel. Click a row to drill into that
          session's per-channel chat history.
        </p>
        <RecentSyncsPanel syncs={recentSyncs} channels={channels} />
      </section>

      <ConnectPlatformButtons />
    </PageBoundary>
  );
}
