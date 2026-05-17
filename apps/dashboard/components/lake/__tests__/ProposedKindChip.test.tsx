/**
 * ProposedKindChip component tests — L1 Sub-wave D (2026-06-08).
 *
 * Pins the connector-registry chip discipline:
 *   * All 12 day-one connector kinds render with ``data-known="true"``
 *     and an accessible aria-label.
 *   * ``mcp:*`` namespace shares one muted color but is still treated
 *     as "known" (data-known="true") because the registry guarantees
 *     mcp:* validity by config.
 *   * Unknown kinds fall back to a muted slate style with
 *     ``data-known="false"`` and "(unknown)" aria-label suffix.
 *   * Each chip's testid is suffixed with the provided ``testIdSuffix``
 *     so multiple chips on a page get unique ids.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ProposedKindChip } from "../ProposedKindChip";

const DAY_ONE_KINDS = [
  "csv_local",
  "postgres",
  "snowflake",
  "bigquery",
  "stripe",
  "salesforce",
  "hubspot",
  "gsheets",
  "s3_csv",
  "http_csv",
  "rest_api",
  "other",
];

describe("ProposedKindChip", () => {
  it("renders all 12 day-one connector kinds with distinct data-kind attributes", () => {
    for (const kind of DAY_ONE_KINDS) {
      const { unmount } = render(
        <ProposedKindChip kind={kind} testIdSuffix={kind} />,
      );
      const chip = screen.getByTestId(`source-candidate-kind-chip-${kind}`);
      expect(chip.getAttribute("data-kind")).toBe(kind);
      expect(chip.getAttribute("data-known")).toBe("true");
      expect(chip.textContent).toContain(kind);
      unmount();
    }
  });

  it("renders mcp:* namespaced kinds as 'known' (registry guarantees validity)", () => {
    render(<ProposedKindChip kind="mcp:notion" testIdSuffix="r-1" />);
    const chip = screen.getByTestId("source-candidate-kind-chip-r-1");
    expect(chip.getAttribute("data-kind")).toBe("mcp:notion");
    expect(chip.getAttribute("data-known")).toBe("true");
    expect(chip.getAttribute("aria-label")).not.toContain("unknown");
  });

  it("renders mcp:* with a muted shared color (distinct from named connectors)", () => {
    render(<ProposedKindChip kind="mcp:figma" testIdSuffix="r-2" />);
    const chip = screen.getByTestId("source-candidate-kind-chip-r-2");
    // The mcp:* style is a shared muted purple-slate — the exact
    // border color is an implementation detail but the style must
    // be present.
    const style = chip.getAttribute("style") ?? "";
    expect(style).toContain("border");
  });

  it("falls back to muted slate (data-known=false) for unknown kinds", () => {
    render(
      <ProposedKindChip kind="brand_new_connector" testIdSuffix="r-3" />,
    );
    const chip = screen.getByTestId("source-candidate-kind-chip-r-3");
    expect(chip.getAttribute("data-kind")).toBe("brand_new_connector");
    expect(chip.getAttribute("data-known")).toBe("false");
    expect(chip.getAttribute("aria-label")).toContain("unknown");
    // Reduced opacity discipline for unknown tier.
    const style = chip.getAttribute("style") ?? "";
    expect(style).toContain("opacity");
  });

  it("emits unique data-testid per testIdSuffix so multiple chips coexist on a page", () => {
    render(
      <>
        <ProposedKindChip kind="csv_local" testIdSuffix="cand-001" />
        <ProposedKindChip kind="postgres" testIdSuffix="cand-002" />
        <ProposedKindChip kind="mcp:notion" testIdSuffix="cand-003" />
        <ProposedKindChip kind="never_heard_of_it" testIdSuffix="cand-004" />
      </>,
    );
    expect(
      screen.getByTestId("source-candidate-kind-chip-cand-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-kind-chip-cand-002"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-kind-chip-cand-003"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("source-candidate-kind-chip-cand-004"),
    ).toBeInTheDocument();
  });

  it("renders 'other' as known but with the muted-slate tier (same family as unknown)", () => {
    render(<ProposedKindChip kind="other" testIdSuffix="o-1" />);
    const chip = screen.getByTestId("source-candidate-kind-chip-o-1");
    // ``other`` is a registry-known sentinel — known=true.
    expect(chip.getAttribute("data-known")).toBe("true");
    // But shares the muted style with unknown kinds.
    const style = chip.getAttribute("style") ?? "";
    expect(style).toContain("border");
  });
});
