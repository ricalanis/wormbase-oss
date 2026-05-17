/**
 * LineageProposalRow component tests — L3 Sub-wave D.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LineageProposalRow } from "../LineageProposalRow";
import type { LineageEdgeRow } from "../../../lib/lineage";

function makeEdge(partial: Partial<LineageEdgeRow> = {}): LineageEdgeRow {
  const base: LineageEdgeRow = {
    edgeId: "edge-001",
    srcTableId: "snowflake.raw.users",
    srcColumn: "id",
    tgtTableId: "snowflake.dbt.dim_users",
    tgtColumn: "user_id",
    confidence: 0.99,
    strategy: "dbt_manifest",
    reasoning: "manifest-listed",
    evidence: {},
    state: "proposed",
    stateChangedAt: "2026-05-29T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("LineageProposalRow", () => {
  it("renders the source / target / confidence / strategy cells", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge({ confidence: 0.95 })}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("lineage-proposal-row-edge-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("lineage-proposal-confidence-edge-001"),
    ).toHaveTextContent("95%");
    expect(
      screen.getByTestId("lineage-proposal-strategy-edge-001"),
    ).toHaveTextContent("dbt_manifest");
  });

  it("invokes onConfirm with the edge when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const edge = makeEdge();
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={edge}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("lineage-proposal-confirm-edge-001"));
    expect(onConfirm).toHaveBeenCalledWith(edge);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("invokes onReject with the edge when Reject is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const edge = makeEdge();
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={edge}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("lineage-proposal-reject-edge-001"));
    expect(onReject).toHaveBeenCalledWith(edge);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge()}
            disabled
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "lineage-proposal-confirm-edge-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "lineage-proposal-reject-edge-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });

  it("renders whole-table edges without a column suffix", () => {
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge({
              edgeId: "whole-table-edge",
              srcColumn: null,
              tgtColumn: null,
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const row = screen.getByTestId("lineage-proposal-row-whole-table-edge");
    expect(row.textContent).not.toContain("·");
  });

  // ─── R1 L4↦L3 reverse-arc badge (Recipe Addendum #3) ──────────────

  it("does NOT render the impact-count badge when impactCount is undefined", () => {
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("lineage-proposal-impact-badge-edge-001"),
    ).not.toBeInTheDocument();
  });

  it("does NOT render the impact-count badge when impactCount is 0", () => {
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={0}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("lineage-proposal-impact-badge-edge-001"),
    ).not.toBeInTheDocument();
  });

  it("renders an impact-count badge when impactCount > 0", () => {
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={3}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "lineage-proposal-impact-badge-edge-001",
    );
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3 impact proposals via L4");
    const href = badge.getAttribute("href") ?? "";
    expect(href).toContain("/lake/schema-impact?");
    expect(href).toContain("upstream_lineage_edge_id=edge-001");
  });

  it("uses singular 'impact proposal' when impactCount === 1", () => {
    render(
      <table>
        <tbody>
          <LineageProposalRow
            edge={makeEdge()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("lineage-proposal-impact-badge-edge-001"),
    ).toHaveTextContent("1 impact proposal via L4");
  });
});
