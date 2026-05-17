/**
 * Unit tests for the four /research surface components:
 *
 *   * ResearchOverviewCard       — totals + win rate + top movers card
 *   * UserSelector               — Person × Position dropdown
 *   * HeadlineMetricSparkline    — sparkline SVG
 *   * ExperimentsTable           — propose → run → resolve table with
 *                                  approve / discard buttons
 *
 * All four are pure presentational components fed by mock data shaped
 * exactly like the live ledger folds in lib/ledger-client.ts.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ExperimentsTable } from "../../components/research/ExperimentsTable";
import { HeadlineMetricSparkline } from "../../components/research/HeadlineMetricSparkline";
import { ResearchOverviewCard } from "../../components/research/ResearchOverviewCard";
import { UserSelector } from "../../components/research/UserSelector";
import type {
  ExperimentRow,
  HeadlineMetricSeries,
  PositionRegistryRow,
  ResearchOverview,
} from "../../lib/ledger-client.types";

const RECEIPT = {
  hash: "abc123def456",
  source: "autoresearch_loop",
  owner: "person-1",
  classification: "internal" as const,
};

// ─── ResearchOverviewCard ───────────────────────────────────────────────

const OVERVIEW: ResearchOverview = {
  totalExperiments: 12,
  totalKept: 8,
  totalDiscarded: 4,
  winRate: 8 / 12,
  topMovers: [
    {
      position: "cfo",
      metricId: "revenue",
      delta: 0.144,
      experimentsKept: 4,
      experimentsDiscarded: 1,
    },
    {
      position: "data_engineer",
      metricId: "pipeline_p95_latency_ms",
      delta: -180.0,
      experimentsKept: 2,
      experimentsDiscarded: 0,
    },
  ],
  latestExperiments: [],
};

const OVERVIEW_EMPTY: ResearchOverview = {
  totalExperiments: 0,
  totalKept: 0,
  totalDiscarded: 0,
  winRate: null,
  topMovers: [],
  latestExperiments: [],
};

describe("ResearchOverviewCard", () => {
  it("renders totals + win rate + movers", () => {
    render(<ResearchOverviewCard overview={OVERVIEW} />);
    expect(screen.getByTestId("research-overview")).toBeInTheDocument();
    expect(screen.getByTestId("overview-total")).toHaveTextContent("12");
    expect(screen.getByTestId("overview-keep-discard")).toHaveTextContent(
      "8 · 4",
    );
    expect(screen.getByTestId("overview-winrate")).toHaveTextContent(/67%/);
    expect(
      screen.getByTestId("mover-cfo-revenue"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("mover-data_engineer-pipeline_p95_latency_ms"),
    ).toBeInTheDocument();
  });

  it("renders empty state when no movers exist", () => {
    render(<ResearchOverviewCard overview={OVERVIEW_EMPTY} />);
    expect(screen.getByTestId("overview-no-movers")).toBeInTheDocument();
    // win rate cell shows em-dash when totals are zero
    expect(screen.getByTestId("overview-winrate").textContent).toContain("—");
  });
});

// ─── UserSelector ───────────────────────────────────────────────────────

const REGISTRY: PositionRegistryRow[] = [
  {
    personId: "p-carol",
    displayName: "Carol",
    position: "cfo",
    email: "carol@example.com",
    role: "admin",
    assignedAt: "2026-04-24T10:00:00Z",
    receipt: RECEIPT,
  },
  {
    personId: "p-dave",
    displayName: "Dave",
    position: "data_engineer",
    email: null,
    role: "member",
    assignedAt: "2026-04-24T10:00:00Z",
    receipt: { ...RECEIPT, hash: "deedeefffeed" },
  },
];

describe("UserSelector", () => {
  it("renders the empty state when registry is empty", () => {
    render(
      <UserSelector
        registry={[]}
        selectedPersonId={null}
        onSelect={() => undefined}
      />,
    );
    expect(screen.getByTestId("user-selector-empty")).toBeInTheDocument();
  });

  it("renders an option per registry row", () => {
    render(
      <UserSelector
        registry={REGISTRY}
        selectedPersonId="p-carol"
        onSelect={() => undefined}
      />,
    );
    const select = screen.getByTestId("user-select") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("__all");
    expect(values).toContain("p-carol");
    expect(values).toContain("p-dave");
    expect(select.value).toBe("p-carol");
  });

  it("invokes onSelect with null when 'All' is picked", () => {
    const onSelect = vi.fn();
    render(
      <UserSelector
        registry={REGISTRY}
        selectedPersonId="p-carol"
        onSelect={onSelect}
      />,
    );
    const select = screen.getByTestId("user-select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "__all" } });
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("invokes onSelect with the new personId on change", () => {
    const onSelect = vi.fn();
    render(
      <UserSelector
        registry={REGISTRY}
        selectedPersonId="p-carol"
        onSelect={onSelect}
      />,
    );
    fireEvent.change(screen.getByTestId("user-select"), {
      target: { value: "p-dave" },
    });
    expect(onSelect).toHaveBeenCalledWith("p-dave");
  });
});

// ─── HeadlineMetricSparkline ────────────────────────────────────────────

const SERIES: HeadlineMetricSeries = {
  position: "cfo",
  metricId: "revenue",
  points: [
    { observedAt: "2026-04-24T10:00:00Z", value: 1_420_000 },
    { observedAt: "2026-04-24T10:30:00Z", value: 1_424_000 },
    { observedAt: "2026-04-24T11:00:00Z", value: 1_426_500 },
  ],
};

describe("HeadlineMetricSparkline", () => {
  it("renders an SVG with one circle per sample point", () => {
    render(<HeadlineMetricSparkline series={SERIES} />);
    const fig = screen.getByTestId("headline-sparkline");
    expect(fig).toBeInTheDocument();
    expect(fig.getAttribute("data-position")).toBe("cfo");
    expect(fig.getAttribute("data-metric")).toBe("revenue");
    expect(screen.getByTestId("sparkline-point-0")).toBeInTheDocument();
    expect(screen.getByTestId("sparkline-point-1")).toBeInTheDocument();
    expect(screen.getByTestId("sparkline-point-2")).toBeInTheDocument();
  });

  it("renders an empty state when no points are present", () => {
    render(
      <HeadlineMetricSparkline
        series={{ position: "cfo", metricId: "revenue", points: [] }}
      />,
    );
    expect(screen.getByTestId("sparkline-no-points")).toBeInTheDocument();
  });
});

// ─── ExperimentsTable ───────────────────────────────────────────────────

const EXPERIMENTS: ExperimentRow[] = [
  {
    experimentId: "e-1",
    forPersonId: "p-carol",
    position: "cfo",
    headlineMetric: "revenue",
    proposedChange: { kind: "kpi_definition", target: "revenue_forecast" },
    expectedDelta: 0.04,
    proposedAt: "2026-04-24T10:00:00Z",
    runLog: { iterations: 1 },
    startedAt: "2026-04-24T10:00:00Z",
    finishedAt: "2026-04-24T10:01:00Z",
    outcome: "keep",
    observedDelta: 0.036,
    rationale: "win",
    resolvedAt: "2026-04-24T10:01:00Z",
    receipt: RECEIPT,
  },
  {
    experimentId: "e-2",
    forPersonId: "p-carol",
    position: "cfo",
    headlineMetric: "cac_payback",
    proposedChange: { kind: "process_automation", target: "billing_close" },
    expectedDelta: -0.3,
    proposedAt: "2026-04-24T11:00:00Z",
    runLog: null,
    startedAt: null,
    finishedAt: null,
    outcome: null,
    observedDelta: null,
    rationale: null,
    resolvedAt: null,
    receipt: { ...RECEIPT, hash: "111222333444" },
  },
];

describe("ExperimentsTable", () => {
  it("renders rows with outcomes + receipts", () => {
    render(<ExperimentsTable rows={EXPERIMENTS} />);
    expect(screen.getByTestId("experiments-table")).toBeInTheDocument();
    expect(screen.getByTestId("experiment-e-1")).toBeInTheDocument();
    expect(screen.getByTestId("experiment-e-2")).toBeInTheDocument();
    // kept row has data-outcome=keep
    expect(
      screen.getByTestId("experiment-e-1").getAttribute("data-outcome"),
    ).toBe("keep");
    // in-flight row exposes data-outcome=pending
    expect(
      screen.getByTestId("experiment-e-2").getAttribute("data-outcome"),
    ).toBe("pending");
  });

  it("only shows approve/reject for in-flight experiments", () => {
    render(<ExperimentsTable rows={EXPERIMENTS} onResolve={() => undefined} />);
    expect(screen.queryByTestId("approve-experiment-e-1")).toBeNull();
    expect(screen.queryByTestId("reject-experiment-e-1")).toBeNull();
    expect(screen.getByTestId("approve-experiment-e-2")).toBeInTheDocument();
    expect(screen.getByTestId("reject-experiment-e-2")).toBeInTheDocument();
  });

  it("invokes onResolve with the experimentId + outcome after approve resolves", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          experiment_id: "e-2",
          outcome: "keep",
          rationale: "stub",
          entry_ids: ["e1"],
        }),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    try {
      const onResolve = vi.fn();
      render(<ExperimentsTable rows={EXPERIMENTS} onResolve={onResolve} />);
      fireEvent.click(screen.getByTestId("approve-experiment-e-2"));
      await vi.waitFor(() => expect(onResolve).toHaveBeenCalled());
      expect(onResolve).toHaveBeenCalledWith("e-2", "keep");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("invokes onResolve with discard when reject resolves", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          experiment_id: "e-2",
          outcome: "discard",
          rationale: "stub",
          entry_ids: ["e1"],
        }),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    try {
      const onResolve = vi.fn();
      render(<ExperimentsTable rows={EXPERIMENTS} onResolve={onResolve} />);
      fireEvent.click(screen.getByTestId("reject-experiment-e-2"));
      await vi.waitFor(() => expect(onResolve).toHaveBeenCalled());
      expect(onResolve).toHaveBeenCalledWith("e-2", "discard");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("renders empty state when no experiments are provided", () => {
    render(<ExperimentsTable rows={[]} />);
    expect(screen.getByTestId("experiments-empty")).toBeInTheDocument();
  });
});
