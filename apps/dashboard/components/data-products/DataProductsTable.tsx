"use client";
/**
 * DataProductsTable — sortable table of data products in the tenant.
 *
 * F3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Click a row to drill into /data-products/{id}; the drawer is rendered
 * inside the [id] page (not as an overlay) so the URL is shareable.
 *
 * Visual style mirrors PeopleRoster: wb-mono ids, serif names, square chips,
 * top + bottom inked rule.
 */
import Link from "next/link";
import { useMemo, useState } from "react";
import type { DataProductRow } from "../../lib/ledger-client.types";
import { chipStyle } from "../people/_styles";

type SortKey = "name" | "kind" | "status" | "generatedAt";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "kind", label: "Kind" },
  { key: "status", label: "Status" },
  { key: "generatedAt", label: "Generated" },
];

function compareRows(
  a: DataProductRow,
  b: DataProductRow,
  key: SortKey,
): number {
  switch (key) {
    case "name":
      return a.name.localeCompare(b.name);
    case "kind":
      return a.kind.localeCompare(b.kind);
    case "status":
      return a.status.localeCompare(b.status);
    case "generatedAt": {
      const aT = a.generatedAt ? Date.parse(a.generatedAt) : 0;
      const bT = b.generatedAt ? Date.parse(b.generatedAt) : 0;
      return aT - bT;
    }
  }
}

function statusTone(s: string) {
  if (s === "generated") return "green" as const;
  if (s === "proposed") return "sepia" as const;
  if (s === "archived") return "muted" as const;
  return "neutral" as const;
}

export function DataProductsTable({
  dataProducts,
}: {
  dataProducts: DataProductRow[];
}) {
  const [sortKey, setSortKey] = useState<SortKey>("generatedAt");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = dataProducts.slice();
    arr.sort((a, b) => {
      const c = compareRows(a, b, sortKey);
      return sortDir === "asc" ? c : -c;
    });
    return arr;
  }, [dataProducts, sortKey, sortDir]);

  function handleHeaderClick(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <table
      data-testid="data-products-table"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        borderTop: "1px solid var(--wb-color-aged-ink)",
      }}
    >
      <thead>
        <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
          {COLUMNS.map((c) => {
            const active = c.key === sortKey;
            return (
              <th
                key={c.key}
                scope="col"
                onClick={() => handleHeaderClick(c.key)}
                style={{
                  textAlign: "left",
                  padding: "8px 12px",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  fontWeight: 500,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  cursor: "pointer",
                  userSelect: "none",
                  color: active
                    ? "var(--wb-color-aged-ink)"
                    : "var(--wb-color-hash-gray)",
                }}
              >
                {c.label}
                {active ? (
                  <span style={{ marginLeft: 4 }}>
                    {sortDir === "asc" ? "↑" : "↓"}
                  </span>
                ) : null}
              </th>
            );
          })}
          <th
            scope="col"
            style={{
              textAlign: "left",
              padding: "8px 12px",
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              fontWeight: 500,
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            ID
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.length === 0 ? (
          <tr>
            <td
              colSpan={5}
              style={{
                padding: "24px 12px",
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              No data products yet. The worm publishes one when it answers a
              KPI question or when an admin posts a request.
            </td>
          </tr>
        ) : (
          sorted.map((dp) => (
            <tr
              key={dp.dataProductId}
              data-testid="data-product-row"
              style={{
                borderBottom: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <td style={{ padding: "10px 12px" }}>
                <Link
                  href={`/data-products/${dp.dataProductId}`}
                  style={{
                    color: "var(--wb-color-aged-ink)",
                    fontFamily: "var(--wb-font-serif)",
                    fontWeight: 500,
                    textDecoration: "none",
                  }}
                >
                  {dp.name}
                </Link>
              </td>
              <td style={{ padding: "10px 12px" }}>
                <span style={chipStyle("neutral")}>{dp.kind}</span>
              </td>
              <td style={{ padding: "10px 12px" }}>
                <span style={chipStyle(statusTone(dp.status))}>{dp.status}</span>
              </td>
              <td
                className="wb-mono"
                style={{
                  padding: "10px 12px",
                  fontSize: 12,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {dp.generatedAt
                  ? new Date(dp.generatedAt).toISOString().slice(0, 19) + "Z"
                  : "—"}
              </td>
              <td
                className="wb-mono"
                style={{
                  padding: "10px 12px",
                  fontSize: 11,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {dp.dataProductId.slice(0, 8)}…
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
