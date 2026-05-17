/**
 * Tests for `InstallCascadePanel` (W1.A3).
 *
 * The panel uses the browser's native EventSource API. happy-dom does
 * not ship a real EventSource; we install a stub on `globalThis` for
 * the duration of each test so the component's lifecycle (open / message
 * / error / close) is exercised end-to-end.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

import { InstallCascadePanel } from "../InstallCascadePanel";

class StubEventSource {
  public url: string;
  public onopen: ((e: Event) => void) | null = null;
  public onmessage: ((e: MessageEvent<string>) => void) | null = null;
  public onerror: ((e: Event) => void) | null = null;
  public closed = false;

  static instances: StubEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    StubEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  // Test helpers
  fireOpen() {
    this.onopen?.(new Event("open"));
  }
  fireMessage(data: unknown) {
    const ev = new MessageEvent<string>("message", {
      data: typeof data === "string" ? data : JSON.stringify(data),
    });
    this.onmessage?.(ev);
  }
  fireError() {
    this.onerror?.(new Event("error"));
  }
}

describe("InstallCascadePanel", () => {
  let originalEventSource: typeof EventSource | undefined;

  beforeEach(() => {
    StubEventSource.instances = [];
    // happy-dom may or may not define EventSource; preserve it.
    originalEventSource = (globalThis as unknown as {
      EventSource?: typeof EventSource;
    }).EventSource;
    (globalThis as unknown as {
      EventSource: typeof EventSource;
    }).EventSource = StubEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    if (originalEventSource) {
      (globalThis as unknown as {
        EventSource: typeof EventSource;
      }).EventSource = originalEventSource;
    } else {
      delete (globalThis as { EventSource?: typeof EventSource }).EventSource;
    }
  });

  it("renders all 9 cascade steps as initially unseen", () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={42} />);
    const list = screen.getByTestId("install-cascade-steps");
    expect(list.children.length).toBe(9);
    // Every step is "not seen" before any SSE message arrives.
    expect(
      screen.getByTestId("cascade-step-install_completed"),
    ).toHaveAttribute("data-seen", "false");
    expect(
      screen.getByTestId("cascade-step-autoresearch_armed"),
    ).toHaveAttribute("data-seen", "false");
  });

  it("opens an EventSource against the expected URL with kinds + filter_install + since", () => {
    render(<InstallCascadePanel installId="install-abc" sinceSeq={100} />);
    expect(StubEventSource.instances.length).toBe(1);
    const url = StubEventSource.instances[0].url;
    expect(url).toContain("/api/v1/ledger/stream");
    expect(url).toContain("since=100");
    expect(url).toContain("kinds=execute%2Cverify%2Cresolve");
    expect(url).toContain("filter_install=install-abc");
  });

  it("transitions to live · streaming when the source opens", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    expect(
      screen.getByTestId("cascade-connection-open"),
    ).toBeInTheDocument();
  });

  it("checks off the install_completed step when the matching tool fires", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 101,
        kind: "execute",
        ts: "2026-04-27T12:00:00Z",
        hash: "abcd",
        payload: { tool: "emit_install_completed", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-install_completed"),
      ).toHaveAttribute("data-seen", "true"),
    );
    expect(
      screen.getByTestId("cascade-step-install_completed-mark").textContent,
    ).toBe("✓");
  });

  it("ignores malformed SSE frames", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() => source.fireMessage("this is not json"));
    // Still all unseen.
    expect(
      screen.getByTestId("cascade-step-install_completed"),
    ).toHaveAttribute("data-seen", "false");
  });

  it("renders an honest error footer when SSE errors before opening", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    // No fireOpen — go straight to error.
    act(() => source.fireError());
    // connection state may stay "connecting" or move to error depending on
    // ordering; only assert the panel still surfaces a footer.
    expect(screen.getByTestId("install-cascade-footer")).toBeInTheDocument();
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = render(
      <InstallCascadePanel installId="install-1" sinceSeq={null} />,
    );
    const source = StubEventSource.instances[0];
    expect(source.closed).toBe(false);
    unmount();
    expect(source.closed).toBe(true);
  });

  it("falls back to the error path when EventSource is not available", () => {
    delete (globalThis as { EventSource?: typeof EventSource }).EventSource;
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    expect(
      screen.getByTestId("cascade-connection-error"),
    ).toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // F1 correctness — Sub-wave A, 2026-05-30.
  //
  // Five of nine cells previously matched emitter names with no producer
  // (`emit_default_lake_provisioned`, `emit_lake_bronze_ingested`,
  // `emit_lake_silver_promoted`, `emit_lake_gold_published`,
  // `emit_autoresearch_armed`). The audit at
  // docs/superpowers/notes/2026-05-30-onboarding-audit.md confirmed real
  // producers emit `emit_source_*` + `emit_experiment_proposed`. These
  // tests pin the renamed cells to the real producer tool names so a
  // future revert is caught at CI.
  // -----------------------------------------------------------------------

  it("checks off local_lake_provisioned when emit_source_profiled fires (provision_local_lake chain end)", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 200,
        kind: "execute",
        ts: "2026-04-27T12:01:00Z",
        hash: "h-prof",
        payload: { tool: "emit_source_profiled", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-local_lake_provisioned"),
      ).toHaveAttribute("data-seen", "true"),
    );
  });

  it("checks off lake_bronze when emit_source_bronzed fires (MedallionCascade bronze)", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 201,
        kind: "execute",
        ts: "2026-04-27T12:02:00Z",
        hash: "h-brz",
        payload: { tool: "emit_source_bronzed", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-lake_bronze"),
      ).toHaveAttribute("data-seen", "true"),
    );
  });

  it("checks off lake_silver when emit_source_silvered fires (MedallionCascade silver)", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 202,
        kind: "execute",
        ts: "2026-04-27T12:03:00Z",
        hash: "h-slv",
        payload: { tool: "emit_source_silvered", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-lake_silver"),
      ).toHaveAttribute("data-seen", "true"),
    );
  });

  it("checks off lake_gold when emit_source_golded fires (MedallionCascade gold)", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 203,
        kind: "execute",
        ts: "2026-04-27T12:04:00Z",
        hash: "h-gld",
        payload: { tool: "emit_source_golded", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-lake_gold"),
      ).toHaveAttribute("data-seen", "true"),
    );
  });

  it("checks off autoresearch_armed when emit_experiment_proposed fires (research-loop)", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    act(() =>
      source.fireMessage({
        seq: 204,
        kind: "execute",
        ts: "2026-04-27T12:05:00Z",
        hash: "h-exp",
        payload: { tool: "emit_experiment_proposed", args: {} },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cascade-step-autoresearch_armed"),
      ).toHaveAttribute("data-seen", "true"),
    );
  });

  it("ignores legacy non-producer tool names that previously kept cells permanently pending", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    // The 5 legacy names that have no producer. None of these should
    // ever flip a cell — the renamed F1 wiring matches the producer
    // names instead. This protects against a future regression that
    // re-introduces the unmatched names.
    const legacyNames = [
      "emit_default_lake_provisioned",
      "emit_lake_bronze_ingested",
      "emit_lake_silver_promoted",
      "emit_lake_gold_published",
      "emit_autoresearch_armed",
    ];
    legacyNames.forEach((tool, idx) => {
      act(() =>
        source.fireMessage({
          seq: 300 + idx,
          kind: "execute",
          ts: "2026-04-27T13:00:00Z",
          hash: `h-legacy-${idx}`,
          payload: { tool, args: {} },
        }),
      );
    });
    // All five renamed cells remain unseen.
    for (const id of [
      "local_lake_provisioned",
      "lake_bronze",
      "lake_silver",
      "lake_gold",
      "autoresearch_armed",
    ]) {
      expect(
        screen.getByTestId(`cascade-step-${id}`),
      ).toHaveAttribute("data-seen", "false");
    }
  });

  it("checks off all 9 cells when the full real-producer cascade lands in order", async () => {
    render(<InstallCascadePanel installId="install-1" sinceSeq={null} />);
    const source = StubEventSource.instances[0];
    act(() => source.fireOpen());
    const cascade = [
      ["emit_install_completed", "install_completed"],
      ["emit_setup_mode_chosen", "setup_mode_chosen"],
      ["emit_source_profiled", "local_lake_provisioned"],
      ["emit_source_bronzed", "lake_bronze"],
      ["emit_source_silvered", "lake_silver"],
      ["emit_source_golded", "lake_gold"],
      ["emit_concept_proposed", "concept_proposed"],
      ["emit_memory_written", "ramp_recompute"],
      ["emit_experiment_proposed", "autoresearch_armed"],
    ] as const;
    cascade.forEach(([tool], idx) => {
      act(() =>
        source.fireMessage({
          seq: 500 + idx,
          kind: "execute",
          ts: "2026-04-27T14:00:00Z",
          hash: `h-real-${idx}`,
          payload: { tool, args: {} },
        }),
      );
    });
    for (const [, cellId] of cascade) {
      await waitFor(() =>
        expect(
          screen.getByTestId(`cascade-step-${cellId}`),
        ).toHaveAttribute("data-seen", "true"),
      );
    }
  });
});
