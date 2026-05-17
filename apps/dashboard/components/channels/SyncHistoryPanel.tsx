/**
 * SyncHistoryPanel — Phase D3 (WhatsApp first-class).
 *
 * Renders the `conversation_sync` history for a single channel. Each row is
 * one PEVR cycle written by `LedgerWriter.emit_conversation_sync` (channel
 * platform reconnect / initial-connect / channel-join). Sorted descending
 * by `started_at` so the most-recent session is always at the top.
 *
 * Click-through: each row is a Link to the same channel-detail page with a
 * `?history_sync_id=<sync_id>` query param. The `ChannelChatHistory`
 * component reads that param and filters its `chat_received` list to the
 * messages folded by that one session.
 *
 * Reads only ledger projections per CLAUDE.md §1 — the rows arrive
 * pre-folded from `getConversationSyncs`. No fixture loads, no shortcut
 * paths.
 *
 * Empty-state per CLAUDE.md §9: when the projection returns `[]` the panel
 * surfaces a visible "no sync history yet" panel rather than rendering
 * nothing.
 *
 * Status chip vocabulary mirrors ConversationSyncPayload.status:
 *   - `completed`   → green
 *   - `interrupted` → sepia (warning)
 *   - `in_progress` → ink (active) with subtle pulse
 */
import Link from "next/link";
import { chipStyle, type ChipTone } from "../people/_styles";
import type {
  ConversationSyncRow,
  ConversationSyncStatus,
  ConversationSyncTrigger,
} from "../../lib/ledger-client.types";

interface Props {
  channelId: string;
  syncs: ConversationSyncRow[];
  /** When set, the row matching this sync_id is highlighted. */
  activeSyncId?: string | null;
}

const STATUS_TONE: Record<ConversationSyncStatus, ChipTone> = {
  completed: "green",
  interrupted: "sepia",
  in_progress: "ink",
};

const STATUS_LABEL: Record<ConversationSyncStatus, string> = {
  completed: "completed",
  interrupted: "interrupted",
  in_progress: "in progress",
};

const TRIGGER_LABEL: Record<ConversationSyncTrigger, string> = {
  initial_connect: "initial connect",
  reconnect: "reconnect",
  channel_join: "channel join",
};

function formatTs(iso: string | null): string {
  if (!iso) return "—";
  // Same shape as the rest of the field-notebook chrome: ISO with a space
  // separator between date and time. Truncate to seconds; the operator
  // doesn't need millisecond precision.
  return iso.replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 20);
}

export function SyncHistoryPanel({ channelId, syncs, activeSyncId }: Props) {
  if (syncs.length === 0) {
    return (
      <section
        data-testid="sync-history-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: 18,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No sync history yet — sync entries land when the worm reconnects to
        WhatsApp.
      </section>
    );
  }

  return (
    <section
      data-testid="sync-history-panel"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <table
        data-testid="sync-history-table"
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontFamily: "var(--wb-font-serif)",
        }}
      >
        <thead>
          <tr
            style={{
              borderBottom: "1px solid var(--wb-color-aged-ink)",
              fontFamily: "var(--wb-font-mono)",
              textTransform: "uppercase",
              fontSize: 10,
              letterSpacing: "0.12em",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            <th style={cellStyle("left", true)}>trigger</th>
            <th style={cellStyle("left", true)}>started</th>
            <th style={cellStyle("left", true)}>completed</th>
            <th style={cellStyle("right", true)}>messages</th>
            <th style={cellStyle("left", true)}>status</th>
            <th style={cellStyle("right", true)}> </th>
          </tr>
        </thead>
        <tbody>
          {syncs.map((s) => {
            const isActive = activeSyncId === s.syncId;
            const filterHref = `/channels/${encodeURIComponent(
              channelId,
            )}?history_sync_id=${encodeURIComponent(s.syncId)}`;
            return (
              <tr
                key={s.syncId}
                data-testid={`sync-history-row-${s.syncId}`}
                data-active={isActive ? "true" : "false"}
                data-status={s.status}
                style={{
                  borderBottom: "1px solid var(--wb-color-paper-edge)",
                  background: isActive
                    ? "var(--wb-color-paper-deep)"
                    : "transparent",
                }}
              >
                <td style={cellStyle("left")}>
                  <span
                    className="wb-mono"
                    style={{ fontSize: 12 }}
                    data-testid={`sync-history-trigger-${s.syncId}`}
                  >
                    {TRIGGER_LABEL[s.trigger]}
                  </span>
                </td>
                <td style={cellStyle("left")}>
                  <span
                    className="wb-mono"
                    style={{ fontSize: 12 }}
                    data-testid={`sync-history-started-${s.syncId}`}
                  >
                    {formatTs(s.startedAt)}
                  </span>
                </td>
                <td style={cellStyle("left")}>
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 12,
                      color:
                        s.completedAt == null
                          ? "var(--wb-color-hash-gray)"
                          : undefined,
                    }}
                    data-testid={`sync-history-completed-${s.syncId}`}
                  >
                    {s.completedAt
                      ? formatTs(s.completedAt)
                      : "in progress"}
                  </span>
                </td>
                <td style={cellStyle("right")}>
                  <span
                    className="wb-mono"
                    style={{ fontSize: 12 }}
                    data-testid={`sync-history-count-${s.syncId}`}
                  >
                    {s.messageCount}
                  </span>
                </td>
                <td style={cellStyle("left")}>
                  <StatusChip status={s.status} syncId={s.syncId} />
                </td>
                <td style={cellStyle("right")}>
                  <Link
                    href={filterHref}
                    data-testid={`sync-history-filter-${s.syncId}`}
                    style={{
                      fontFamily: "var(--wb-font-mono)",
                      fontSize: 11,
                      color: "var(--wb-color-botanical-green-deep)",
                      textDecoration: "none",
                      letterSpacing: "0.04em",
                    }}
                  >
                    filter chat →
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function StatusChip({
  status,
  syncId,
}: {
  status: ConversationSyncStatus;
  syncId: string;
}) {
  const tone = STATUS_TONE[status];
  const label = STATUS_LABEL[status];
  return (
    <span
      data-testid={`sync-history-status-${syncId}`}
      data-status={status}
      style={{
        ...chipStyle(tone),
        // The in_progress pulse is intentionally subtle — opacity oscillates
        // via the global `wb-pulse` animation registered in the dashboard's
        // base stylesheet (see app/globals.css). Falls back to a static
        // chip when the animation is absent.
        animation:
          status === "in_progress"
            ? "wb-pulse 1.6s ease-in-out infinite"
            : undefined,
      }}
    >
      {label}
    </span>
  );
}

function cellStyle(
  align: "left" | "right" | "center",
  header = false,
): React.CSSProperties {
  return {
    textAlign: align,
    padding: header ? "8px 12px" : "10px 12px",
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  };
}
