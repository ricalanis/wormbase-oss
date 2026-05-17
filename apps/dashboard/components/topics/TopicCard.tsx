/**
 * WS5 S3 — TopicCard.
 *
 * One card per (channel, top-keyword) cluster from getTopics. Surface
 * fields:
 *   - Channel-prefixed label, e.g. "#data-eng · revenue"
 *   - Recent message count
 *   - Top participants (up to three)
 *   - Latest message excerpt (≤140 chars)
 *
 * Editorial chrome — square corners, wb-mono eyebrow + monospace counts,
 * serif excerpt. No emojis.
 */

import type { Topic } from "../../lib/ledger-client";

export interface TopicCardProps {
  topic: Topic;
}

export function TopicCard({ topic }: TopicCardProps) {
  const channelLabel = topic.channelName.startsWith("#")
    ? topic.channelName
    : `#${topic.channelName}`;
  const personChips = topic.topPersons.length > 0 ? topic.topPersons : [];

  return (
    <article
      data-testid={`topic-${topic.topicId}`}
      data-channel={topic.channelId}
      style={cardStyle}
    >
      <header style={headerStyle}>
        <span className="wb-mono" style={eyebrowStyle}>
          {channelLabel}
        </span>
        <h3 style={titleStyle} data-testid={`topic-label-${topic.topicId}`}>
          {topic.label}
        </h3>
      </header>

      <dl style={statsRowStyle}>
        <div style={statColStyle}>
          <dt className="wb-mono" style={statLabelStyle}>
            messages
          </dt>
          <dd
            className="wb-mono"
            style={statValueStyle}
            data-testid={`topic-count-${topic.topicId}`}
          >
            {topic.messageCount}
          </dd>
        </div>
        <div style={statColStyle}>
          <dt className="wb-mono" style={statLabelStyle}>
            participants
          </dt>
          <dd style={participantsStyle}>
            {personChips.length === 0 ? (
              <span style={italicMutedStyle}>none</span>
            ) : (
              personChips.map((p) => (
                <span
                  key={p}
                  className="wb-mono"
                  style={chipStyle}
                  data-testid={`topic-person-${topic.topicId}-${p}`}
                >
                  @{p.slice(0, 12)}
                </span>
              ))
            )}
          </dd>
        </div>
      </dl>

      {topic.latestExcerpt ? (
        <blockquote
          data-testid={`topic-excerpt-${topic.topicId}`}
          style={excerptStyle}
        >
          {topic.latestExcerpt}
        </blockquote>
      ) : null}
    </article>
  );
}

const cardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  padding: "18px 20px",
  margin: 0,
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 500,
  letterSpacing: "-0.005em",
  color: "var(--wb-color-aged-ink)",
};

const statsRowStyle: React.CSSProperties = {
  display: "flex",
  gap: 24,
  margin: 0,
  flexWrap: "wrap",
};

const statColStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const statLabelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const statValueStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 18,
  color: "var(--wb-color-aged-ink)",
  fontWeight: 500,
};

const participantsStyle: React.CSSProperties = {
  margin: 0,
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
};

const chipStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 6px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper-deep)",
  fontSize: 11,
  color: "var(--wb-color-aged-ink)",
};

const italicMutedStyle: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  color: "var(--wb-color-hash-gray)",
};

const excerptStyle: React.CSSProperties = {
  margin: 0,
  padding: "8px 12px",
  borderLeft: "2px solid var(--wb-color-paper-edge)",
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 13,
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
};
