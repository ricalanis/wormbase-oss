/**
 * CatalogDriftStrategyBanner component tests — L2 Sub-wave D
 * (2026-06-09; Catalog-mirror Wave 2 Sub-wave C posture refresh
 * 2026-06-10).
 *
 * Pins:
 *   * Renders all 3 strategy rows with the override label and the
 *     CapabilityBadges integration.
 *   * Wave 2 unified 3-state matrix for ALL three strategies
 *     (table_set / column_set / column_type) keyed on the Wave 2
 *     substrate (``projection_catalog_tables``):
 *     - disabled (master or sub-knob off)
 *     - configured · awaiting-per-table-entries (substrate ready,
 *       no entries folded for tenant)
 *     - productive · per-connector (≥1 entry folded)
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CatalogDriftStrategyBanner } from "../CatalogDriftStrategyBanner";
import type { CatalogDriftStrategyStatus } from "../../../lib/catalog-drift";

const ROW_DISABLED = (
  strategy: CatalogDriftStrategyStatus["strategy"],
): CatalogDriftStrategyStatus => ({
  strategy,
  configured: false,
  productive: false,
  badge: "disabled",
  note: "Disabled",
});

describe("CatalogDriftStrategyBanner — table_set 3-state matrix (Wave 2)", () => {
  it("renders productive · per-connector when Wave 2 substrate has entries", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      {
        strategy: "table_set",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · per-connector",
        note: "Productive — reading 5 folded catalog_table_imported entries",
      },
      ROW_DISABLED("column_set"),
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-row-table_set"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-strategy-override-table_set"),
    ).toHaveTextContent("productive · per-connector");
  });

  it("renders configured · awaiting-per-table-entries when substrate is empty", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      {
        strategy: "table_set",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-per-table-entries",
        note: "Configured — Wave 2 substrate ready; awaiting per-table entries",
      },
      ROW_DISABLED("column_set"),
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-override-table_set"),
    ).toHaveTextContent("configured · awaiting-per-table-entries");
  });

  it("renders disabled badge when knobs off (no override label)", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      ROW_DISABLED("column_set"),
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.queryByTestId("catalog-drift-strategy-override-table_set"),
    ).toBeNull();
  });
});

describe("CatalogDriftStrategyBanner — column_set 3-state matrix (Wave 2)", () => {
  it("renders productive · per-connector when Wave 2 substrate has entries", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      {
        strategy: "column_set",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · per-connector",
        note: "Productive — reading 3 folded catalog_table_imported entries",
      },
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-override-column_set"),
    ).toHaveTextContent("productive · per-connector");
  });

  it("renders configured · awaiting-per-table-entries when substrate is empty", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      {
        strategy: "column_set",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-per-table-entries",
        note: "Configured — awaiting per-table entries with populated columns",
      },
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-override-column_set"),
    ).toHaveTextContent("configured · awaiting-per-table-entries");
  });

  it("renders disabled badge when knob off (no override label)", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      ROW_DISABLED("column_set"),
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.queryByTestId("catalog-drift-strategy-override-column_set"),
    ).toBeNull();
  });
});

describe("CatalogDriftStrategyBanner — column_type 3-state matrix (Wave 2)", () => {
  it("renders productive · per-connector when Wave 2 substrate has entries", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      ROW_DISABLED("column_set"),
      {
        strategy: "column_type",
        configured: true,
        productive: true,
        badge: "production",
        badgeLabelOverride: "productive · per-connector",
        note: "Productive — reading folded catalog_table_imported entries with types",
      },
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-override-column_type"),
    ).toHaveTextContent("productive · per-connector");
  });

  it("renders configured · awaiting-per-table-entries when substrate is empty", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      ROW_DISABLED("column_set"),
      {
        strategy: "column_type",
        configured: true,
        productive: false,
        badge: "configured-stubbed",
        badgeLabelOverride: "configured · awaiting-per-table-entries",
        note: "Configured — awaiting per-table entries with populated column types",
      },
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-override-column_type"),
    ).toHaveTextContent("configured · awaiting-per-table-entries");
  });
});

describe("CatalogDriftStrategyBanner — render shape", () => {
  it("renders all three strategy rows", () => {
    const rows: CatalogDriftStrategyStatus[] = [
      ROW_DISABLED("table_set"),
      ROW_DISABLED("column_set"),
      ROW_DISABLED("column_type"),
    ];
    render(<CatalogDriftStrategyBanner rows={rows} />);
    expect(
      screen.getByTestId("catalog-drift-strategy-status-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-strategy-row-table_set"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-strategy-row-column_set"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-strategy-row-column_type"),
    ).toBeInTheDocument();
  });
});
