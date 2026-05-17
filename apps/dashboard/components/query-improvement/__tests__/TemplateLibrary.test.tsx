/**
 * Tests for TemplateLibrary (Wave 3 Task 4).
 *
 * Pure presentational. Pins:
 *   - one <tr> per template
 *   - cluster size = promotedFromOutcomeIds.length
 *   - hitCount renders
 *   - querySpec compacts into a one-line ``key=value`` repr
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { TemplateLibrary } from "../TemplateLibrary";
import type { QueryTemplateRow } from "../../../lib/query-improvement";

function template(
  partial: Partial<QueryTemplateRow> & Pick<QueryTemplateRow, "id">,
): QueryTemplateRow {
  return {
    id: partial.id,
    domainId: partial.domainId ?? "domain-finance",
    nlIntent: partial.nlIntent ?? "revenue_by_quarter",
    querySpec: partial.querySpec ?? {
      metric: "revenue_total",
      time_grain: "quarter",
    },
    promotedFromOutcomeIds: partial.promotedFromOutcomeIds ?? [
      "outcome-1",
      "outcome-2",
      "outcome-3",
    ],
    qualityScore: partial.qualityScore ?? "0.9500",
    hitCount: partial.hitCount ?? 0,
    promotedAt: partial.promotedAt ?? "2026-05-11T10:00:00.000Z",
  };
}

describe("TemplateLibrary", () => {
  it("renders one row per template", () => {
    render(
      <TemplateLibrary
        rows={[template({ id: "tpl-1" }), template({ id: "tpl-2" })]}
      />,
    );
    expect(
      screen.getByTestId("query-templates-row-tpl-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("query-templates-row-tpl-2"),
    ).toBeInTheDocument();
  });

  it("shows the cluster size", () => {
    render(
      <TemplateLibrary
        rows={[
          template({
            id: "tpl-cluster-5",
            promotedFromOutcomeIds: ["a", "b", "c", "d", "e"],
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("query-templates-cluster-tpl-cluster-5"),
    ).toHaveTextContent("5");
  });

  it("shows hit count and a query-spec preview", () => {
    render(
      <TemplateLibrary
        rows={[
          template({
            id: "tpl-hot",
            hitCount: 42,
            querySpec: { metric: "revenue_total", time_grain: "quarter" },
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("query-templates-hits-tpl-hot"),
    ).toHaveTextContent("42");
    const spec = screen.getByTestId("query-templates-spec-tpl-hot");
    expect(spec.textContent).toContain("metric=revenue_total");
    expect(spec.textContent).toContain("time_grain=quarter");
  });
});
