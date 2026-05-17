/**
 * RecentSyncsPanel — Phase D3 cross-channel "Recent syncs" mini-panel.
 *
 * Renders the N most-recent `conversation_sync` entries across every
 * channel. Helps surface "system pulse" without needing to drill into each
 * channel detail page. Each row links to that channel's detail page with
 * the `?history_sync_id=<sync_id>` filter applied.
 *
 * Reads only ledger projections per CLAUDE.md §1. Empty state per
 * CLAUDE.md §9: when no syncs exist anywhere, the panel surfaces a quiet
 * dashed-border note rather than rendering nothing.
 */
import Link from "next/link";
import { chipStyle, type ChipTone } from "../people/_styles";
import { formatChannelDisplay } from "../../lib/whatsapp-display";
import type {
  ConversationSyncRow,
  ConversationSyncStatus,
  ChannelRow,
} from "../../lib/ledger-client.types";

interface Props {
  syncs: ConversationSyncRow[];
  /** Channel registry — used to resolve display names for jids / Slack ids. */
  channels: ChannelRow[];
  /** Cap how many rows render. Defaults to 5 per the plan. */
  limit?: number;
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

export function RecentSyncsPanel({ syncs, channels, limit = 5 }: Props) {
  if (syncs.length === 0) {
    return (
      <section
        data-testid="recent-syncs-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: 14,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
          fontSize: 13,
        }}
      >
        No sync sessions yet — once the worm reconnects to any channel
        platform, the most-recent reconnects surface here.
      </section>
    );
  }

  const channelById = new Map(channels.map((c) => [c.channelId, c] as const));
  // Already sorted descending by `started_at` from `getConversationSyncs`.
  const rows = syncs.slice(0, limit);

  return (
    <section
      data-testid="recent-syncs-panel"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
      }}
    >
      <ol
        data-testid="recent-syncs-list"
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {rows.map((s) => {
          // A sync may touch multiple channels; pick the first id and link
          // there with the sync filter applied. The detail page surfaces
          // the full channel list inside the row anyway.
          const targetChannelId =
            s.channelIds[0] ?? `unknown-${s.syncId.slice(0, 8)}`;
          const channel = channelById.get(targetChannelId) ?? null;
          const display = formatChannelDisplay(
            targetChannelId,
            channel?.platform ?? s.platform,
            channel?.name ?? null,
          );
          const href =
            s.channelIds.length > 0
              ? `/channels/${encodeURIComponent(
                  targetChannelId,
                )}?history_sync_id=${encodeURIComponent(s.syncId)}`
              : `/channels`;
          return (
            <li
              key={s.syncId}
              data-testid={`recent-syncs-row-${s.syncId}`}
              data-status={s.status}
              data-platform={s.platform}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto",
                alignItems: "center",
                gap: 12,
                padding: "10px 14px",
                borderBottom: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <Link
                href={href}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  textDecoration: "none",
                  color: "inherit",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 14,
                  }}
                >
                  {display.label}
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    color: "var(--wb-color-hash-gray)",
                    textTransform: "uppercase",
                  }}
                >
                  {s.platform} · {s.trigger.replace("_", " ")} ·{" "}
                  {s.messageCount} msg
                </span>
              </Link>
              <span
                className="wb-mono"
                style={{
                  fontSize: 11,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {s.startedAt
                  .replace("T", " ")
                  .replace(/\.\d+Z$/, "Z")
                  .slice(0, 16)}
              </span>
              <span
                data-testid={`recent-syncs-status-${s.syncId}`}
                style={chipStyle(STATUS_TONE[s.status])}
              >
                {STATUS_LABEL[s.status]}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
