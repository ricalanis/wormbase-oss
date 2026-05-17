"use client";
/**
 * NotebooksTable — sortable table of notebooks in the tenant.
 *
 * F4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import Link from "next/link";
import { useMemo, useState } from "react";
import type { NotebookRow } from "../../lib/ledger-client.types";
import { chipStyle } from "../people/_styles";

type SortKey = "name" | "kernel" | "status" | "version";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "kernel", label: "Kernel" },
  { key: "status", label: "Status" },
  { key: "version", label: "Version" },
];

function compareRows(a: NotebookRow, b: NotebookRow, key: SortKey): number {
  switch (key) {
    case "name":
      return a.name.localeCompare(b.name);
    case "kernel":
      return a.kernel.localeCompare(b.kernel);
    case "status":
      return a.status.localeCompare(b.status);
    case "version":
      return (a.version ?? "").localeCompare(b.version ?? "");
  }
}

function statusTone(s: string) {
  if (s === "published") return "green" as const;
  if (s === "run") return "neutral" as const;
  if (s === "proposed") return "sepia" as const;
  if (s === "archived") return "muted" as const;
  return "neutral" as const;
}

export function NotebooksTable({ notebooks }: { notebooks: NotebookRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const sorted = useMemo(() => {
    const arr = notebooks.slice();
    arr.sort((a, b) => {
      const c = compareRows(a, b, sortKey);
      return sortDir === "asc" ? c : -c;
    });
    return arr;
  }, [notebooks, sortKey, sortDir]);

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
      data-testid="notebooks-table"
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
              No notebooks yet. The autoresearch loop publishes one per kept
              experiment.
            </td>
          </tr>
        ) : (
          sorted.map((nb) => (
            <tr
              key={nb.notebookId}
              data-testid="notebook-row"
              style={{
                borderBottom: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <td style={{ padding: "10px 12px" }}>
                <Link
                  href={`/notebooks/${nb.notebookId}`}
                  style={{
                    color: "var(--wb-color-aged-ink)",
                    fontFamily: "var(--wb-font-serif)",
                    fontWeight: 500,
                    textDecoration: "none",
                  }}
                >
                  {nb.name}
                </Link>
              </td>
              <td className="wb-mono" style={{ padding: "10px 12px", fontSize: 12 }}>
                {nb.kernel}
              </td>
              <td style={{ padding: "10px 12px" }}>
                <span style={chipStyle(statusTone(nb.status))}>{nb.status}</span>
              </td>
              <td className="wb-mono" style={{ padding: "10px 12px", fontSize: 12 }}>
                {nb.version ?? "—"}
              </td>
              <td
                className="wb-mono"
                style={{
                  padding: "10px 12px",
                  fontSize: 11,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {nb.notebookId.slice(0, 8)}…
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
