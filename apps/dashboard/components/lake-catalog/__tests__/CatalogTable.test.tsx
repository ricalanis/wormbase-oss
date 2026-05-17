/**
 * Tests for CatalogTable (Wave 3 Task 1).
 *
 * Pure presentational; the page handles the empty state. These tests
 * pin:
 *
 *   * One ``<tr>`` per row plus the header row
 *   * The source-id link points to the per-source detail route
 *   * Sortable header — clicking a column header re-orders rows
 *   * Initial-vs-refresh import_mode pill renders distinctly
 *
 * jsdom-flavoured DOM (vitest); no Next router or server-side
 * concerns needed because this is a "use client" component.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CatalogTable } from "../CatalogTable";
import type { CatalogTable as CatalogTableRow } from "../../../lib/lake-catalog";

function row(
  partial: Partial<CatalogTableRow> &
    Pick<CatalogTableRow, "sourceId" | "sourceKind">,
): CatalogTableRow {
  return {
    sourceId: partial.sourceId,
    sourceKind: partial.sourceKind,
    domainId:
      partial.domainId ?? "11111111-1111-1111-1111-111111111111",
    snapshotHash: partial.snapshotHash ?? "deadbeefcafefeed",
    tableCount: partial.tableCount ?? 0,
    edgeCount: partial.edgeCount ?? 0,
    metricCount: partial.metricCount ?? 0,
    importMode: partial.importMode ?? "initial",
    upstreamLineageCount: partial.upstreamLineageCount ?? 0,
    downstreamLineageCount: partial.downstreamLineageCount ?? 0,
    importedAt: partial.importedAt ?? "2026-05-11T10:00:00.000Z",
  };
}

describe("CatalogTable", () => {
  it("renders one row per snapshot", () => {
    const rows = [
      row({
        sourceId: "00000000-0000-0000-0000-000000000001",
        sourceKind: "dbt",
        tableCount: 12,
      }),
      row({
        sourceId: "00000000-0000-0000-0000-000000000002",
        sourceKind: "snowflake_native",
        tableCount: 38,
      }),
    ];
    render(<CatalogTable rows={rows} />);
    expect(
      screen.getByTestId("catalog-row-00000000-0000-0000-0000-000000000001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-row-00000000-0000-0000-0000-000000000002"),
    ).toBeInTheDocument();
  });

  it("emits a click-through link to the per-source detail route", () => {
    const rows = [
      row({
        sourceId: "abc12345-0000-0000-0000-000000000001",
        sourceKind: "dbt",
      }),
    ];
    render(<CatalogTable rows={rows} />);
    const link = screen.getByTestId(
      "catalog-row-link-abc12345-0000-0000-0000-000000000001",
    );
    expect(link).toHaveAttribute(
      "href",
      "/lake/catalog/abc12345-0000-0000-0000-000000000001",
    );
  });

  it("re-orders rows when a header is clicked", () => {
    const rows = [
      row({
        sourceId: "00000000-0000-0000-0000-000000000001",
        sourceKind: "dbt",
        tableCount: 5,
        importedAt: "2026-05-10T10:00:00.000Z",
      }),
      row({
        sourceId: "00000000-0000-0000-0000-000000000002",
        sourceKind: "snowflake_native",
        tableCount: 50,
        importedAt: "2026-05-09T10:00:00.000Z",
      }),
    ];
    render(<CatalogTable rows={rows} />);

    // Default sort: importedAt desc → dbt (May 10) first.
    let bodyRows = screen.getAllByTestId(/^catalog-row-/);
    expect(bodyRows[0].getAttribute("data-testid")).toContain(
      "00000000-0000-0000-0000-000000000001",
    );

    // Click tableCount header — numeric default desc → snowflake (50) first.
    fireEvent.click(screen.getByTestId("catalog-th-tableCount"));
    bodyRows = screen.getAllByTestId(/^catalog-row-/);
    expect(bodyRows[0].getAttribute("data-testid")).toContain(
      "00000000-0000-0000-0000-000000000002",
    );

    // Clicking the same header again flips direction → asc → dbt (5) first.
    fireEvent.click(screen.getByTestId("catalog-th-tableCount"));
    bodyRows = screen.getAllByTestId(/^catalog-row-/);
    expect(bodyRows[0].getAttribute("data-testid")).toContain(
      "00000000-0000-0000-0000-000000000001",
    );
  });

  it("renders the import_mode pill distinctly for initial vs refresh", () => {
    const rows = [
      row({
        sourceId: "00000000-0000-0000-0000-000000000001",
        sourceKind: "dbt",
        importMode: "initial",
      }),
      row({
        sourceId: "00000000-0000-0000-0000-000000000002",
        sourceKind: "snowflake_native",
        importMode: "refresh",
      }),
    ];
    render(<CatalogTable rows={rows} />);
    // One initial pill + one refresh pill, both present.
    expect(screen.getAllByTestId("catalog-mode-initial")).toHaveLength(1);
    expect(screen.getAllByTestId("catalog-mode-refresh")).toHaveLength(1);
  });

  it("surfaces lineage counts in dedicated columns", () => {
    const rows = [
      row({
        sourceId: "00000000-0000-0000-0000-000000000001",
        sourceKind: "dbt",
        upstreamLineageCount: 12,
        downstreamLineageCount: 7,
      }),
    ];
    render(<CatalogTable rows={rows} />);
    const tr = screen.getByTestId(
      "catalog-row-00000000-0000-0000-0000-000000000001",
    );
    // Match the cell text via inspection on the parent row.
    expect(tr.textContent).toContain("12");
    expect(tr.textContent).toContain("7");
  });
});
