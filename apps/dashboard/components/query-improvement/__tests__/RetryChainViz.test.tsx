/**
 * Tests for RetryChainViz (Wave 3 Task 4).
 *
 * Pure presentational. Pins:
 *   - one <tr> per gap
 *   - reason renders with the matching test id (no_match / ambiguous / low_confidence)
 *   - the row link points at /lake/metrics-proposed
 *   - null proposed_metric_name renders as em dash
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RetryChainViz } from "../RetryChainViz";
import type { SemanticGapRow } from "../../../lib/query-improvement";

function gap(
  partial: Partial<SemanticGapRow> & Pick<SemanticGapRow, "id">,
): SemanticGapRow {
  return {
    id: partial.id,
    agentId: partial.agentId ?? "agent-1",
    nlQuestion: partial.nlQuestion ?? "show me ARR by region",
    reason: partial.reason ?? "no_match",
    proposedMetricName: partial.proposedMetricName ?? null,
    proposedAt: partial.proposedAt ?? "2026-05-11T10:00:00.000Z",
  };
}

describe("RetryChainViz", () => {
  it("renders one row per gap", () => {
    render(
      <RetryChainViz
        rows={[gap({ id: "gap-1" }), gap({ id: "gap-2", reason: "ambiguous" })]}
      />,
    );
    expect(screen.getByTestId("query-gaps-row-gap-1")).toBeInTheDocument();
    expect(screen.getByTestId("query-gaps-row-gap-2")).toBeInTheDocument();
  });

  it("renders distinct reason pills", () => {
    render(
      <RetryChainViz
        rows={[
          gap({ id: "g-nm", reason: "no_match" }),
          gap({ id: "g-amb", reason: "ambiguous" }),
          gap({ id: "g-lc", reason: "low_confidence" }),
        ]}
      />,
    );
    expect(screen.getByTestId("query-gaps-reason-no_match")).toBeInTheDocument();
    expect(screen.getByTestId("query-gaps-reason-ambiguous")).toBeInTheDocument();
    expect(
      screen.getByTestId("query-gaps-reason-low_confidence"),
    ).toBeInTheDocument();
  });

  it("links to the admin queue", () => {
    render(<RetryChainViz rows={[gap({ id: "g-1" })]} />);
    const link = screen.getByTestId("query-gaps-row-link-g-1");
    expect(link).toHaveAttribute("href", "/lake/metrics-proposed");
  });

  it("renders em dash for null proposed_metric_name", () => {
    render(
      <RetryChainViz
        rows={[gap({ id: "g-null-metric", proposedMetricName: null })]}
      />,
    );
    expect(
      screen.getByTestId("query-gaps-proposed-g-null-metric"),
    ).toHaveTextContent("—");
  });
});
