/**
 * Phase D3 — SyncHistoryPanel component tests.
 *
 * Pins:
 *   - empty state per CLAUDE.md §9 ("No sync history yet — sync entries…")
 *   - one row per sync, sorted in input order (the accessor sorts; the panel
 *     renders as-given)
 *   - status chip color/label per status enum
 *   - click-through href has the correct ?history_sync_id param
 *   - active sync (current filter) is marked data-active=true
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SyncHistoryPanel } from "../../components/channels/SyncHistoryPanel";
import type { ConversationSyncRow } from "../../lib/ledger-client.types";

const CHANNEL = "5511999998888@s.whatsapp.net";
const SYNC_A = "11111111-1111-1111-1111-111111111111";
const SYNC_B = "22222222-2222-2222-2222-222222222222";
const SYNC_C = "33333333-3333-3333-3333-333333333333";

function row(
  syncId: string,
  status: ConversationSyncRow["status"],
  trigger: ConversationSyncRow["trigger"] = "reconnect",
  overrides: Partial<ConversationSyncRow> = {},
): ConversationSyncRow {
  return {
    syncId,
    platform: "whatsapp",
    installId: "inst-1",
    channelIds: [CHANNEL],
    trigger,
    startedAt: "2026-05-06T19:30:00.000Z",
    completedAt:
      status === "in_progress" ? null : "2026-05-06T19:31:00.000Z",
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
    ...overrides,
  };
}

describe("SyncHistoryPanel", () => {
  it("renders the empty state when no syncs are folded", () => {
    render(<SyncHistoryPanel channelId={CHANNEL} syncs={[]} />);
    const empty = screen.getByTestId("sync-history-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.textContent).toMatch(/No sync history yet/);
    expect(empty.textContent).toMatch(/reconnects to WhatsApp/);
  });

  it("renders one row per sync with the expected metadata", () => {
    render(
      <SyncHistoryPanel
        channelId={CHANNEL}
        syncs={[
          row(SYNC_A, "completed"),
          row(SYNC_B, "interrupted", "initial_connect"),
          row(SYNC_C, "in_progress", "channel_join"),
        ]}
      />,
    );
    expect(screen.getByTestId(`sync-history-row-${SYNC_A}`)).toBeInTheDocument();
    expect(screen.getByTestId(`sync-history-row-${SYNC_B}`)).toBeInTheDocument();
    expect(screen.getByTestId(`sync-history-row-${SYNC_C}`)).toBeInTheDocument();
    // Trigger labels.
    expect(
      screen.getByTestId(`sync-history-trigger-${SYNC_A}`).textContent,
    ).toBe("reconnect");
    expect(
      screen.getByTestId(`sync-history-trigger-${SYNC_B}`).textContent,
    ).toBe("initial connect");
    expect(
      screen.getByTestId(`sync-history-trigger-${SYNC_C}`).textContent,
    ).toBe("channel join");
  });

  it("renders 'in progress' for completedAt when a sync is still active", () => {
    render(
      <SyncHistoryPanel
        channelId={CHANNEL}
        syncs={[row(SYNC_A, "in_progress")]}
      />,
    );
    expect(
      screen.getByTestId(`sync-history-completed-${SYNC_A}`).textContent,
    ).toBe("in progress");
  });

  it("status chip surfaces the right enum label per status", () => {
    render(
      <SyncHistoryPanel
        channelId={CHANNEL}
        syncs={[
          row(SYNC_A, "completed"),
          row(SYNC_B, "interrupted"),
          row(SYNC_C, "in_progress"),
        ]}
      />,
    );
    expect(
      screen.getByTestId(`sync-history-status-${SYNC_A}`).textContent,
    ).toBe("completed");
    expect(
      screen.getByTestId(`sync-history-status-${SYNC_B}`).textContent,
    ).toBe("interrupted");
    expect(
      screen.getByTestId(`sync-history-status-${SYNC_C}`).textContent,
    ).toBe("in progress");
    expect(
      screen
        .getByTestId(`sync-history-status-${SYNC_C}`)
        .getAttribute("data-status"),
    ).toBe("in_progress");
  });

  it("filter link points at the channel detail page with history_sync_id param", () => {
    render(
      <SyncHistoryPanel
        channelId={CHANNEL}
        syncs={[row(SYNC_A, "completed")]}
      />,
    );
    const link = screen.getByTestId(
      `sync-history-filter-${SYNC_A}`,
    ) as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain(`/channels/${encodeURIComponent(CHANNEL)}`);
    expect(href).toContain(`history_sync_id=${SYNC_A}`);
  });

  it("marks the active sync row with data-active=true", () => {
    render(
      <SyncHistoryPanel
        channelId={CHANNEL}
        syncs={[row(SYNC_A, "completed"), row(SYNC_B, "completed")]}
        activeSyncId={SYNC_B}
      />,
    );
    expect(
      screen
        .getByTestId(`sync-history-row-${SYNC_A}`)
        .getAttribute("data-active"),
    ).toBe("false");
    expect(
      screen
        .getByTestId(`sync-history-row-${SYNC_B}`)
        .getAttribute("data-active"),
    ).toBe("true");
  });

  it("preserves the input order (sorting is the accessor's job)", () => {
    // Pass syncs in a non-sorted order; the panel should render in the
    // order it received them. The accessor (`getConversationSyncs`)
    // already sorts; the panel doesn't re-sort.
    const a = row(SYNC_A, "completed", "reconnect", {
      startedAt: "2026-05-06T08:00:00.000Z",
    });
    const b = row(SYNC_B, "completed", "reconnect", {
      startedAt: "2026-05-06T20:00:00.000Z",
    });
    render(<SyncHistoryPanel channelId={CHANNEL} syncs={[b, a]} />);
    const rows = screen
      .getAllByTestId(/^sync-history-row-/)
      .map((r) => r.getAttribute("data-testid"));
    expect(rows[0]).toBe(`sync-history-row-${SYNC_B}`);
    expect(rows[1]).toBe(`sync-history-row-${SYNC_A}`);
  });
});
