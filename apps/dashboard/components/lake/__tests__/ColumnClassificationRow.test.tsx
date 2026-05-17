/**
 * ColumnClassificationRow component tests — L6 Sub-wave D (2026-06-06).
 *
 * Pins:
 *   * Render shape (table.column, classification_level chip,
 *     confidence, strategy badge, Confirm + Reject buttons).
 *   * 5-value classification_level chip with regulated visual
 *     distinction — ``regulated`` carries the lock glyph prefix +
 *     data-regulated="true" attribute. Other 4 levels carry
 *     data-regulated="false".
 *   * Cross-axis link to L5 — rows with ``upstreamSemanticTypeId`` set
 *     render "view L5 semantic type →" link to
 *     ``/lake/semantic-types?type_id=<id>``; rows without it (e.g.
 *     ``naming_pattern`` / ``domain_default``) render NO link at all
 *     (no dead links — matches L4→L3 SchemaImpactRow contract).
 *   * Confirm + Reject button callbacks fire with the row data.
 *   * disabled={true} suppresses both action callbacks (non-admin
 *     lens).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ColumnClassificationRow } from "../ColumnClassificationRow";
import type {
  ClassificationLevel,
  ColumnClassificationRow as ColumnClassificationRowData,
} from "../../../lib/column-classification";

function makeProposal(
  partial: Partial<ColumnClassificationRowData> = {},
): ColumnClassificationRowData {
  const base: ColumnClassificationRowData = {
    classificationId: "cls-001",
    tableId: "raw.users",
    column: "ssn",
    classificationLevel: "regulated" as ClassificationLevel,
    upstreamSemanticTypeId: "type-pii-ssn-001",
    confidence: 0.95,
    strategy: "semantic_type",
    reasoning: "L5 confirmed pii_ssn → governance regulated",
    evidence: { semantic_type: "pii_ssn", regex_hit: true },
    state: "proposed",
    stateChangedAt: "2026-06-06T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("ColumnClassificationRow", () => {
  it("renders table.column, classification_level chip, confidence, and strategy", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({ confidence: 0.95 })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("column-classification-row-cls-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("column-classification-target-cls-001"),
    ).toHaveTextContent("raw.users");
    expect(
      screen.getByTestId("column-classification-confidence-cls-001"),
    ).toHaveTextContent("95%");
    expect(
      screen.getByTestId("column-classification-strategy-cls-001"),
    ).toHaveTextContent("semantic_type");
  });

  it("renders the regulated chip with lock glyph + data-regulated=true distinction", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({
              classificationLevel: "regulated",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const chip = screen.getByTestId(
      "column-classification-level-chip-cls-001",
    );
    expect(chip.getAttribute("data-level")).toBe("regulated");
    expect(chip.getAttribute("data-regulated")).toBe("true");
    // Lock glyph (U+1F512) is the visual distinguisher.
    expect(chip.textContent).toContain("\u{1F512}");
    expect(chip.textContent).toContain("regulated");
  });

  it("renders the pii chip WITHOUT the lock glyph (data-regulated=false)", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({
              classificationLevel: "pii",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const chip = screen.getByTestId(
      "column-classification-level-chip-cls-001",
    );
    expect(chip.getAttribute("data-level")).toBe("pii");
    expect(chip.getAttribute("data-regulated")).toBe("false");
    expect(chip.textContent).not.toContain("\u{1F512}");
    expect(chip.textContent).toContain("pii");
  });

  it("renders the public/internal/confidential chips with data-regulated=false", () => {
    const levels: ClassificationLevel[] = [
      "public",
      "internal",
      "confidential",
    ];
    for (const level of levels) {
      const { unmount } = render(
        <table>
          <tbody>
            <ColumnClassificationRow
              proposal={makeProposal({
                classificationId: `cls-${level}`,
                classificationLevel: level,
              })}
              onConfirm={vi.fn()}
              onReject={vi.fn()}
            />
          </tbody>
        </table>,
      );
      const chip = screen.getByTestId(
        `column-classification-level-chip-cls-${level}`,
      );
      expect(chip.getAttribute("data-level")).toBe(level);
      expect(chip.getAttribute("data-regulated")).toBe("false");
      expect(chip.textContent).not.toContain("\u{1F512}");
      expect(chip.textContent).toContain(level);
      unmount();
    }
  });

  it("renders cross-axis 'view L5 semantic type' link when upstreamSemanticTypeId is set", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({
              upstreamSemanticTypeId: "type-pii-ssn-001",
              strategy: "semantic_type",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const link = screen.getByTestId(
      "column-classification-l5-link-cls-001",
    ) as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    // Cross-axis nav target shape: /lake/semantic-types?type_id=<encoded-id>.
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=type-pii-ssn-001",
    );
  });

  it("renders NO L5 link when upstreamSemanticTypeId is null (naming_pattern strategy)", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({
              classificationId: "cls-np",
              upstreamSemanticTypeId: null,
              strategy: "naming_pattern",
              classificationLevel: "confidential",
              column: "api_secret",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    // No dead links — matches L4→L3 cross-axis-link contract.
    expect(
      screen.queryByTestId("column-classification-l5-link-cls-np"),
    ).toBeNull();
  });

  it("renders NO L5 link when upstreamSemanticTypeId is null (domain_default strategy)", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal({
              classificationId: "cls-dd",
              upstreamSemanticTypeId: null,
              strategy: "domain_default",
              classificationLevel: "internal",
              confidence: 0.6,
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("column-classification-l5-link-cls-dd"),
    ).toBeNull();
  });

  it("invokes onConfirm with the proposal when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const proposal = makeProposal();
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={proposal}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(
      screen.getByTestId("column-classification-confirm-cls-001"),
    );
    expect(onConfirm).toHaveBeenCalledWith(proposal);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal()}
            disabled
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "column-classification-confirm-cls-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "column-classification-reject-cls-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });

  // ─── R5 L4↦L6 reverse-arc badge (Recipe Addendum #3) ──────────────

  it("does NOT render the impact-count badge when impactCount is undefined", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("column-classification-impact-badge-cls-001"),
    ).not.toBeInTheDocument();
  });

  it("does NOT render the impact-count badge when impactCount is 0", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={0}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("column-classification-impact-badge-cls-001"),
    ).not.toBeInTheDocument();
  });

  it("renders an impact-count badge when impactCount > 0 with classification id encoded in href", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={4}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "column-classification-impact-badge-cls-001",
    );
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("4 impact proposals via L4");
    const href = badge.getAttribute("href") ?? "";
    expect(href).toContain("/lake/schema-impact?");
    expect(href).toContain("upstream_classification_id=cls-001");
  });

  it("uses singular 'impact proposal' when impactCount === 1", () => {
    render(
      <table>
        <tbody>
          <ColumnClassificationRow
            proposal={makeProposal()}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("column-classification-impact-badge-cls-001"),
    ).toHaveTextContent("1 impact proposal via L4");
  });
});
