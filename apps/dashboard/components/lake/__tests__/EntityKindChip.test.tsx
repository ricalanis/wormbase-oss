/**
 * EntityKindChip component tests — L8 Sub-wave D (2026-06-07).
 *
 * Pins the 8-value EntityKind chip discipline:
 *   * All 8 values render successfully with a distinct ``data-kind``
 *     attribute and accessible aria-label.
 *   * The ``other`` chip carries ``data-unclassified="true"`` and a
 *     muted "(unclassified)" aria-label — per Sub-wave C handoff
 *     concern #4 (NameMatch fuzzy-name path always emits ``other``).
 *   * The 7 named kinds carry ``data-unclassified="false"``.
 *   * Each chip's testid is suffixed with the provided ``testIdSuffix``
 *     so multiple chips on a page get unique ids.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EntityKindChip } from "../EntityKindChip";
import type { EntityKind } from "../../../lib/entity-stitches";

const ALL_KINDS: EntityKind[] = [
  "person",
  "organization",
  "transaction",
  "product",
  "event",
  "location",
  "session",
  "other",
];

describe("EntityKindChip", () => {
  it("renders all 8 entity_kind values with distinct data-kind attributes", () => {
    for (const kind of ALL_KINDS) {
      const { unmount } = render(
        <EntityKindChip kind={kind} testIdSuffix={kind} />,
      );
      const chip = screen.getByTestId(`entity-stitch-kind-chip-${kind}`);
      expect(chip.getAttribute("data-kind")).toBe(kind);
      expect(chip.textContent).toContain(kind);
      unmount();
    }
  });

  it("renders 'other' chip with data-unclassified=true (the 'unclassified' tier per handoff concern #4)", () => {
    render(<EntityKindChip kind="other" testIdSuffix="row-1" />);
    const chip = screen.getByTestId("entity-stitch-kind-chip-row-1");
    expect(chip.getAttribute("data-kind")).toBe("other");
    expect(chip.getAttribute("data-unclassified")).toBe("true");
    expect(chip.getAttribute("aria-label")).toContain("unclassified");
  });

  it("renders the 7 named kinds with data-unclassified=false", () => {
    const named: EntityKind[] = [
      "person",
      "organization",
      "transaction",
      "product",
      "event",
      "location",
      "session",
    ];
    for (const kind of named) {
      const { unmount } = render(
        <EntityKindChip kind={kind} testIdSuffix={`r-${kind}`} />,
      );
      const chip = screen.getByTestId(`entity-stitch-kind-chip-r-${kind}`);
      expect(chip.getAttribute("data-unclassified")).toBe("false");
      expect(chip.getAttribute("aria-label")).not.toContain("unclassified");
      unmount();
    }
  });

  it("emits unique data-testid per testIdSuffix so multiple chips coexist on a page", () => {
    render(
      <>
        <EntityKindChip kind="person" testIdSuffix="stitch-001" />
        <EntityKindChip kind="organization" testIdSuffix="stitch-002" />
        <EntityKindChip kind="other" testIdSuffix="stitch-003" />
      </>,
    );
    expect(
      screen.getByTestId("entity-stitch-kind-chip-stitch-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-kind-chip-stitch-002"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("entity-stitch-kind-chip-stitch-003"),
    ).toBeInTheDocument();
  });

  it("renders distinct colored chip styles per kind (sanity check on inline style border)", () => {
    // Each kind picks a different border color from the palette; we
    // can't trivially assert exact colors (CSS-var fallbacks), but
    // confirm the border is set and varies between non-`other` and
    // `other` tiers.
    const { unmount: u1 } = render(
      <EntityKindChip kind="person" testIdSuffix="a" />,
    );
    const personChip = screen.getByTestId("entity-stitch-kind-chip-a");
    const personBorder = personChip.getAttribute("style") ?? "";
    expect(personBorder).toContain("border");
    u1();

    const { unmount: u2 } = render(
      <EntityKindChip kind="other" testIdSuffix="b" />,
    );
    const otherChip = screen.getByTestId("entity-stitch-kind-chip-b");
    const otherBorder = otherChip.getAttribute("style") ?? "";
    expect(otherBorder).toContain("border");
    // Other tier carries reduced opacity per the muted slate
    // discipline (handoff concern #4).
    expect(otherBorder).toContain("opacity");
    u2();
  });
});
