import { Receipt } from "../../lib/receipts";
import type { ConversationMessage } from "../../lib/ledger-client.types";

/**
 * ConversationsFeed — Field-Notebook transcript style. Explicitly NOT chat-bubble:
 * each entry is a single text line preceded by a mono channel·author·ts prefix,
 * with a Receipt below proving it's part of the ledger.
 */
export function ConversationsFeed({
  messages,
}: {
  messages: ConversationMessage[];
}) {
  if (messages.length === 0) {
    return (
      <p
        data-testid="conversations-feed-empty"
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No messages captured yet. The worm starts ingesting as soon as it joins
        a channel — connect a chat platform on /channels to begin building the
        conversation lake.
      </p>
    );
  }
  return (
    <ol
      data-testid="conversations-feed"
      style={{
        padding: 0,
        margin: 0,
        listStyle: "none",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {messages.map((m, i) => (
        <li
          key={i}
          data-testid={`conversation-${i}`}
          style={{
            display: "grid",
            gridTemplateColumns: "260px 1fr 280px",
            gap: 16,
            padding: "8px 0",
            borderBottom: "1px solid var(--wb-color-paper-edge)",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray)",
              letterSpacing: "0.02em",
            }}
          >
            {m.ts} · {m.channel} · {m.author}
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 14,
              lineHeight: 1.55,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {m.text}
          </span>
          <Receipt
            hash={m.receipt.hash}
            source={m.receipt.source}
            owner={m.receipt.owner}
            classification={m.receipt.classification}
            compact
          />
        </li>
      ))}
    </ol>
  );
}
