/**
 * Tests for OutcomeLedgerView (Wave 3 Task 4).
 *
 * Pure presentational; the /lake/query-improvement page handles
 * empty state. These tests pin:
 *
 *   - one <tr> per outcome
 *   - quality_score renders as percent
 *   - useful=false shows the user_correction string
 *   - the row link points at /trace/agent_query/[agentQueryId]
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { OutcomeLedgerView } from "../OutcomeLedgerView";
import type { QueryOutcomeRow } from "../../../lib/query-improvement";

function outcome(
  partial: Partial<QueryOutcomeRow> & Pick<QueryOutcomeRow, "id">,
): QueryOutcomeRow {
  return {
    id: partial.id,
    agentQueryId: partial.agentQueryId ?? `audit-${partial.id}`,
    nlQuestion: partial.nlQuestion ?? "what was Q3 revenue?",
    finalQuerySpec: partial.finalQuerySpec ?? { metric: "revenue_total" },
    resultSummary: partial.resultSummary ?? { row_count: 1 },
    used: partial.used ?? true,
    useful: partial.useful ?? true,
    userCorrection: partial.userCorrection ?? null,
    qualityScore: partial.qualityScore ?? "1.0000",
    recordedAt: partial.recordedAt ?? "2026-05-11T10:00:00.000Z",
  };
}

describe("OutcomeLedgerView", () => {
  it("renders one row per outcome", () => {
    const rows = [
      outcome({ id: "outcome-1" }),
      outcome({ id: "outcome-2" }),
    ];
    render(<OutcomeLedgerView rows={rows} />);
    expect(
      screen.getByTestId("query-outcomes-row-outcome-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("query-outcomes-row-outcome-2"),
    ).toBeInTheDocument();
  });

  it("links each outcome to its trace chain", () => {
    const rows = [
      outcome({
        id: "outcome-1",
        agentQueryId: "audit-trail-abc",
      }),
    ];
    render(<OutcomeLedgerView rows={rows} />);
    const link = screen.getByTestId("query-outcomes-row-link-outcome-1");
    expect(link).toHaveAttribute("href", "/trace/agent_query/audit-trail-abc");
  });

  it("renders the quality score as a percent", () => {
    const rows = [
      outcome({ id: "outcome-q95", qualityScore: "0.9500" }),
    ];
    render(<OutcomeLedgerView rows={rows} />);
    expect(screen.getByTestId("query-outcomes-quality-outcome-q95")).toHaveTextContent("95%");
  });

  it("surfaces the user_correction string when present", () => {
    const rows = [
      outcome({
        id: "outcome-corrected",
        useful: false,
        used: true,
        userCorrection: "wanted gross churn, not net",
      }),
    ];
    render(<OutcomeLedgerView rows={rows} />);
    const correction = screen.getByTestId(
      "query-outcomes-correction-outcome-corrected",
    );
    expect(correction.textContent).toContain("wanted gross churn, not net");
  });
});
