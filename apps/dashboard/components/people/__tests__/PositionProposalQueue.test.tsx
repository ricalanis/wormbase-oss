/**
 * Tests for `PositionProposalQueue` (Wave H Phase 2 Task 2C).
 *
 * Covers: empty-state honest message, row rendering, confirm POST,
 * reject reason input, error surfacing on a 502.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PositionProposalQueue } from "../PositionProposalQueue";
import type { PositionProposalRow } from "../../../lib/server/worm-core-write";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn(),
    push: vi.fn(),
    replace: vi.fn(),
  }),
}));

function row(over: Partial<PositionProposalRow>): PositionProposalRow {
  return {
    person_id: over.person_id ?? "00000000-0000-0000-0000-000000000001",
    person_name: over.person_name ?? "Alice",
    position: over.position ?? "senior_engineer",
    confidence: over.confidence ?? 0.72,
    signals: over.signals ?? ["commit_msg", "design_doc"],
    proposed_at: over.proposed_at ?? "2026-05-03T10:00:00+00:00",
    proposed_by: over.proposed_by ?? "worm",
  };
}

describe("PositionProposalQueue", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders an honest empty state when there are no proposals", () => {
    render(<PositionProposalQueue proposals={[]} />);
    expect(
      screen.getByText(/no pending position proposals/i),
    ).toBeInTheDocument();
    // Heading still rendered with the "0" count.
    expect(
      screen.getByRole("heading", { level: 2 }),
    ).toHaveTextContent(/Pending position proposals · 0/);
  });

  it("renders one row per proposal with name, position, confidence, signals", () => {
    const proposals = [
      row({
        person_id: "p1",
        person_name: "Alice",
        position: "senior_engineer",
        signals: ["commit_msg"],
      }),
      row({
        person_id: "p2",
        person_name: "Bob",
        position: "data_analyst",
        signals: ["design_doc"],
      }),
    ];
    render(<PositionProposalQueue proposals={proposals} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("senior_engineer")).toBeInTheDocument();
    expect(screen.getByText("data_analyst")).toBeInTheDocument();
    expect(screen.getByText("commit_msg")).toBeInTheDocument();
    expect(screen.getByText("design_doc")).toBeInTheDocument();
  });

  it("POSTs to the confirm endpoint when Confirm is clicked", async () => {
    const proposals = [row({ person_id: "p1" })];
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ entry_ids: ["e1", "e2", "e3", "e4"] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<PositionProposalQueue proposals={proposals} />);
    fireEvent.click(screen.getByTestId("confirm-p1"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/people/p1/position/confirm");
    const body = JSON.parse(init.body);
    expect(body.position).toBe("senior_engineer");
  });

  it("opens the reason input when Reject is clicked and POSTs reason on confirm", async () => {
    const proposals = [row({ person_id: "p1" })];
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ entry_ids: ["e1", "e2", "e3", "e4"] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<PositionProposalQueue proposals={proposals} />);
    fireEvent.click(screen.getByTestId("reject-p1"));
    // Reason textarea now visible.
    const textarea = screen.getByLabelText(/reason \(optional\)/i);
    fireEvent.change(textarea, {
      target: { value: "joined as analyst, not engineer" },
    });
    fireEvent.click(screen.getByTestId("reject-confirm-p1"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/people/p1/position/reject");
    const body = JSON.parse(init.body);
    expect(body.position).toBe("senior_engineer");
    expect(body.reason).toBe("joined as analyst, not engineer");
  });

  it("surfaces an error when the API returns a non-2xx", async () => {
    const proposals = [row({ person_id: "p1" })];
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: "worm-core unreachable" }), {
        status: 502,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<PositionProposalQueue proposals={proposals} />);
    fireEvent.click(screen.getByTestId("confirm-p1"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/worm-core unreachable/);
    });
  });
});
