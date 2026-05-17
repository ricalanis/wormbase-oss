/**
 * CatalogTable — pure presentational table for /lake/catalog.
 *
 * One row per catalog snapshot (most-recent per source_id). Click-through
 * to ``/lake/catalog/[sourceId]`` is wired but the detail page is v2;
 * the row link is still emitted so the chrome behaves consistently when
 * the detail page ships.
 *
 * Sorting: a header click toggles sort by that column. Default sort is
 * ``importedAt`` descending (newest snapshots first), which matches the
 * accessor's natural order for "what's the catalog state right now?".
 *
 * Empty state is handled by the page itself, not here — this component
 * stays a pure list so it composes cleanly with the page's
 * ``rows.length === 0 ? <EmptyState /> : <CatalogTable />`` pattern.
 */

"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { CatalogTable as CatalogTableRow } from "../../lib/lake-catalog";

type SortKey =
  | "sourceKind"
  | "tableCount"
  | "edgeCount"
  | "metricCount"
  | "upstreamLineageCount"
  | "downstreamLineageCount"
  | "importMode"
  | "importedAt";

type SortDir = "asc" | "desc";

export interface CatalogTableProps {
  rows: CatalogTableRow[];
}

function compareRows(
  a: CatalogTableRow,
  b: CatalogTableRow,
  key: SortKey,
): number {
  const av = a[key];
  const bv = b[key];
  if (typeof av === "number" && typeof bv === "number") return av - bv;
  return String(av).localeCompare(String(bv));
}

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16);
  } catch {
    return iso;
  }
}

function shortHash(hash: string): string {
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 8)}…${hash.slice(-4)}`;
}

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray, #6b6256)",
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  cursor: "pointer",
  userSelect: "none",
  whiteSpace: "nowrap",
};

const TD_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 14,
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.06))",
  verticalAlign: "top",
};

function SortArrow({
  active,
  dir,
}: {
  active: boolean;
  dir: SortDir;
}): JSX.Element | null {
  if (!active) return null;
  return (
    <span
      aria-hidden
      style={{ marginLeft: 6, fontSize: 9 }}
    >
      {dir === "asc" ? "▲" : "▼"}
    </span>
  );
}

export function CatalogTable({ rows }: CatalogTableProps): JSX.Element {
  const [sortKey, setSortKey] = useState<SortKey>("importedAt");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const cmp = compareRows(a, b, sortKey);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Numbers default to descending (biggest first); strings ascending.
      setSortDir(
        key === "tableCount" ||
          key === "edgeCount" ||
          key === "metricCount" ||
          key === "upstreamLineageCount" ||
          key === "downstreamLineageCount" ||
          key === "importedAt"
          ? "desc"
          : "asc",
      );
    }
  }

  const headerCell = (key: SortKey, label: string) => (
    <th
      scope="col"
      style={TH_STYLE}
      onClick={() => toggleSort(key)}
      data-testid={`catalog-th-${key}`}
    >
      {label}
      <SortArrow active={sortKey === key} dir={sortDir} />
    </th>
  );

  return (
    <div
      data-testid="catalog-table"
      style={{ overflowX: "auto" }}
    >
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <thead>
          <tr>
            {headerCell("sourceKind", "Source")}
            <th scope="col" style={TH_STYLE}>Snapshot</th>
            {headerCell("tableCount", "Tables")}
            {headerCell("edgeCount", "Edges")}
            {headerCell("metricCount", "Metrics")}
            {headerCell("upstreamLineageCount", "Upstream")}
            {headerCell("downstreamLineageCount", "Downstream")}
            {headerCell("importMode", "Mode")}
            {headerCell("importedAt", "Imported")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={`${row.sourceId}:${row.snapshotHash}`}
              data-testid={`catalog-row-${row.sourceId}`}
            >
              <td style={TD_STYLE}>
                <Link
                  href={`/lake/catalog/${row.sourceId}`}
                  style={{
                    color: "var(--wb-color-botanical, #2d6a4f)",
                    textDecoration: "none",
                    fontWeight: 500,
                  }}
                  data-testid={`catalog-row-link-${row.sourceId}`}
                >
                  {row.sourceKind}
                </Link>
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    marginTop: 2,
                  }}
                >
                  {row.sourceId.slice(0, 8)}…
                </div>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
                title={row.snapshotHash}
              >
                {shortHash(row.snapshotHash)}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.tableCount}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.edgeCount}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.metricCount}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.upstreamLineageCount}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.downstreamLineageCount}
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`catalog-mode-${row.importMode}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    padding: "2px 8px",
                    border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
                    color:
                      row.importMode === "initial"
                        ? "var(--wb-color-botanical, #2d6a4f)"
                        : "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.importMode}
                </span>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.importedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
