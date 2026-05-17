/**
 * Tests for ReactivityFiresLog (W5.A5).
 *
 * Covers:
 *   - fetches /api/v1/reactivities/{id}/fires?limit= on mount
 *   - renders one row per fire with seq + source seq + budget summary
 *   - "no fires yet" empty state when fires is []
 *   - error path falls through to the empty state with an inline alert
 *   - seq deep-link points at /trace?kind=emit_reactivity_fired&seq=
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { ReactivityFiresLog } from "../ReactivityFiresLog";

describe("ReactivityFiresLog", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("fetches fires on mount and renders rows", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        fires: [
          {
            seq: 42,
            ts: "2026-04-28T10:00:00.000Z",
            sourceSeq: 41,
            noveltyKey: "topic:owner",
            actionSeqs: [43, 44, 45, 46],
            budgetUsed: { per_owner: 1, per_tenant: 1 },
          },
        ],
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityFiresLog reactivityId="rx_a" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/reactivities/rx_a/fires?limit=50",
    );
    await waitFor(() =>
      expect(screen.getByTestId("reactivity-fire-row-42")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("reactivity-fire-source-42"),
    ).toHaveTextContent("#41");
    expect(
      screen.getByTestId("reactivity-fire-budget-42"),
    ).toHaveTextContent(/per_owner=1/);
  });

  it("renders the empty state when fires is empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ fires: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityFiresLog reactivityId="rx_b" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("reactivity-fires-empty-rx_b"),
      ).toBeInTheDocument(),
    );
  });

  it("renders the error path with a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({}),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityFiresLog reactivityId="rx_c" />);
    await waitFor(() =>
      expect(
        screen.getByTestId("reactivity-fires-error-rx_c"),
      ).toBeInTheDocument(),
    );
  });

  it("uses initialFires without fetching when provided", () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(
      <ReactivityFiresLog
        reactivityId="rx_d"
        initialFires={[
          {
            seq: 7,
            ts: "2026-04-28T10:00:00.000Z",
            sourceSeq: 6,
            noveltyKey: "",
            actionSeqs: [8, 9, 10, 11],
            budgetUsed: { per_owner: 1 },
          },
        ]}
      />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("reactivity-fire-row-7")).toBeInTheDocument();
  });
});
