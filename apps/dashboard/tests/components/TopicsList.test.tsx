/**
 * WS5 S3 — TopicsList + TopicCard.
 *
 * Pure presentational tests over a mock Topic[] shaped like the upstream
 * getTopics fold. Empty-state rendering belongs to the page itself, not
 * to the list, so we don't test it here.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TopicsList } from "../../components/topics/TopicsList";
import { TopicCard } from "../../components/topics/TopicCard";
import type { Topic } from "../../lib/ledger-client";

const TOPICS: Topic[] = [
  {
    topicId: "C-data-eng:revenue",
    label: "revenue",
    channelId: "C-data-eng",
    channelName: "data-eng",
    messageCount: 12,
    topPersons: ["p-alice-001", "p-bob-002"],
    latestExcerpt: "should we double-check the revenue methodology before we ship?",
    latestTs: "2026-04-26T10:00:00Z",
  },
  {
    topicId: "C-finance:close",
    label: "close",
    channelId: "C-finance",
    channelName: "#finance",
    messageCount: 7,
    topPersons: ["p-carol-003"],
    latestExcerpt: "we agreed to push close to Friday.",
    latestTs: "2026-04-25T14:00:00Z",
  },
];

describe("TopicsList (WS5 S3)", () => {
  it("renders one card per Topic", () => {
    render(<TopicsList topics={TOPICS} />);
    expect(screen.getByTestId("topics-list")).toBeTruthy();
    expect(screen.getByTestId("topic-C-data-eng:revenue")).toBeTruthy();
    expect(screen.getByTestId("topic-C-finance:close")).toBeTruthy();
  });

  it("renders an empty list element when no topics", () => {
    render(<TopicsList topics={[]} />);
    const list = screen.getByTestId("topics-list");
    expect(list.children.length).toBe(0);
  });
});

describe("TopicCard (WS5 S3)", () => {
  it("shows the topic label, message count, and channel", () => {
    render(<TopicCard topic={TOPICS[0]} />);
    const card = screen.getByTestId("topic-C-data-eng:revenue");
    expect(card.textContent).toContain("revenue");
    expect(card.textContent).toContain("#data-eng");
    expect(screen.getByTestId("topic-count-C-data-eng:revenue").textContent).toBe("12");
  });

  it("renders a chip per top participant (up to three)", () => {
    render(<TopicCard topic={TOPICS[0]} />);
    expect(
      screen.getByTestId("topic-person-C-data-eng:revenue-p-alice-001"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("topic-person-C-data-eng:revenue-p-bob-002"),
    ).toBeTruthy();
  });

  it("renders the latest excerpt as a blockquote when present", () => {
    render(<TopicCard topic={TOPICS[0]} />);
    const excerpt = screen.getByTestId("topic-excerpt-C-data-eng:revenue");
    expect(excerpt.textContent).toContain("revenue methodology");
  });

  it("doesn't double-prefix the # on already-hashed channel names", () => {
    render(<TopicCard topic={TOPICS[1]} />);
    const card = screen.getByTestId("topic-C-finance:close");
    expect(card.textContent).toContain("#finance");
    expect(card.textContent).not.toContain("##");
  });

  it("renders 'none' when there are no top participants", () => {
    const topic: Topic = { ...TOPICS[0], topPersons: [] };
    render(<TopicCard topic={topic} />);
    const card = screen.getByTestId("topic-C-data-eng:revenue");
    expect(card.textContent).toContain("none");
  });

  it("hides the excerpt when there's no latest text", () => {
    const topic: Topic = { ...TOPICS[0], latestExcerpt: "" };
    render(<TopicCard topic={topic} />);
    expect(
      screen.queryByTestId("topic-excerpt-C-data-eng:revenue"),
    ).toBeNull();
  });
});
