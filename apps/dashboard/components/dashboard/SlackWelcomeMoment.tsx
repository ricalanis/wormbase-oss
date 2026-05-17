/**
 * WS5 S2 — In-Slack welcome moment surfaced on /dashboard.
 *
 * The most photo-friendly demo beat is when the worm posts "hi I'm here"
 * in the channel. Today that beat is OFF-screen (it lives only in Slack).
 * This component finds the worm's first ``emit_chat_sent`` entry and
 * renders it on the dashboard as a small editorial pull-quote card.
 *
 * The card looks like an editorial pull quote:
 *
 *   "Hi! I'm WormBase. I'll be in #data-eng listening for the next few days."
 *
 *                  — @WormBase, #data-eng, 2 minutes ago
 *
 * wb-mono for timestamps, serif for the quote. No emojis.
 */

import type { FirstWormMessage } from "../../lib/ledger-client";

export interface SlackWelcomeMomentProps {
  message: FirstWormMessage;
}

export function SlackWelcomeMoment({ message }: SlackWelcomeMomentProps) {
  const channelLabel = message.channelName.startsWith("#")
    ? message.channelName
    : `#${message.channelName}`;
  const relative = formatRelative(message.ts);

  return (
    <figure
      data-testid="slack-welcome-moment"
      style={cardStyle}
    >
      <span
        className="wb-mono"
        style={eyebrowStyle}
        data-testid="slack-welcome-eyebrow"
      >
        the worm said hello · {channelLabel}
      </span>
      <blockquote style={quoteStyle} data-testid="slack-welcome-quote">
        <span style={quoteMarkStyle} aria-hidden="true">
          &ldquo;
        </span>
        {message.text}
        <span style={quoteMarkStyle} aria-hidden="true">
          &rdquo;
        </span>
      </blockquote>
      <figcaption
        className="wb-mono"
        style={attributionStyle}
        data-testid="slack-welcome-attribution"
      >
        — @WormBase, {channelLabel}, {relative}
      </figcaption>
    </figure>
  );
}

/**
 * Format a timestamp as a coarse human-readable relative time. We avoid
 * the user's locale (server-rendered) and stay in editorial register —
 * "2 minutes ago", "3 hours ago", "yesterday", or fall back to ISO.
 */
function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const now = Date.now();
  const deltaMs = now - d.valueOf();
  if (deltaMs < 0) return iso;
  const seconds = Math.floor(deltaMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  // Older — fall back to a compact UTC date.
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

const cardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  padding: "20px 24px",
  margin: 0,
  border: "1px solid var(--wb-color-paper-edge)",
  borderLeft: "3px solid var(--wb-color-botanical-green-deep)",
  background: "var(--wb-color-paper)",
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const quoteStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 20,
  lineHeight: 1.45,
  fontStyle: "italic",
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.005em",
};

const quoteMarkStyle: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: 24,
  color: "var(--wb-color-botanical-green-deep)",
  fontStyle: "normal",
  margin: "0 4px",
};

const attributionStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--wb-color-hash-gray)",
  letterSpacing: "0.04em",
};
