/**
 * EntityStitchesTable component tests — L8 Sub-wave D (2026-06-07).
 *
 * Pins:
 *   * High-density advisory renders ONLY when rows > 200 (per Sub-wave
 *     C handoff concern #2 — pair enumeration is O(N²)).
 *   * Group-by default is ``entity_kind`` so the 8-color chip
 *     discipline serves as the primary visual organizer.
 *   * Read-only (non-admin) hint surfaces in the header copy.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { EntityStitchesTable, HIGH_DENSITY_THRESHOLD } from "../EntityStitchesTable";
import type {
  EntityKind,
  EntityStitchRow as EntityStitchRowData,
} from "../../../lib/entity-stitches";

// Stub next/navigation so the client component can call router.refresh().
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

function makeProposal(
  i: number,
  partial: Partial<EntityStitchRowData> = {},
): EntityStitchRowData {
  const base: EntityStitchRowData = {
    stitchId: `stitch-${String(i).padStart(4, "0")}`,
    srcSourceIdA: "crm",
    srcTableA: "crm.contacts",
    srcColumnA: "email",
    srcSourceIdB: "app",
    srcTableB: "app.users",
    srcColumnB: "email_address",
    upstreamSemanticTypeId: null,
    entityKind: "other" as EntityKind,
    confidence: 0.7,
    strategy: "name_match",
    reasoning: "fuzzy-name",
    evidence: {},
    state: "proposed",
    stateChangedAt: "2026-06-07T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("EntityStitchesTable — high-density advisory (handoff concern #2)", () => {
  it("does NOT render the advisory at the threshold or below", async () => {
    const confirmAction = vi.fn();
    const rejectAction = vi.fn();
    const rows = Array.from({ length: HIGH_DENSITY_THRESHOLD }, (_, i) =>
      makeProposal(i),
    );
    render(
      <EntityStitchesTable
        rows={rows}
        isAdmin
        confirmAction={confirmAction}
        rejectAction={rejectAction}
      />,
    );
    expect(
      screen.queryByTestId("entity-stitch-high-density-advisory"),
    ).toBeNull();
  });

  it("renders the high-density advisory when rows > 200 (Sub-wave C concern #2)", () => {
    const confirmAction = vi.fn();
    const rejectAction = vi.fn();
    const rows = Array.from({ length: HIGH_DENSITY_THRESHOLD + 1 }, (_, i) =>
      makeProposal(i),
    );
    render(
      <EntityStitchesTable
        rows={rows}
        isAdmin
        confirmAction={confirmAction}
        rejectAction={rejectAction}
      />,
    );
    const advisory = screen.getByTestId("entity-stitch-high-density-advisory");
    expect(advisory).toBeInTheDocument();
    expect(advisory).toHaveTextContent("High density");
    expect(advisory).toHaveTextContent(String(HIGH_DENSITY_THRESHOLD + 1));
  });
});

describe("EntityStitchesTable — render shape", () => {
  it("renders the proposals section + group-by select defaulting to entity_kind", () => {
    render(
      <EntityStitchesTable
        rows={[
          makeProposal(1, { entityKind: "person" }),
          makeProposal(2, { entityKind: "other" }),
        ]}
        isAdmin
        confirmAction={vi.fn()}
        rejectAction={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("entity-stitch-proposals-section"),
    ).toBeInTheDocument();
    const groupBy = screen.getByTestId(
      "entity-stitch-group-by",
    ) as HTMLSelectElement;
    expect(groupBy.value).toBe("entity_kind");
  });

  it("surfaces read-only hint in copy when isAdmin=false", () => {
    render(
      <EntityStitchesTable
        rows={[makeProposal(1)]}
        isAdmin={false}
        confirmAction={vi.fn()}
        rejectAction={vi.fn()}
      />,
    );
    const section = screen.getByTestId("entity-stitch-proposals-section");
    expect(section).toHaveTextContent("Read-only");
  });

  it("renders the dedup-window footnote", () => {
    render(
      <EntityStitchesTable
        rows={[makeProposal(1)]}
        isAdmin
        confirmAction={vi.fn()}
        rejectAction={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("entity-stitch-window-footnote"),
    ).toHaveTextContent("PROPOSE_WINDOW_SECONDS");
  });
});
