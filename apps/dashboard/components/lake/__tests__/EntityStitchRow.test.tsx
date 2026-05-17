/**
 * EntityStitchRow component tests — L8 Sub-wave D (2026-06-07).
 *
 * Pins:
 *   * Render shape (src_a.col_a ↔ src_b.col_b pair, entity_kind chip,
 *     confidence, strategy badge, Confirm + Reject buttons).
 *   * Cross-axis link to L5 — rows with ``upstreamSemanticTypeId`` set
 *     render "view L5 semantic type →" link to
 *     ``/lake/semantic-types?type_id=<id>``; rows without it (e.g.
 *     fuzzy-name-only / sample_overlap / schema_shape) render NO link
 *     (no dead links — matches L6→L5 contract).
 *   * Confirm + Reject button callbacks fire with the row data.
 *   * disabled={true} suppresses both action callbacks (non-admin lens).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { EntityStitchRow } from "../EntityStitchRow";
import type {
  EntityKind,
  EntityStitchRow as EntityStitchRowData,
} from "../../../lib/entity-stitches";

function makeProposal(
  partial: Partial<EntityStitchRowData> = {},
): EntityStitchRowData {
  const base: EntityStitchRowData = {
    stitchId: "stitch-001",
    srcSourceIdA: "crm",
    srcTableA: "crm.contacts",
    srcColumnA: "email",
    srcSourceIdB: "app",
    srcTableB: "app.users",
    srcColumnB: "email_address",
    upstreamSemanticTypeId: "type-email-001",
    entityKind: "person" as EntityKind,
    confidence: 0.9,
    strategy: "name_match",
    reasoning: "L5 confirmed shared semantic type email",
    evidence: { path: "semantic_type_anchor", shared_semantic_type: "email" },
    state: "proposed",
    stateChangedAt: "2026-06-07T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("EntityStitchRow", () => {
  it("renders the endpoint pair (a ↔ b), entity_kind chip, confidence, strategy", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal({ confidence: 0.9 })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByTestId("entity-stitch-row-stitch-001")).toBeInTheDocument();
    const pair = screen.getByTestId("entity-stitch-pair-stitch-001");
    expect(pair).toHaveTextContent("crm.contacts");
    expect(pair).toHaveTextContent("email");
    expect(pair).toHaveTextContent("app.users");
    expect(pair).toHaveTextContent("email_address");
    expect(pair).toHaveTextContent("↔");
    expect(
      screen.getByTestId("entity-stitch-confidence-stitch-001"),
    ).toHaveTextContent("90%");
    expect(
      screen.getByTestId("entity-stitch-strategy-stitch-001"),
    ).toHaveTextContent("name_match");
    // EntityKindChip child renders with the row testIdSuffix.
    expect(
      screen.getByTestId("entity-stitch-kind-chip-stitch-001"),
    ).toHaveAttribute("data-kind", "person");
  });

  it("renders cross-axis 'view L5 semantic type' link when upstreamSemanticTypeId is set", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal({
              upstreamSemanticTypeId: "type-email-001",
              strategy: "name_match",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const link = screen.getByTestId(
      "entity-stitch-l5-link-stitch-001",
    ) as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe(
      "/lake/semantic-types?type_id=type-email-001",
    );
  });

  it("renders NO L5 link when upstreamSemanticTypeId is null (fuzzy-name-only)", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal({
              stitchId: "stitch-fuzzy",
              upstreamSemanticTypeId: null,
              strategy: "name_match",
              entityKind: "other",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("entity-stitch-l5-link-stitch-fuzzy"),
    ).toBeNull();
  });

  it("renders NO L5 link for sample_overlap rows (no upstream)", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal({
              stitchId: "stitch-so",
              upstreamSemanticTypeId: null,
              strategy: "sample_overlap",
              entityKind: "transaction",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(screen.queryByTestId("entity-stitch-l5-link-stitch-so")).toBeNull();
  });

  it("renders 'other' entity_kind as the muted unclassified tier (handoff concern #4)", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal({
              stitchId: "stitch-other",
              entityKind: "other",
            })}
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const chip = screen.getByTestId("entity-stitch-kind-chip-stitch-other");
    expect(chip.getAttribute("data-unclassified")).toBe("true");
  });

  it("invokes onConfirm with the proposal when Confirm is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const proposal = makeProposal();
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={proposal}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("entity-stitch-confirm-stitch-001"));
    expect(onConfirm).toHaveBeenCalledWith(proposal);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("invokes onReject with the proposal when Reject is clicked", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const proposal = makeProposal();
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={proposal}
            onConfirm={onConfirm}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("entity-stitch-reject-stitch-001"));
    expect(onReject).toHaveBeenCalledWith(proposal);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons when disabled=true (non-admin lens)", () => {
    render(
      <table>
        <tbody>
          <EntityStitchRow
            proposal={makeProposal()}
            disabled
            onConfirm={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    const confirm = screen.getByTestId(
      "entity-stitch-confirm-stitch-001",
    ) as HTMLButtonElement;
    const reject = screen.getByTestId(
      "entity-stitch-reject-stitch-001",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reject.disabled).toBe(true);
  });
});
