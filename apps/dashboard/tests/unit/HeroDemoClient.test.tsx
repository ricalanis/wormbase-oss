/**
 * Phase 4 Task 4B — HeroDemoClient (replay-in-browser viewer).
 *
 * The viewer is the client half of the SSR-replayed hero demo: it
 * receives a deterministic payload from the server component, renders
 * a Slack-thread-style scaffold, scrubs through messages with hashes
 * visible, and re-fires the SSR replay via the "Replay again" button
 * to demonstrate hash-stability across re-runs.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";

import {
  HeroDemoClient,
  type LandingReplay,
} from "../../components/landing/HeroDemoClient";

const REPLAY: LandingReplay = {
  tenantSlug: "baseworm",
  companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
  untilTs: "2026-04-30T09:00:00Z",
  terminalHashHex: "deadbeef0000",
  entries: [
    {
      id: "e_0001",
      ts: "2026-04-30T08:00:00Z",
      who: "Bob",
      role: "actor",
      body: "@worm here is sales-q3.csv",
      kind: "chat_received",
      hashShort: "aaaaaaaaaaaa",
    },
    {
      id: "e_0002",
      ts: "2026-04-30T08:00:01Z",
      who: "WormBase",
      role: "worm",
      body: "Profiled. 4 tables proposed; bronze layer ready.",
      kind: "chat_sent",
      hashShort: "bbbbbbbbbbbb",
    },
    {
      id: "e_0003",
      ts: "2026-04-30T08:00:02Z",
      who: "WormBase",
      role: "worm",
      body: "Q3 net revenue computed: $1.42M (+12% QoQ).",
      kind: "kpi_resolved",
      hashShort: "cccccccccccc",
    },
  ],
  stop: "end_of_data",
};

describe("HeroDemoClient (4B replay-in-browser viewer)", () => {
  it("renders the hero-demo landmark + receipt footer (no placeholder)", () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    expect(screen.getByTestId("hero-demo")).toBeInTheDocument();
    expect(screen.getByTestId("hero-demo-receipt")).toBeInTheDocument();
    // 4B replaces the preview-placeholder marker entirely.
    expect(screen.queryByTestId("hero-demo-placeholder")).toBeNull();
  });

  it("renders one row per replay entry with hashShort visible (hashes on screen)", async () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    // Wait for the progressive reveal to surface every row.
    await waitFor(() => {
      for (const entry of REPLAY.entries) {
        const row = screen.getByTestId(`hero-demo-row-${entry.id}`);
        expect(row).toBeInTheDocument();
      }
    });
    // Hash receipt is rendered inside each row.
    for (const entry of REPLAY.entries) {
      const row = screen.getByTestId(`hero-demo-row-${entry.id}`);
      expect(within(row).getByText(new RegExp(entry.hashShort))).toBeInTheDocument();
    }
  });

  it("exposes the terminal-hash receipt + tenant slug in the footer", () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    const footer = screen.getByTestId("hero-demo-receipt");
    expect(within(footer).getByText(/deadbeef0000/)).toBeInTheDocument();
    expect(within(footer).getByText(/baseworm/)).toBeInTheDocument();
  });

  it("renders an honest stop-state when end of replay reached", async () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("hero-demo-stop-state")).toBeInTheDocument();
    });
  });

  it("scrubs entries in order via a step-counter (progressive reveal)", async () => {
    // Use fake timers + act() to verify the step counter actually
    // gates the reveal — no client-side jump-to-end shortcut.
    vi.useFakeTimers();
    try {
      render(<HeroDemoClient initial={REPLAY} stepDelayMs={50} />);
      // Initial: only the first row is revealed (step counter starts at 1).
      expect(screen.queryByTestId("hero-demo-row-e_0001")).toBeInTheDocument();
      expect(screen.queryByTestId("hero-demo-row-e_0002")).toBeNull();
      expect(screen.queryByTestId("hero-demo-row-e_0003")).toBeNull();
      // First tick reveals row 2.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60);
      });
      expect(screen.queryByTestId("hero-demo-row-e_0002")).toBeInTheDocument();
      // Second tick reveals row 3.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60);
      });
      expect(screen.queryByTestId("hero-demo-row-e_0003")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("Replay again button refires the SSR replay and renders the same hashes", async () => {
    // Real timers — the determinism contract we care about here is on the
    // fetch invocation + re-render. The payload-level determinism is
    // covered by the lib test.
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(REPLAY), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<HeroDemoClient initial={REPLAY} stepDelayMs={5} />);

    const button = await screen.findByTestId("hero-demo-replay-again");
    expect(button).toBeInTheDocument();
    fireEvent.click(button);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/landing/replay",
        expect.objectContaining({ cache: "no-store" }),
      );
    });

    // After replay-again, the same entries with the same hashShorts
    // render — the determinism contract surfaced on screen.
    await waitFor(() => {
      for (const entry of REPLAY.entries) {
        const row = screen.getByTestId(`hero-demo-row-${entry.id}`);
        expect(within(row).getByText(new RegExp(entry.hashShort))).toBeInTheDocument();
      }
    });

    fetchSpy.mockRestore();
  });

  it("supports keyboard / role accessibility on the replay button", () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    const button = screen.getByTestId("hero-demo-replay-again");
    expect(button.tagName.toLowerCase()).toBe("button");
    expect(button).not.toBeDisabled();
  });

  it("renders a thread scaffold with at least 3 rows (Slack-style)", async () => {
    render(<HeroDemoClient initial={REPLAY} stepDelayMs={1} />);
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^hero-demo-row-/);
      expect(rows.length).toBeGreaterThanOrEqual(3);
    });
  });
});
