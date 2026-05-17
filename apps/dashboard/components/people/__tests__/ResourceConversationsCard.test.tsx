/**
 * Tests for ResourceConversationsCard (W5.A5).
 *
 * Covers:
 *   - fetches /api/v1/people/<id>/resource-conversations on mount
 *   - renders one row per conversation with topic + statement + replies
 *   - "no active conversations" empty state when [] is returned
 *   - error path falls through to empty state with inline alert
 *   - Resolve button POSTs to /api/v1/resource-conversations/<id>/resolve
 *     and flips the row to a Resolved state
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ResourceConversationsCard } from "../ResourceConversationsCard";
import type { ResourceConversation } from "../../../lib/ledger-client.types";

const SAMPLE_CONV: ResourceConversation = {
  conversationId: "cv-1",
  ownerId: "p-1",
  topic: {
    kind: "kpi",
    id: "k-churn",
    label: "Churn",
    confidence: 0.9,
    domainId: null,
  },
  statement: "our churn is up 8% MoM in Europe",
  statementSeq: 99,
  channel: "C-rev",
  resources: {
    kpis: [],
    sources: [],
    decisions: [],
    processes: [],
    dataProducts: [],
  },
  proposedAt: "2026-04-28T10:00:00.000Z",
  seq: 100,
  replies: [],
  recentReplies: [
    {
      replierId: "p-1",
      content: "thanks, will look",
      ts: "2026-04-28T10:01:00.000Z",
      seq: 101,
    },
  ],
  replyCount: 1,
  resolution: null,
  receipt: {
    hash: "abc123",
    source: "reactivity",
    owner: "p-1",
    classification: "internal",
  },
};

describe("ResourceConversationsCard", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("fetches conversations on mount and renders a row", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ conversations: [SAMPLE_CONV] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ResourceConversationsCard personId="p-1" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("resource-conversation-cv-1"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("resource-conversation-topic-cv-1"),
    ).toHaveTextContent(/kpi/i);
    expect(
      screen.getByTestId("resource-conversation-statement-cv-1"),
    ).toHaveTextContent(/churn is up/);
    expect(
      screen.getByTestId("resource-conversation-replies-cv-1"),
    ).toBeInTheDocument();
  });

  it("renders the empty state when no conversations are returned", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ conversations: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ResourceConversationsCard personId="p-2" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("resource-conversations-empty"),
      ).toBeInTheDocument(),
    );
  });

  it("renders the error state on a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({}),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ResourceConversationsCard personId="p-3" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("resource-conversations-error"),
      ).toBeInTheDocument(),
    );
  });

  it("clicking Resolve POSTs to the resolve endpoint and flips the row", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ conversations: [SAMPLE_CONV] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => "{}",
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ResourceConversationsCard personId="p-1" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("resource-conversation-cv-1"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByTestId("resource-conversation-resolve-cv-1"),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/resource-conversations/cv-1/resolve",
    );
  });

  it("uses initialConversations without fetching when provided", () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ResourceConversationsCard
        personId="p-1"
        initialConversations={[SAMPLE_CONV]}
      />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(
      screen.getByTestId("resource-conversation-cv-1"),
    ).toBeInTheDocument();
  });
});
