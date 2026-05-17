/**
 * SourceCandidateRow component tests — L1 Sub-wave D (2026-06-08).
 *
 * Pins:
 *   * Render shape (proposed_kind chip + identifier, domain hint,
 *     confidence, strategy, Promote + Reject buttons).
 *   * Honest NULL ``domain_id_hint`` per handoff concerns #2 + #3
 *     (renders ``—`` cell rather than synthesizing).
 *   * Promote + Reject button callbacks fire with the row data.
 *   * disabled={true} suppresses both action callbacks (non-admin lens).
 *   * Pending rows do NOT render a downstream link — that affordance
 *     is exclusive to promoted rows in the Promoted Candidates section
 *     on the page (per spec §4.7 — downstream link is sui-generis,
 *     not a peer-axis cross-axis chain).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SourceCandidateRow } from "../SourceCandidateRow";
import type { SourceCandidateRow as SourceCandidateRowData } from "../../../lib/source-candidates";

function makeProposal(
  partial: Partial<SourceCandidateRowData> = {},
): SourceCandidateRowData {
  const base: SourceCandidateRowData = {
    candidateId: "cand-001",
    proposedKind: "stripe",
    proposedIdentifier: "monthly_recurring_revenue",
    domainIdHint: null,
    strategy: "kpi_gap",
    reasoning: "KPI mrr has no source; *_revenue → stripe",
    confidence: 0.72,
    evidence: { kpi_node_id: "kpi-mrr-001" },
    downstreamSourceProposedId: null,
    state: "proposed",
    stateChangedAt: "2026-06-08T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("SourceCandidateRow", () => {
  it("renders the proposed_kind chip + identifier + confidence + strategy", () => {
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal({ confidence: 0.72 })}
            onPromote={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByTestId("source-candidate-row-cand-001")).toBeInTheDocument();
    expect(screen.getByTestId("source-candidate-kind-chip-cand-001")).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-identifier-cand-001"),
    ).toHaveTextContent("monthly_recurring_revenue");
    expect(
      screen.getByTestId("source-candidate-confidence-cand-001"),
    ).toHaveTextContent("72%");
    expect(
      screen.getByTestId("source-candidate-strategy-cand-001"),
    ).toHaveTextContent("kpi_gap");
  });

  it("renders ``—`` in the domain cell when domain_id_hint is NULL (Wave 1, handoff #2+#3)", () => {
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal({ domainIdHint: null })}
            onPromote={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("source-candidate-domain-null-cand-001"),
    ).toBeInTheDocument();
  });

  it("renders the actual domain id when domain_id_hint is set", () => {
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal({ domainIdHint: "domain-finance-001" })}
            onPromote={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const cell = screen.getByTestId("source-candidate-domain-cand-001");
    expect(cell.textContent).toContain("domain-finance-001");
    expect(
      screen.queryByTestId("source-candidate-domain-null-cand-001"),
    ).toBeNull();
  });

  it("does NOT render a downstream link on pending rows (downstream link is promoted-rows-only)", () => {
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal({
              downstreamSourceProposedId: "source-abc",
            })}
            onPromote={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    // Even when downstreamSourceProposedId is set on a (hypothetical)
    // pending row, the pending row does NOT render the link — it's
    // surfaced only on promoted rows in the page-level Promoted
    // Candidates section.
    expect(
      screen.queryByTestId("source-candidate-downstream-link-cand-001"),
    ).toBeNull();
  });

  it("fires onPromote with the row data when Promote clicked", () => {
    const onPromote = vi.fn();
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal()}
            onPromote={onPromote}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("source-candidate-promote-cand-001"));
    expect(onPromote).toHaveBeenCalledTimes(1);
    expect(onPromote.mock.calls[0][0].candidateId).toBe("cand-001");
  });

  it("fires onReject with the row data when Reject clicked", () => {
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal()}
            onPromote={vi.fn()}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("source-candidate-reject-cand-001"));
    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onReject.mock.calls[0][0].candidateId).toBe("cand-001");
  });

  it("disabled={true} prevents both action callbacks from firing", () => {
    const onPromote = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <SourceCandidateRow
            proposal={makeProposal()}
            disabled
            onPromote={onPromote}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("source-candidate-promote-cand-001"));
    fireEvent.click(screen.getByTestId("source-candidate-reject-cand-001"));
    expect(onPromote).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });
});
