/**
 * KpiCompareView — Phase 3 Task 3E.
 *
 * Side-by-side hash + value diff for two replay timestamps. Three states:
 * empty (no T1, no T2), single (one of two picked), compare (both picked).
 * The "matches" badge fires when both columns landed on the same row.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { KpiCompareView } from "../../components/kpis/KpiCompareView";
import type { KpiReplaySnapshot } from "../../lib/server/kpi-compare";

const empty: KpiReplaySnapshot = {
  found: false,
  value: null,
  hash: "",
  rowTs: null,
  rowSeq: 0,
  scanCount: 0,
};

function snap(over: Partial<KpiReplaySnapshot>): KpiReplaySnapshot {
  return { ...empty, found: true, ...over };
}

describe("KpiCompareView · empty state", () => {
  it("renders the picker hint when neither T1 nor T2 are picked", () => {
    render(
      <KpiCompareView
        kpiId="revenue.q3"
        t1={null}
        t2={null}
        snapshotA={empty}
        snapshotB={empty}
      />,
    );
    expect(screen.getByTestId("kpi-compare-view")).toHaveAttribute(
      "data-state",
      "empty",
    );
    expect(screen.getByTestId("kpi-compare-empty-hint")).toBeInTheDocument();
    // Both columns render but with the dim "(no timestamp picked)" prose.
    const colA = screen.getByTestId("kpi-compare-col-A");
    const colB = screen.getByTestId("kpi-compare-col-B");
    expect(colA.textContent).toContain("no timestamp picked");
    expect(colB.textContent).toContain("no timestamp picked");
  });
});

describe("KpiCompareView · single replay", () => {
  it("renders one populated column and one dim column", () => {
    render(
      <KpiCompareView
        kpiId="revenue.q3"
        t1="2026-04-26T00:00:00Z"
        t2={null}
        snapshotA={snap({
          value: 42,
          hash: "a".repeat(64),
          rowTs: "2026-04-25T12:00:00Z",
          rowSeq: 17,
          scanCount: 3,
        })}
        snapshotB={empty}
      />,
    );
    expect(screen.getByTestId("kpi-compare-view")).toHaveAttribute(
      "data-state",
      "single",
    );
    expect(screen.getByTestId("kpi-compare-col-A-value").textContent).toBe(
      "42",
    );
    expect(screen.getByTestId("kpi-compare-col-A-hash").textContent).toBe(
      "a".repeat(64),
    );
    // Single state suppresses the match badge.
    expect(screen.queryByTestId("kpi-compare-match-badge")).toBeNull();
  });
});

describe("KpiCompareView · compare both", () => {
  it("fires the matches-badge with data-matches=true when hash + value align", () => {
    const same = snap({
      value: 1234567,
      hash: "f".repeat(64),
      rowTs: "2026-04-25T12:00:00Z",
      rowSeq: 17,
      scanCount: 3,
    });
    render(
      <KpiCompareView
        kpiId="revenue.q3"
        t1="2026-04-26T00:00:00Z"
        t2="2026-04-26T01:00:00Z"
        snapshotA={same}
        snapshotB={same}
      />,
    );
    const badge = screen.getByTestId("kpi-compare-match-badge");
    expect(badge).toHaveAttribute("data-matches", "true");
    expect(badge.textContent).toMatch(/hashes match/i);
    expect(badge.textContent).toContain("hash ==");
    expect(badge.textContent).toContain("value ==");
  });

  it("fires the matches-badge with data-matches=false when hashes diverge", () => {
    render(
      <KpiCompareView
        kpiId="revenue.q3"
        t1="2026-04-26T00:00:00Z"
        t2="2026-04-27T00:00:00Z"
        snapshotA={snap({
          value: 100,
          hash: "a".repeat(64),
          rowTs: "2026-04-25T12:00:00Z",
          rowSeq: 17,
          scanCount: 3,
        })}
        snapshotB={snap({
          value: 200,
          hash: "b".repeat(64),
          rowTs: "2026-04-26T18:00:00Z",
          rowSeq: 31,
          scanCount: 5,
        })}
      />,
    );
    const badge = screen.getByTestId("kpi-compare-match-badge");
    expect(badge).toHaveAttribute("data-matches", "false");
    expect(badge.textContent).toMatch(/ledger advanced/i);
    expect(badge.textContent).toContain("hash !=");
    expect(badge.textContent).toContain("value !=");
  });

  it("suppresses the badge when one side is genuinely empty (no row at T)", () => {
    render(
      <KpiCompareView
        kpiId="revenue.q3"
        t1="2026-04-26T00:00:00Z"
        t2="2026-04-27T00:00:00Z"
        snapshotA={empty}
        snapshotB={snap({
          value: 200,
          hash: "b".repeat(64),
          rowTs: "2026-04-26T18:00:00Z",
          rowSeq: 31,
          scanCount: 5,
        })}
      />,
    );
    expect(screen.queryByTestId("kpi-compare-match-badge")).toBeNull();
    // The empty side surfaces an honest "no emit_kpi_node row" prose.
    expect(screen.getByTestId("kpi-compare-col-A-empty")).toBeInTheDocument();
    // The found side still shows its row.
    expect(screen.getByTestId("kpi-compare-col-B-value").textContent).toBe(
      "200",
    );
  });
});
