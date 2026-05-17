/**
 * CatalogDriftRow component tests — L2 Sub-wave D (2026-06-09).
 *
 * Pins:
 *   * Render shape (drift_kind chip + source.table[.column]
 *     identifier, before→after delta, confidence, strategy,
 *     Acknowledge + Reject buttons).
 *   * Column-level drifts render the column in the identifier path
 *     (``source.table.column``); table-level drifts render only
 *     ``source.table``.
 *   * Acknowledge + Reject button callbacks fire with the row data.
 *   * disabled={true} suppresses both action callbacks (non-admin lens).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CatalogDriftRow } from "../CatalogDriftRow";
import type { CatalogDriftRow as CatalogDriftRowData } from "../../../lib/catalog-drift";

function makeDrift(
  partial: Partial<CatalogDriftRowData> = {},
): CatalogDriftRowData {
  const base: CatalogDriftRowData = {
    driftId: "drift-001",
    sourceId: "src-postgres-prod",
    tableId: "public.orders",
    column: null,
    driftKind: "table_added",
    before: null,
    after: { table_id: "public.orders" },
    strategy: "table_set",
    reasoning: "Table appears in current snapshot but not baseline",
    confidence: 0.9,
    evidence: { before_tables: ["public.users"], after_tables: ["public.users", "public.orders"] },
    state: "proposed",
    stateChangedAt: "2026-06-09T10:00:00.000Z",
    stateChangedBy: null,
  };
  return { ...base, ...partial };
}

describe("CatalogDriftRow", () => {
  it("renders the drift_kind chip + identifier + confidence + strategy", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({ confidence: 0.9 })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("catalog-drift-row-drift-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-kind-chip-drift-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-confidence-drift-001"),
    ).toHaveTextContent("90%");
    expect(
      screen.getByTestId("catalog-drift-strategy-drift-001"),
    ).toHaveTextContent("table_set");
  });

  it("renders source.table for table-level drifts (column is null)", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              driftKind: "table_added",
              column: null,
              sourceId: "src-x",
              tableId: "schema.tbl",
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("catalog-drift-identifier-drift-001"),
    ).toHaveTextContent("src-x.schema.tbl");
  });

  it("renders source.table.column for column-level drifts", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              driftKind: "column_added",
              column: "first_seen_at",
              before: null,
              after: { column_name: "first_seen_at" },
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("catalog-drift-identifier-drift-001"),
    ).toHaveTextContent("src-postgres-prod.public.orders.first_seen_at");
  });

  it("renders the before→after delta inside the delta cell", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              driftKind: "column_type_changed",
              column: "id",
              before: { type: "int" },
              after: { type: "bigint" },
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.getByTestId("catalog-drift-delta-drift-001"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("catalog-drift-delta-before-drift-001"),
    ).toHaveTextContent("int");
    expect(
      screen.getByTestId("catalog-drift-delta-after-drift-001"),
    ).toHaveTextContent("bigint");
  });

  it("fires onAcknowledge with the row data when Acknowledge clicked", () => {
    const onAcknowledge = vi.fn();
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift()}
            onAcknowledge={onAcknowledge}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("catalog-drift-acknowledge-drift-001"));
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
    expect(onAcknowledge.mock.calls[0][0].driftId).toBe("drift-001");
  });

  it("fires onReject with the row data when Reject clicked", () => {
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift()}
            onAcknowledge={vi.fn()}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("catalog-drift-reject-drift-001"));
    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onReject.mock.calls[0][0].driftId).toBe("drift-001");
  });

  it("disabled={true} prevents both action callbacks from firing", () => {
    const onAcknowledge = vi.fn();
    const onReject = vi.fn();
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift()}
            disabled
            onAcknowledge={onAcknowledge}
            onReject={onReject}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByTestId("catalog-drift-acknowledge-drift-001"));
    fireEvent.click(screen.getByTestId("catalog-drift-reject-drift-001"));
    expect(onAcknowledge).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });

  // ─── L4↦L2 reverse-arc badge (Half B) ────────────────────────────

  it("does NOT render the impact-count badge when impactCount is undefined", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift()}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("catalog-drift-impact-badge-drift-001"),
    ).not.toBeInTheDocument();
  });

  it("does NOT render the impact-count badge when impactCount is 0", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift()}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
            impactCount={0}
          />
        </tbody>
      </table>,
    );
    expect(
      screen.queryByTestId("catalog-drift-impact-badge-drift-001"),
    ).not.toBeInTheDocument();
  });

  it("renders an impact-count badge when impactCount > 0", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              driftKind: "column_type_changed",
              column: "email",
              sourceId: "warehouse",
              tableId: "public.users",
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
            impactCount={3}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "catalog-drift-impact-badge-drift-001",
    );
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3 downstream impacts via L4");
  });

  it("uses singular 'impact' when impactCount === 1", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              column: "email",
              sourceId: "warehouse",
              tableId: "public.users",
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "catalog-drift-impact-badge-drift-001",
    );
    expect(badge).toHaveTextContent("1 downstream impact via L4");
  });

  it("badge link href encodes source_id, src_table, src_column for column-level drifts", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              column: "email",
              sourceId: "warehouse",
              tableId: "public.users",
              driftKind: "column_type_changed",
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
            impactCount={2}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "catalog-drift-impact-badge-drift-001",
    );
    const href = badge.getAttribute("href") ?? "";
    expect(href.startsWith("/lake/schema-impact?")).toBe(true);
    expect(href).toContain("source_id=warehouse");
    expect(href).toContain("src_table=public.users");
    expect(href).toContain("src_column=email");
  });

  it("badge link href omits src_column for table-level drifts (column null)", () => {
    render(
      <table>
        <tbody>
          <CatalogDriftRow
            drift={makeDrift({
              column: null,
              sourceId: "warehouse",
              tableId: "public.users",
              driftKind: "table_added",
            })}
            onAcknowledge={vi.fn()}
            onReject={vi.fn()}
            impactCount={1}
          />
        </tbody>
      </table>,
    );
    const badge = screen.getByTestId(
      "catalog-drift-impact-badge-drift-001",
    );
    const href = badge.getAttribute("href") ?? "";
    expect(href).toContain("source_id=warehouse");
    expect(href).toContain("src_table=public.users");
    expect(href).not.toContain("src_column=");
  });
});
