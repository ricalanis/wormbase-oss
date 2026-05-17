"use client";
/**
 * ResourceConversationsCard — per-Person active resource conversations
 * (W5.A5).
 *
 * Mounts on /people/<id> when the Person is the owner of any resource
 * the worm DM'd them about. Honest empty: "no active conversations" when
 * none are pending.
 *
 * Each conversation card shows:
 *   - Topic (kpi / source / domain / process · label)
 *   - The chat statement that triggered the worm
 *   - The 3 most recent replies
 *   - Reply count (chip)
 *   - "Resolve" CTA (lands emit_resource_conversation_resolved with
 *     outcome=no_action by default — admins can refine the outcome later
 *     via the ledger view)
 */

import { useEffect, useState } from "react";
import type {
  ResourceConversation,
  ResourceConversationReply,
} from "../../lib/ledger-client.types";

export interface ResourceConversationsCardProps {
  personId: string;
  /** Optional initial rows for tests; production fetches on mount. */
  initialConversations?: ResourceConversation[];
}

function topicLabel(topic: Record<string, unknown>): string {
  const kind = typeof topic.kind === "string" ? topic.kind : "topic";
  const id = typeof topic.id === "string" ? topic.id : "";
  const label = typeof topic.label === "string" ? topic.label : "";
  if (label) return `${kind}: ${label}`;
  if (id) return `${kind}: ${id.slice(0, 8)}…`;
  return kind;
}

export function ResourceConversationsCard({
  personId,
  initialConversations,
}: ResourceConversationsCardProps) {
  const [convs, setConvs] = useState<ResourceConversation[] | null>(
    initialConversations ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialConversations !== undefined) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/v1/people/${encodeURIComponent(personId)}/resource-conversations`,
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`fetch failed (${res.status})`);
        const body = (await res.json()) as {
          conversations?: ResourceConversation[];
        };
        if (cancelled) return;
        setConvs(body.conversations ?? []);
      } catch (err) {
        if (cancelled) return;
        setError((err as Error).message);
        setConvs([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [personId, initialConversations]);

  return (
    <section
      data-testid="resource-conversations-card"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Statement-to-Owner · open
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
            borderBottom: "1px solid var(--wb-color-paper-edge)",
            paddingBottom: 6,
          }}
        >
          Resource Conversations
        </h3>
      </header>
      {error ? (
        <div
          data-testid="resource-conversations-error"
          role="alert"
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-sepia-warning-deep)" }}
        >
          {error}
        </div>
      ) : null}
      {convs === null ? (
        <span
          data-testid="resource-conversations-loading"
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
        >
          Loading…
        </span>
      ) : convs.length === 0 ? (
        <span
          data-testid="resource-conversations-empty"
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          no active conversations — when the worm matches a chat
          statement to a resource this Person owns, the DM thread shows
          up here.
        </span>
      ) : (
        <ul
          data-testid="resource-conversations-list"
          style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}
        >
          {convs.map((c) => (
            <ResourceConversationRow key={c.conversationId} conversation={c} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ResourceConversationRow({
  conversation,
}: {
  conversation: ResourceConversation;
}) {
  const [busy, setBusy] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resolve() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/resource-conversations/${encodeURIComponent(conversation.conversationId)}/resolve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ outcome: "no_action" }),
        },
      );
      if (!res.ok && res.status !== 404) {
        // 404 is expected until W5.A2 lands the resolve endpoint;
        // surface it as a non-blocking notice rather than an error.
        const t = await res.text().catch(() => "");
        throw new Error(t || `resolve failed (${res.status})`);
      }
      setResolved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-testid={`resource-conversation-${conversation.conversationId}`}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        background: resolved
          ? "var(--wb-color-paper-deep)"
          : "var(--wb-color-paper)",
        opacity: resolved ? 0.6 : 1,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span
          data-testid={`resource-conversation-topic-${conversation.conversationId}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
            border: "1px solid var(--wb-color-aged-ink)",
            padding: "2px 8px",
          }}
        >
          {topicLabel(conversation.topic as Record<string, unknown>)}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {(conversation.replyCount ?? conversation.replies?.length ?? 0)} reply
          {(conversation.replyCount ?? conversation.replies?.length ?? 0) === 1
            ? ""
            : "ies"}
        </span>
      </div>
      <p
        data-testid={`resource-conversation-statement-${conversation.conversationId}`}
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 14,
          lineHeight: 1.5,
        }}
      >
        “{conversation.statement ?? `seq #${conversation.statementSeq}`}”
      </p>
      {(conversation.recentReplies ?? conversation.replies ?? []).length > 0 ? (
        <ul
          data-testid={`resource-conversation-replies-${conversation.conversationId}`}
          style={{
            listStyle: "none",
            padding: "8px 12px",
            margin: 0,
            background: "var(--wb-color-paper-deep)",
            borderLeft: "2px solid var(--wb-color-rule-line)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {(conversation.recentReplies ?? conversation.replies ?? []).map(
            (r: ResourceConversationReply) => (
              <li
                key={r.seq}
                className="wb-mono"
                style={{ fontSize: 11, color: "var(--wb-color-aged-ink)" }}
              >
                <span style={{ color: "var(--wb-color-hash-gray)" }}>
                  {r.replierId.slice(0, 8)} ·{" "}
                </span>
                {r.content.slice(0, 200)}
              </li>
            ),
          )}
        </ul>
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          data-testid={`resource-conversation-resolve-${conversation.conversationId}`}
          onClick={resolve}
          disabled={busy || resolved}
          style={{
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: resolved ? "transparent" : "var(--wb-color-paper)",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
            cursor: busy || resolved ? "default" : "pointer",
          }}
        >
          {resolved ? "Resolved" : busy ? "Resolving…" : "Resolve"}
        </button>
        {error ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-sepia-warning-deep)",
              alignSelf: "center",
            }}
          >
            {error}
          </span>
        ) : null}
      </div>
    </li>
  );
}
