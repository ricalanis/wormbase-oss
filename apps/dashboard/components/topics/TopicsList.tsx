/**
 * WS5 S3 — TopicsList.
 *
 * Pure list-of-cards. Each Topic is rendered by TopicCard; ordering is
 * dictated by the upstream getTopics (message-count desc).
 *
 * Empty state is rendered by the page itself, not here, so this component
 * can stay a pure presentational list.
 */

import type { Topic } from "../../lib/ledger-client";
import { TopicCard } from "./TopicCard";

export interface TopicsListProps {
  topics: Topic[];
}

export function TopicsList({ topics }: TopicsListProps) {
  return (
    <section
      data-testid="topics-list"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 16,
      }}
    >
      {topics.map((t) => (
        <TopicCard key={t.topicId} topic={t} />
      ))}
    </section>
  );
}
