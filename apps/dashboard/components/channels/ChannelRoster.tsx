/**
 * ChannelRoster — wraps the existing ChannelDial-driven talkativeness UI
 * (formerly /settings/channels). Imports the same client component so the
 * write path (`/api/channels/talkativeness`) stays unchanged.
 *
 * D3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { ChannelsClient } from "../../app/(app)/settings/channels/ChannelsClient";
import type { ChannelRow } from "../../lib/ledger-client.types";

export function ChannelRoster({ channels }: { channels: ChannelRow[] }) {
  if (channels.length === 0) {
    return (
      <section
        data-testid="channel-roster-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: 18,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No channels yet. Once a platform install lands, every channel the
        worm joins will surface here with a talkativeness dial.
      </section>
    );
  }
  return (
    <section data-testid="channel-roster">
      <ChannelsClient channels={channels} />
    </section>
  );
}
