/**
 * SemanticTypeRow component tests — L5 Sub-wave D (2026-06-05).
 *
 * Pins:
 *   * Render shape (table.column, semantic_type badge, confidence,
 *     strategy badge, Confirm + Reject buttons).
 *   * PII-band semantic types render the sensitivity chip; non-PII
 *     types do not.
 *   * Confirm + Reject button callbacks fire with the row data.
 *   * disabled={true} suppresses both action callbacks (non-admin lens).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SemanticTypeRow } from "../SemanticTypeRow";
import type {
  SemanticTypeRow as SemanticTypeRowData,
  SemanticTypeValue,
} from "../../../lib/semantic-types";

function makeProposal(
  partial: Partial<SemanticTypeRowData> = {},
): SemanticTypeRowData {
  const base: SemanticTypeRowData = {
    typeId: "type-email-001",
    tableId: "dbt.dim_users",
    column: "email_address",
    semanticType: "email" as SemanticTypeValue,
    confidence: 0.95,
    strategy: "column_name",
    reasoning: "column name matches email regex /^email/i",
    evidence: { matched_regex: "^email" },
    state: "proposed",
    stateChangedAt: "2026-06-05T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("SemanticTypeRow", () => {
  it("renders table.column, semantic_type badge, confidence, and strategy", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal({ confidence: 0.95 })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("semantic-type-row-type-email-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("semantic-type-target-type-email-001"),
    ).toHaveTextContent("dbt.dim_users");
    expect(
      screen.getByTestId("semantic-type-kind-type-email-001"),
    ).toHaveTextContent("email");
    expect(
      screen.getByTestId("semantic-type-confidence-type-email-001"),
    ).toHaveTextContent("95%");
    expect(
      screen.getByTestId("semantic-type-strategy-type-email-001"),
    ).toHaveTextContent("column_name");
  });

  it("renders the PII sensitivity chip for pii_credit_card (PII band)", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal({
              typeId: "type-cc-001",
              column: "card_number",
              semanticType: "pii_credit_card",
              strategy: "value_pattern",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("semantic-type-pii-chip-type-cc-001"),
    ).toHaveTextContent(/pii/i);
  });

  it("renders NO PII chip for non-PII types (e.g. email)", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal({ semanticType: "email" })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("semantic-type-pii-chip-type-email-001"),
    ).toBeNull();
  });

  it("invokes onConfirm with the proposal when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const proposal = makeProposal();
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={proposal}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("semantic-type-confirm-type-email-001"));
    expect(onConfirm).toHaveBeenCalledWith(proposal);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            disabled
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "semantic-type-confirm-type-email-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "semantic-type-reject-type-email-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });

  // ─── R2/R3/R4/R6 reverse-arc cluster (Recipe Addendum #3) ─────────

  it("does NOT render the downstream cluster when all 4 counts are undefined", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId(
        "semantic-type-downstream-cluster-type-email-001",
      ),
    ).not.toBeInTheDocument();
  });

  it("does NOT render the downstream cluster when all 4 counts are 0", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            classificationCount={0}
            entityStitchCount={0}
            qualityCount={0}
            impactCount={0}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId(
        "semantic-type-downstream-cluster-type-email-001",
      ),
    ).not.toBeInTheDocument();
  });

  it("renders all 4 chips when all 4 counts > 0", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            classificationCount={5}
            entityStitchCount={2}
            qualityCount={3}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("semantic-type-downstream-cluster-type-email-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(
        "semantic-type-downstream-classification-type-email-001",
      ),
    ).toHaveTextContent("5 classifications via L6");
    expect(
      screen.getByTestId(
        "semantic-type-downstream-entity-stitch-type-email-001",
      ),
    ).toHaveTextContent("2 entity stitches via L8");
    expect(
      screen.getByTestId(
        "semantic-type-downstream-quality-type-email-001",
      ),
    ).toHaveTextContent("3 quality checks via L7");
    expect(
      screen.getByTestId(
        "semantic-type-downstream-impact-type-email-001",
      ),
    ).toHaveTextContent("1 impact proposal via L4");
  });

  it("renders ONLY the populated chips (e.g. only L6 + L4)", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            classificationCount={2}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId(
        "semantic-type-downstream-classification-type-email-001",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(
        "semantic-type-downstream-impact-type-email-001",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId(
        "semantic-type-downstream-entity-stitch-type-email-001",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId(
        "semantic-type-downstream-quality-type-email-001",
      ),
    ).not.toBeInTheDocument();
  });

  it("downstream chip hrefs encode the semantic_type_id", () => {
    render(
      <table>
        <tbody>
          <SemanticTypeRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            classificationCount={2}
          />
        </tbody>
      </table>,
    );
    const chip = screen.getByTestId(
      "semantic-type-downstream-classification-type-email-001",
    );
    const href = chip.getAttribute("href") ?? "";
    expect(href).toBe(
      "/lake/column-classification?upstream_semantic_type_id=type-email-001",
    );
  });
});
