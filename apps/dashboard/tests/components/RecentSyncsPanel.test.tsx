/**
 * Phase D3 — RecentSyncsPanel cross-channel mini-panel tests.
 *
 * Pins:
 *   - empty state per CLAUDE.md §9
 *   - caps at 5 rows by default
 *   - link href routes to the per-channel detail page with the sync filter
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { RecentSyncsPanel } from "../../components/channels/RecentSyncsPanel";
import type {
  ChannelRow,
  ConversationSyncRow,
} from "../../lib/ledger-client.types";

const CHANNEL = "5511999998888@s.whatsapp.net";

function syncRow(
  syncId: string,
  status: ConversationSyncRow["status"] = "completed",
  channelId: string = CHANNEL,
): ConversationSyncRow {
  return {
    syncId,
    platform: "whatsapp",
    installId: "inst-1",
    channelIds: [channelId],
    trigger: "reconnect",
    startedAt: "2026-05-06T19:30:00.000Z",
    completedAt: "2026-05-06T19:31:00.000Z",
    messageCount: 50,
    earliestTs: "2026-05-06T18:00:00.000Z",
    latestTs: "2026-05-06T19:29:00.000Z",
    status,
    receipt: {
      hash: "abcdef0123456789",
      source: "conversation-sync-projection",
      owner: "channel-adapter",
      classification: "internal",
    },
  };
}

const CHANNELS: ChannelRow[] = [
  {
    channelId: CHANNEL,
    name: CHANNEL,
    talkativeness: "lurker",
    lastPolicyHash: "abcd1234",
    platform: "whatsapp",
    receipt: {
      hash: "abcd1234",
      source: "channel-policy-v1",
      owner: "system",
      classification: "internal",
    },
  },
];

describe("RecentSyncsPanel", () => {
  it("renders the empty state when no syncs exist", () => {
    render(<RecentSyncsPanel syncs={[]} channels={[]} />);
    const empty = screen.getByTestId("recent-syncs-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.textContent).toMatch(/No sync sessions yet/);
  });

  it("caps at 5 rows by default", () => {
    const syncs = Array.from({ length: 8 }, (_, i) =>
      syncRow(`${i}1111111-1111-1111-1111-111111111111`.slice(0, 36)),
    );
    render(<RecentSyncsPanel syncs={syncs} channels={CHANNELS} />);
    const rows = screen.getAllByTestId(/^recent-syncs-row-/);
    expect(rows.length).toBe(5);
  });

  it("respects a custom limit", () => {
    const syncs = Array.from({ length: 8 }, (_, i) =>
      syncRow(`${i}1111111-1111-1111-1111-111111111111`.slice(0, 36)),
    );
    render(<RecentSyncsPanel syncs={syncs} channels={CHANNELS} limit={3} />);
    expect(screen.getAllByTestId(/^recent-syncs-row-/).length).toBe(3);
  });

  it("each row routes to the per-channel detail page with the sync filter", () => {
    const syncId = "11111111-1111-1111-1111-111111111111";
    render(
      <RecentSyncsPanel
        syncs={[syncRow(syncId)]}
        channels={CHANNELS}
      />,
    );
    const row = screen.getByTestId(`recent-syncs-row-${syncId}`);
    const link = row.querySelector("a") as HTMLAnchorElement;
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain(`/channels/${encodeURIComponent(CHANNEL)}`);
    expect(href).toContain(`history_sync_id=${syncId}`);
  });
});
