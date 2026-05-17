/**
 * /channels/[id] — per-channel detail surface (Phase D3, 2026-05-06).
 *
 * Three sections:
 *   1. Header — formatted channel display name (slack/whatsapp via the D1
 *      `whatsapp-display` helper), platform chip, and "back to /channels".
 *   2. SyncHistoryPanel — `conversation_sync` PEVR cycles for this channel
 *      (Phase D3). Click-through filters the chat history by `history_sync_id`.
 *   3. ChannelChatHistory — `chat_received` rows for the channel; when the
 *      page is loaded with `?history_sync_id=<sync_id>` the list is filtered
 *      to messages folded by that one session, with a clear-filter affordance
 *      that returns to the unfiltered view.
 *
 * Reads only ledger projections per CLAUDE.md §1. Empty states per
 * CLAUDE.md §9: a channel with no conversation_sync entries shows the
 * "no sync history yet" panel; a chat history with no messages shows the
 * existing ConversationsFeed empty state. Read-only — no admin gating
 * needed; all roles see this surface.
 */
import Link from "next/link";
import {
  getChannels,
  getChatReceivedForChannel,
  getConversationSyncs,
} from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { formatChannelDisplay } from "../../../../lib/whatsapp-display";
import { SyncHistoryPanel } from "../../../../components/channels/SyncHistoryPanel";
import { RateLimitStatusPanel } from "../../../../components/channels/RateLimitStatusPanel";
import { ConversationsFeed } from "../../../../components/activity/ConversationsFeed";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { EmptyState } from "../../../../components/chrome/EmptyState";

export const metadata = { title: "WormBase · Channel" };
export const dynamic = "force-dynamic";

interface ChannelDetailPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ChannelDetailPage({
  params,
  searchParams,
}: ChannelDetailPageProps) {
  const { id: rawId } = await params;
  const sp = await searchParams;
  const channelId = decodeURIComponent(rawId);
  const companyId = await getCurrentCompanyId();

  const historySyncIdParam = sp["history_sync_id"];
  const historySyncId = Array.isArray(historySyncIdParam)
    ? historySyncIdParam[0]
    : historySyncIdParam ?? undefined;

  const [channels, syncs, messages] = await Promise.all([
    getChannels(companyId),
    getConversationSyncs(companyId, channelId),
    getChatReceivedForChannel(companyId, channelId, {
      historySyncId,
      limit: 50,
    }),
  ]);

  const channel = channels.find((c) => c.channelId === channelId) ?? null;
  // No channel registered yet AND no chat_received rows → likely an unknown
  // id pasted directly. Surface an honest empty state pointing back to
  // the roster rather than a silent 404.
  if (!channel && syncs.length === 0 && messages.length === 0) {
    return (
      <PageBoundary
        surface="channel-detail"
        traceQuery={`?surface=channels&channel_id=${encodeURIComponent(
          channelId,
        )}`}
      >
        <EmptyState
          testId="channel-detail-not-found"
          eyebrow="channel not found"
          title={`No channel data for ${channelId.slice(0, 32)}…`}
          description={
            "The worm hasn't seen this channel yet — no chat_received and " +
            "no conversation_sync entries are folded for it. Check the " +
            "channel roster on /channels for the canonical list."
          }
          cta={{ label: "Back to Channels", href: "/channels" }}
        />
      </PageBoundary>
    );
  }

  const display = formatChannelDisplay(
    channelId,
    channel?.platform,
    channel?.name ?? null,
  );
  const platformLabel = channel?.platform ?? display.kind ?? "channel";
  const activeSync = historySyncId
    ? syncs.find((s) => s.syncId === historySyncId) ?? null
    : null;

  return (
    <PageBoundary
      surface="channel-detail"
      traceQuery={`?surface=channels&channel_id=${encodeURIComponent(
        channelId,
      )}`}
    >
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
          channel · {platformLabel}
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
          data-testid="channel-detail-title"
        >
          {display.label}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {display.hint}
          {channel?.talkativeness ? ` · ${channel.talkativeness}` : ""}
          {channel?.lastSeenAt ? ` · last seen ${formatTs(channel.lastSeenAt)}` : ""}
        </p>
        <div style={{ marginTop: 6 }}>
          <Link
            href="/channels"
            data-testid="channel-detail-back"
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
              letterSpacing: "0.04em",
            }}
          >
            ← back to channels
          </Link>
        </div>
      </header>

      <section
        aria-label="sync history"
        data-testid="sync-history-section"
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
          sync history · {syncs.length}
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
          One row per platform reconnect / initial-connect / channel-join.
          Click <span className="wb-mono">filter chat →</span> to scope the
          message list below to that session.
        </p>
        <SyncHistoryPanel
          channelId={channelId}
          syncs={syncs}
          activeSyncId={historySyncId ?? null}
        />
      </section>

      {channel?.platform === "whatsapp" ? (
        <RateLimitStatusPanel
          companyId={companyId}
          channelId={channelId}
          platform={channel.platform}
        />
      ) : null}

      <section
        aria-label="chat history"
        data-testid="channel-chat-history-section"
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
          chat history · {messages.length}
        </span>
        {activeSync ? (
          <FilterBanner
            channelId={channelId}
            startedAt={activeSync.startedAt}
            trigger={activeSync.trigger}
            messageCount={messages.length}
          />
        ) : null}
        <ConversationsFeed messages={messages} />
      </section>
    </PageBoundary>
  );
}

function FilterBanner({
  channelId,
  startedAt,
  trigger,
  messageCount,
}: {
  channelId: string;
  startedAt: string;
  trigger: string;
  messageCount: number;
}) {
  const tsLabel = startedAt.replace("T", " ").replace(/\.\d+Z$/, "Z");
  return (
    <div
      data-testid="channel-chat-history-filter-banner"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper-deep)",
        padding: "10px 12px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <span
        className="wb-mono"
        style={{ fontSize: 12, color: "var(--wb-color-aged-ink)" }}
      >
        Showing {messageCount} message{messageCount === 1 ? "" : "s"} from
        sync started {tsLabel} ({trigger.replace("_", " ")})
      </span>
      <Link
        href={`/channels/${encodeURIComponent(channelId)}`}
        data-testid="channel-chat-history-clear-filter"
        style={{
          fontFamily: "var(--wb-font-mono)",
          fontSize: 11,
          color: "var(--wb-color-botanical-green-deep)",
          textDecoration: "none",
          letterSpacing: "0.04em",
        }}
      >
        clear filter ×
      </Link>
    </div>
  );
}

function formatTs(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 20);
}
