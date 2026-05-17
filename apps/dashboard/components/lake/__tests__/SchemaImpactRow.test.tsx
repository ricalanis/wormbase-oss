/**
 * SchemaImpactRow component tests — L4 Sub-wave D.
 *
 * Including the FIRST cross-axis trace navigation test: rows that
 * carry ``upstreamLineageEdgeId`` render a "view L3 edge" link to
 * ``/lake/lineage?edge_id=<id>``; rows without it (e.g. ``type_coercion``
 * strategy) render no link at all (no dead links per handoff
 * concern #3).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SchemaImpactRow } from "../SchemaImpactRow";
import type { SchemaImpactRow as SchemaImpactRowData } from "../../../lib/schema-impact";

function makeImpact(
  partial: Partial<SchemaImpactRowData> = {},
): SchemaImpactRowData {
  const base: SchemaImpactRowData = {
    impactId: "impact-001",
    sourceId: "src-snowflake-prod",
    srcTable: "raw.events",
    srcColumn: "user_id",
    changeKind: "column_type_changed",
    impactKind: "tgt_column_type_mismatch",
    tgtTableId: "dbt.dim_users",
    tgtColumn: "user_id",
    upstreamLineageEdgeId: "edge-l3-aaa",
    confidence: 0.85,
    strategy: "lineage_edge",
    reasoning: "dbt-manifest edge mapped src.user_id → tgt.user_id",
    evidence: { upstream_edge_strategy: "dbt_manifest" },
    state: "proposed",
    stateChangedAt: "2026-06-02T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("SchemaImpactRow", () => {
  it("renders change description, downstream target, badges, confidence, and strategy", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <SchemaImpactRow
            impact={makeImpact({ confidence: 0.85 })}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByTestId("schema-impact-row-impact-001")).toBeInTheDocument();
    expect(
      screen.getByTestId("schema-impact-confidence-impact-001"),
    ).toHaveTextContent("85%");
    expect(
      screen.getByTestId("schema-impact-change-kind-impact-001"),
    ).toHaveTextContent("column_type_changed");
    expect(
      screen.getByTestId("schema-impact-impact-kind-impact-001"),
    ).toHaveTextContent("tgt_column_type_mismatch");
    expect(
      screen.getByTestId("schema-impact-strategy-impact-001"),
    ).toHaveTextContent("lineage_edge");
    expect(
      screen.getByTestId("schema-impact-target-impact-001"),
    ).toHaveTextContent("dbt.dim_users");
  });

  it("renders cross-axis 'view L3 edge' link when upstreamLineageEdgeId is set", () => {
    render(
      <table>
        <tbody>
          <SchemaImpactRow
            impact={makeImpact({
              upstreamLineageEdgeId: "edge-l3-aaa",
              strategy: "lineage_edge",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const link = screen.getByTestId(
      "schema-impact-l3-link-impact-001",
    ) as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    // Cross-axis nav target shape: /lake/lineage?edge_id=<encoded-id>.
    expect(link.getAttribute("href")).toBe("/lake/lineage?edge_id=edge-l3-aaa");
  });

  it("renders NO L3 link when upstreamLineageEdgeId is null (type_coercion strategy)", () => {
    render(
      <table>
        <tbody>
          <SchemaImpactRow
            impact={makeImpact({
              impactId: "impact-tc",
              upstreamLineageEdgeId: null,
              strategy: "type_coercion",
              impactKind: "type_coercion_required",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    // Per handoff concern #3 — no dead links. When the field is null,
    // the link slot stays empty.
    expect(
      screen.queryByTestId("schema-impact-l3-link-impact-tc"),
    ).toBeNull();
  });

  it("invokes onConfirm with the impact when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const impact = makeImpact();
    render(
      <table>
        <tbody>
          <SchemaImpactRow
            impact={impact}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("schema-impact-confirm-impact-001"));
    expect(onConfirm).toHaveBeenCalledWith(impact);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <SchemaImpactRow
            impact={makeImpact()}
            disabled
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "schema-impact-confirm-impact-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "schema-impact-reject-impact-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });
});
