/**
 * DriftKindChip component tests — L2 Sub-wave D (2026-06-09).
 *
 * Pins the 5-value strict drift_kind chip discipline:
 *   * All 5 enum values render with ``data-known="true"`` and a
 *     deterministic accessible aria-label.
 *   * Each enum value gets a distinct color signature (verified by
 *     reading the inline style border color).
 *   * Out-of-enum values fall back to muted neutral with
 *     ``data-known="false"`` and "(unknown)" aria-label suffix.
 *   * Each chip's testid is suffixed with the provided ``testIdSuffix``
 *     so multiple chips on a page get unique ids.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { DriftKindChip } from "../DriftKindChip";

const ENUM_VALUES = [
  "table_added",
  "table_removed",
  "column_added",
  "column_removed",
  "column_type_changed",
] as const;

describe("DriftKindChip", () => {
  it("renders all 5 enum values with data-known='true' + distinct data-kind", () => {
    for (const kind of ENUM_VALUES) {
      const { unmount } = render(
        <DriftKindChip kind={kind} testIdSuffix={kind} />,
      );
      const chip = screen.getByTestId(`catalog-drift-kind-chip-${kind}`);
      expect(chip.getAttribute("data-kind")).toBe(kind);
      expect(chip.getAttribute("data-known")).toBe("true");
      expect(chip.textContent).toContain(kind);
      expect(chip.getAttribute("aria-label")).not.toContain("unknown");
      unmount();
    }
  });

  it("renders distinct color signatures across the 5 enum values", () => {
    // The 5 enum values must render with distinct color signatures.
    // The chip exports a ``data-color`` attribute carrying the
    // resolved foreground token (var(...) or raw hex) so the test
    // does not have to scrape jsdom's inline-style parsing — which
    // strips ``var(--name, fallback)`` in some configurations.
    const colors = new Set<string>();
    for (const kind of ENUM_VALUES) {
      const { unmount } = render(
        <DriftKindChip kind={kind} testIdSuffix={`b-${kind}`} />,
      );
      const chip = screen.getByTestId(`catalog-drift-kind-chip-b-${kind}`);
      const c = chip.getAttribute("data-color") ?? "";
      colors.add(c);
      unmount();
    }
    expect(colors.size).toBe(5);
  });

  it("renders table_added in additive green family", () => {
    render(<DriftKindChip kind="table_added" testIdSuffix="a-1" />);
    const chip = screen.getByTestId("catalog-drift-kind-chip-a-1");
    const color = (chip.getAttribute("data-color") ?? "").toLowerCase();
    // Botanical green is the L2-defined additive hue.
    expect(color).toMatch(/botanical-green|2d5d3a/);
  });

  it("renders table_removed in destructive red family", () => {
    render(<DriftKindChip kind="table_removed" testIdSuffix="r-1" />);
    const chip = screen.getByTestId("catalog-drift-kind-chip-r-1");
    const color = (chip.getAttribute("data-color") ?? "").toLowerCase();
    // Deep red — destructive at the table level.
    expect(color).toMatch(/a8323e/);
  });

  it("renders column_type_changed in amber warning family", () => {
    render(
      <DriftKindChip kind="column_type_changed" testIdSuffix="t-1" />,
    );
    const chip = screen.getByTestId("catalog-drift-kind-chip-t-1");
    const color = (chip.getAttribute("data-color") ?? "").toLowerCase();
    // Amber / sepia-warning — type change is neutral / warning hue.
    expect(color).toMatch(/sepia-warning|b6741c/);
  });

  it("falls back to muted neutral (data-known=false) for out-of-enum values", () => {
    render(<DriftKindChip kind="future_kind" testIdSuffix="u-1" />);
    const chip = screen.getByTestId("catalog-drift-kind-chip-u-1");
    expect(chip.getAttribute("data-kind")).toBe("future_kind");
    expect(chip.getAttribute("data-known")).toBe("false");
    expect(chip.getAttribute("aria-label")).toContain("unknown");
    const style = chip.getAttribute("style") ?? "";
    expect(style).toContain("opacity");
  });

  it("emits unique data-testid per testIdSuffix so multiple chips coexist on a page", () => {
    render(
      <>
        <DriftKindChip kind="table_added" testIdSuffix="d-001" />
        <DriftKindChip kind="column_removed" testIdSuffix="d-002" />
        <DriftKindChip kind="column_type_changed" testIdSuffix="d-003" />
      </>,
    );
    expect(
      screen.getByTestId("catalog-drift-kind-chip-d-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-kind-chip-d-002"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-kind-chip-d-003"),
    ).toBeInTheDocument();
  });
});
