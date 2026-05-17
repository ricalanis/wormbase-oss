/**
 * Tests for CompositeScoreCard + KeepRateChart (Demo-day P1).
 *
 * Asserts:
 *   - Empty series renders an honest empty-state, not a fixture
 *   - ≥9 points render as clickable circles linking to /trace with
 *     the correct seqLo/seqHi query params
 *   - Top-contributing-reactivity badge surfaces per point
 *   - KeepRateChart renders one row per scope and tags synthetic days
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CompositeScoreCard } from "../CompositeScoreCard";
import { KeepRateChart } from "../KeepRateChart";
import type {
  CompositeScorePoint,
  CompositeScoreSeries,
  KeepRateSample,
} from "../../../lib/ledger-client.types";


const TENANT = "00000000-0000-0000-0000-000000000001";

function makePoint(i: number, score: number, reactivity = "r1"): CompositeScorePoint {
  return {
    ledgerHeight: 10 + i,
    ts: new Date(2026, 3, 28, 10, i).toISOString(),
    score,
    components: {
      gate_precision: score,
      propose_keep_ratio: score,
      ramp_delta: score,
      reactivity_confirm_rate: score,
    },
    topContributorReactivityId: reactivity,
    contributingSeqLo: i,
    contributingSeqHi: 10 + i,
  };
}

describe("CompositeScoreCard", () => {
  it("renders an honest empty-state when no points exist", () => {
    const series: CompositeScoreSeries = {
      tenantId: TENANT,
      points: [],
      windowDays: 7,
      weights: {
        gate_precision: 0.25,
        propose_keep_ratio: 0.25,
        ramp_delta: 0.25,
        reactivity_confirm_rate: 0.25,
      },
    };
    render(<CompositeScoreCard series={series} />);
    expect(screen.getByTestId("composite-score-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("composite-score-svg")).not.toBeInTheDocument();
  });

  it("renders ≥9 clickable circles linking to /trace with the correct seq range", () => {
    const points: CompositeScorePoint[] = [];
    for (let i = 0; i < 9; i += 1) {
      points.push(makePoint(i, 0.9 - i * 0.05));
    }
    const series: CompositeScoreSeries = {
      tenantId: TENANT,
      points,
      windowDays: 7,
      weights: {
        gate_precision: 0.25,
        propose_keep_ratio: 0.25,
        ramp_delta: 0.25,
        reactivity_confirm_rate: 0.25,
      },
    };
    render(<CompositeScoreCard series={series} />);

    expect(screen.getByTestId("composite-score-svg")).toBeInTheDocument();
    for (let i = 0; i < 9; i += 1) {
      const node = screen.getByTestId(`composite-score-point-${i}`);
      expect(node).toBeInTheDocument();
      expect(node).toHaveAttribute(
        "href",
        // Next/link encodes the query into ?seqLo=<lo>&seqHi=<hi>
        expect.stringMatching(
          new RegExp(
            `^/trace\\?seqLo=${i}&seqHi=${10 + i}$|/trace.*seqLo=${i}.*seqHi=${10 + i}`,
          ),
        ),
      );
    }
  });

  it("surfaces the top-contributing-reactivity badge for each point", () => {
    const points: CompositeScorePoint[] = [];
    for (let i = 0; i < 9; i += 1) {
      points.push(makePoint(i, 0.7, i < 5 ? "alpha" : "beta"));
    }
    const series: CompositeScoreSeries = {
      tenantId: TENANT,
      points,
      windowDays: 7,
      weights: {
        gate_precision: 0.25,
        propose_keep_ratio: 0.25,
        ramp_delta: 0.25,
        reactivity_confirm_rate: 0.25,
      },
    };
    render(<CompositeScoreCard series={series} />);
    const badges = screen.getAllByTestId(/composite-score-badge-/);
    expect(badges.length).toBe(9);
    expect(badges[0]).toHaveTextContent("alpha");
    expect(badges[8]).toHaveTextContent("beta");
  });

  it("data-direction='descending' when last loss < first loss", () => {
    const points: CompositeScorePoint[] = [];
    for (let i = 0; i < 9; i += 1) {
      // Score climbs → loss falls → descending.
      points.push(makePoint(i, 0.1 + i * 0.1));
    }
    const series: CompositeScoreSeries = {
      tenantId: TENANT,
      points,
      windowDays: 7,
      weights: {
        gate_precision: 0.25,
        propose_keep_ratio: 0.25,
        ramp_delta: 0.25,
        reactivity_confirm_rate: 0.25,
      },
    };
    render(<CompositeScoreCard series={series} />);
    expect(screen.getByTestId("composite-score-card")).toHaveAttribute(
      "data-direction",
      "descending",
    );
  });
});

describe("KeepRateChart", () => {
  it("renders an honest empty-state when no rows exist", () => {
    render(<KeepRateChart rows={[]} />);
    expect(screen.getByTestId("keep-rate-empty")).toBeInTheDocument();
  });

  it("renders one row per scope with a bar per day", () => {
    const rows: KeepRateSample[] = [
      { scope: "person", day: "2026-04-22", kept: 5, total: 8, ratio: 0.625, synthetic: false },
      { scope: "person", day: "2026-04-23", kept: 6, total: 8, ratio: 0.75, synthetic: false },
      { scope: "team", day: "2026-04-22", kept: 1, total: 2, ratio: 0.5, synthetic: true },
      { scope: "company", day: "2026-04-22", kept: 4, total: 5, ratio: 0.8, synthetic: false },
    ];
    render(<KeepRateChart rows={rows} />);

    expect(screen.getByTestId("keep-rate-row-person")).toBeInTheDocument();
    expect(screen.getByTestId("keep-rate-row-team")).toBeInTheDocument();
    expect(screen.getByTestId("keep-rate-row-company")).toBeInTheDocument();
    // Per-day bars are present.
    expect(
      screen.getByTestId("keep-rate-bar-person-2026-04-22"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("keep-rate-bar-person-2026-04-23"),
    ).toBeInTheDocument();
  });

  it("tags scopes that have any synthetic day with a 'synthetic baseline' badge", () => {
    const rows: KeepRateSample[] = [
      { scope: "team", day: "2026-04-22", kept: 1, total: 2, ratio: 0.5, synthetic: true },
      { scope: "company", day: "2026-04-22", kept: 4, total: 5, ratio: 0.8, synthetic: false },
    ];
    render(<KeepRateChart rows={rows} />);
    expect(
      screen.getByTestId("keep-rate-synthetic-badge-team"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("keep-rate-synthetic-badge-company"),
    ).not.toBeInTheDocument();
  });
});
