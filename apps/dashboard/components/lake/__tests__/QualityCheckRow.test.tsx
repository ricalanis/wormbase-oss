/**
 * QualityCheckRow component tests — L7 Sub-wave D.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { QualityCheckRow } from "../QualityCheckRow";
import type { QualityCheckRow as QualityCheckRowData } from "../../../lib/quality";

function makeCheck(
  partial: Partial<QualityCheckRowData> = {},
): QualityCheckRowData {
  const base: QualityCheckRowData = {
    checkId: "check-001",
    tableId: "snowflake.dbt.dim_users",
    column: "user_id",
    checkKind: "unique",
    config: {},
    confidence: 0.99,
    strategy: "dbt_tests",
    reasoning: "manifest-listed",
    evidence: {},
    state: "proposed",
    stateChangedAt: "2026-05-30T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("QualityCheckRow", () => {
  it("renders the table / column / kind / confidence / strategy cells", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck({ confidence: 0.85 })}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("quality-check-row-check-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("quality-check-confidence-check-001"),
    ).toHaveTextContent("85%");
    expect(
      screen.getByTestId("quality-check-kind-check-001"),
    ).toHaveTextContent("unique");
    expect(
      screen.getByTestId("quality-check-strategy-check-001"),
    ).toHaveTextContent("dbt_tests");
    expect(
      screen.getByTestId("quality-check-column-check-001"),
    ).toHaveTextContent("user_id");
  });

  it("renders table-level checks (column=null) with a (table-level) placeholder", () => {
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck({
              checkId: "row-count-check",
              column: null,
              checkKind: "row_count_range",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("quality-check-column-row-count-check"),
    ).toHaveTextContent("(table-level)");
  });

  it("invokes onConfirm with the check when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const check = makeCheck();
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={check}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("quality-check-confirm-check-001"));
    expect(onConfirm).toHaveBeenCalledWith(check);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("invokes onReject with the check when Reject is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const check = makeCheck();
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={check}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("quality-check-reject-check-001"));
    expect(onReject).toHaveBeenCalledWith(check);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck()}
            disabled
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "quality-check-confirm-check-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "quality-check-reject-check-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });

  // L5→L7 cross-axis chain (4th cross-axis chain) — link rendering.
  it("renders a 'view L5 semantic type' link when evidence carries upstream_semantic_type_id", () => {
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck({
              strategy: "semantic_type",
              evidence: {
                upstream_semantic_type_id: "tid-email-001",
                semantic_type: "email",
              },
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const link = screen.getByTestId(
      "quality-check-l5-link-check-001",
    ) as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=tid-email-001",
    );
    expect(link.textContent).toContain("view L5 semantic type");
  });

  it("does NOT render the L5 link for pre-cross-axis proposals (evidence has no upstream_semantic_type_id)", () => {
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck({
              strategy: "schema_pattern",
              evidence: { match_kind: "not_null_violation" },
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("quality-check-l5-link-check-001"),
    ).not.toBeInTheDocument();
  });

  it("URL-encodes the upstream_semantic_type_id (defensive against odd ids)", () => {
    render(
      <table>
        <tbody>
          <QualityCheckRow
            check={makeCheck({
              evidence: { upstream_semantic_type_id: "tid/with spaces" },
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const link = screen.getByTestId(
      "quality-check-l5-link-check-001",
    ) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=tid%2Fwith%20spaces",
    );
  });
});
