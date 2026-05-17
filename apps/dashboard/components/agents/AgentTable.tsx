/**
 * AgentTable — pure presentational table for /people/agents.
 *
 * One row per registered Agent (Person sub-type). Shows the external
 * provider, display name, status, active grant count, and remaining
 * model-access budget. Per-row click-through to /people/agents/[id]
 * is wired so the detail page composes cleanly once it ships (Wave 4
 * scope); the row link is emitted here so the chrome stays consistent.
 *
 * Sorting: header click toggles sort. Default sort is `registeredAt`
 * descending (newest agents first), which matches the accessor's
 * natural order.
 *
 * Empty state is handled by the page itself, not here — this component
 * stays a pure list so it composes cleanly with the page's
 * `rows.length === 0 ? <EmptyState /> : <AgentTable />` pattern.
 */

"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { Agent } from "../../lib/agents";

/**
 * Row shape used by /people/agents: ``Agent`` augmented with the v2.A
 * Subscriptions column (active-subscription count from
 * ``getAgentSubscriptionCounts``). The field is optional so callers
 * that haven't joined yet still type-check.
 */
export interface AgentRowWithSubs extends Agent {
  subscriptionCount?: number;
}

type SortKey =
  | "displayName"
  | "externalProvider"
  | "status"
  | "activeGrantCount"
  | "subscriptionCount"
  | "budgetRemainingUsdSum"
  | "registeredAt";

type SortDir = "asc" | "desc";

export interface AgentTableProps {
  rows: AgentRowWithSubs[];
}

function compareRows(
  a: AgentRowWithSubs,
  b: AgentRowWithSubs,
  key: SortKey,
): number {
  const av = a[key];
  const bv = b[key];
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
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

function fmtBudget(sum: string | null): string {
  if (sum == null) return "—";
  // Trim trailing zeros for human readability while preserving the
  // string-typed precision the projection returns.
  const num = Number.parseFloat(sum);
  if (Number.isNaN(num)) return sum;
  return `$${num.toFixed(2)}`;
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
    <span aria-hidden style={{ marginLeft: 6, fontSize: 9 }}>
      {dir === "asc" ? "▲" : "▼"}
    </span>
  );
}

export function AgentTable({ rows }: AgentTableProps): JSX.Element {
  const [sortKey, setSortKey] = useState<SortKey>("registeredAt");
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
      setSortDir(
        key === "activeGrantCount" ||
          key === "subscriptionCount" ||
          key === "budgetRemainingUsdSum" ||
          key === "registeredAt"
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
      data-testid={`agents-th-${key}`}
    >
      {label}
      <SortArrow active={sortKey === key} dir={sortDir} />
    </th>
  );

  return (
    <div data-testid="agents-table" style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <thead>
          <tr>
            {headerCell("displayName", "Agent")}
            {headerCell("externalProvider", "Provider")}
            {headerCell("status", "Status")}
            {headerCell("activeGrantCount", "Grants")}
            {headerCell("subscriptionCount", "Subscriptions")}
            {headerCell("budgetRemainingUsdSum", "Budget")}
            {headerCell("registeredAt", "Registered")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={row.id}
              data-testid={`agents-row-${row.id}`}
            >
              <td style={TD_STYLE}>
                <Link
                  href={`/people/agents/${row.id}`}
                  style={{
                    color: "var(--wb-color-botanical, #2d6a4f)",
                    textDecoration: "none",
                    fontWeight: 500,
                  }}
                  data-testid={`agents-row-link-${row.id}`}
                >
                  {row.displayName}
                </Link>
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    marginTop: 2,
                  }}
                >
                  {row.id.slice(0, 8)}…
                </div>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`agents-provider-${row.externalProvider}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    padding: "2px 8px",
                    border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
                  }}
                >
                  {row.externalProvider}
                </span>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`agents-status-${row.status}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color:
                      row.status === "active"
                        ? "var(--wb-color-botanical, #2d6a4f)"
                        : "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.status}
                </span>
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.activeGrantCount}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                <Link
                  href={`/people/agents/${row.id}/subscriptions`}
                  data-testid={`agents-subscriptions-link-${row.id}`}
                  style={{
                    color:
                      (row.subscriptionCount ?? 0) > 0
                        ? "var(--wb-color-botanical, #2d6a4f)"
                        : "var(--wb-color-hash-gray, #6b6256)",
                    textDecoration: "none",
                    fontFamily:
                      "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 13,
                  }}
                >
                  {row.subscriptionCount ?? 0}
                </Link>
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 13,
                }}
              >
                {fmtBudget(row.budgetRemainingUsdSum)}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.registeredAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
