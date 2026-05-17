"use client";
/**
 * PeopleRoster — sortable table of all active Persons in the tenant.
 *
 * Click a column header to sort by that column (asc → desc → asc). Click a
 * row to open the PersonDetailDrawer. Visual style matches the legacy
 * PersonRow component — wb-mono ids, serif names, square chips.
 *
 * A5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { useMemo, useState } from "react";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";
import { PersonDetailDrawer } from "./PersonDetailDrawer";
import { chipStyle, statusTone, tenancyRoleTone } from "./_styles";

type SortKey =
  | "name"
  | "email"
  | "position"
  | "tenancy"
  | "domain"
  | "resource"
  | "status";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "email", label: "Email" },
  { key: "position", label: "Position" },
  { key: "tenancy", label: "Tenancy" },
  { key: "domain", label: "Domains" },
  { key: "resource", label: "Resources" },
  { key: "status", label: "Status" },
];

function compareRows(
  a: PersonRowModel,
  b: PersonRowModel,
  key: SortKey,
): number {
  switch (key) {
    case "name":
      return a.displayName.localeCompare(b.displayName);
    case "email":
      return (a.email ?? "").localeCompare(b.email ?? "");
    case "position":
      return (a.position ?? "").localeCompare(b.position ?? "");
    case "tenancy":
      return (a.tenancyRole ?? "").localeCompare(b.tenancyRole ?? "");
    case "domain":
      return a.domainGrantCount - b.domainGrantCount;
    case "resource":
      return a.resourceGrantCount - b.resourceGrantCount;
    case "status":
      return a.status.localeCompare(b.status);
  }
}

export interface PeopleRosterProps {
  persons: PersonRowModel[];
  /**
   * Current admin's Person id. Threaded through to the
   * `PersonDetailDrawer` so identity link/unlink and role grants land
   * with real attribution on the wire (per CLAUDE.md §9 — no self-grant
   * placeholders). `null` when the dashboard is rendered without a
   * resolved admin / installer (the `(app)/` layout normally redirects
   * before that happens).
   */
  adminPersonId?: string | null;
  /**
   * Whether the current viewer is an admin or installer. When false the
   * drawer gates merge / unlink / link affordances per CLAUDE.md §5.
   */
  isAdmin?: boolean;
}

export function PeopleRoster({
  persons,
  adminPersonId = null,
  isAdmin = false,
}: PeopleRosterProps) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [drillId, setDrillId] = useState<string | null>(null);

  const sorted = useMemo(() => {
    const arr = persons.slice();
    arr.sort((a, b) => {
      const c = compareRows(a, b, sortKey);
      return sortDir === "asc" ? c : -c;
    });
    return arr;
  }, [persons, sortKey, sortDir]);

  function handleHeaderClick(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <>
      <table
        data-testid="people-roster"
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
                  data-testid={`roster-header-${c.key}`}
                  onClick={() => handleHeaderClick(c.key)}
                  style={{
                    textAlign: "left",
                    padding: "10px 16px",
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.16em",
                    textTransform: "uppercase",
                    color: active
                      ? "var(--wb-color-aged-ink)"
                      : "var(--wb-color-hash-gray)",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  {c.label}
                  {active ? (
                    <span
                      data-testid={`roster-sort-indicator-${c.key}`}
                      className="wb-mono"
                      style={{ marginLeft: 6, fontSize: 10 }}
                    >
                      {sortDir === "asc" ? "▲" : "▼"}
                    </span>
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr data-testid="roster-empty">
              <td
                colSpan={COLUMNS.length}
                style={{
                  padding: "24px 16px",
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                No active Persons in this tenant yet — invite one or wait for
                the worm to discover them.
              </td>
            </tr>
          ) : null}
          {sorted.map((p, i) => (
            <tr
              key={p.personId}
              data-testid={`roster-row-${p.personId}`}
              onClick={() => setDrillId(p.personId)}
              style={{
                background:
                  i % 2 === 1
                    ? "var(--wb-color-paper-deep)"
                    : "var(--wb-color-paper)",
                cursor: "pointer",
              }}
            >
              <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 16,
                    fontWeight: 500,
                  }}
                >
                  {p.displayName}
                </span>
              </td>
              <td
                style={{ padding: "12px 16px", verticalAlign: "top" }}
                className="wb-mono"
              >
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {p.email ?? "—"}
                </span>
              </td>
              <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 13,
                    color: "var(--wb-color-aged-ink)",
                  }}
                >
                  {p.position ?? "—"}
                </span>
              </td>
              <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                <span
                  data-testid={`roster-tenancy-${p.personId}`}
                  className="wb-mono"
                  style={chipStyle(tenancyRoleTone(p.tenancyRole))}
                >
                  {p.tenancyRole ?? "—"}
                </span>
              </td>
              <td
                style={{ padding: "12px 16px", verticalAlign: "top" }}
                className="wb-mono"
              >
                <span style={{ fontSize: 12, color: "var(--wb-color-aged-ink)" }}>
                  {p.domainGrantCount}
                </span>
              </td>
              <td
                style={{ padding: "12px 16px", verticalAlign: "top" }}
                className="wb-mono"
              >
                <span style={{ fontSize: 12, color: "var(--wb-color-aged-ink)" }}>
                  {p.resourceGrantCount}
                </span>
              </td>
              <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                <span
                  data-testid={`roster-status-${p.personId}`}
                  className="wb-mono"
                  style={chipStyle(statusTone(p.status))}
                >
                  {p.status}
                </span>
                <div style={{ marginTop: 6 }}>
                  <Receipt
                    hash={p.receipt.hash}
                    source={p.receipt.source}
                    owner={p.receipt.owner}
                    classification={p.receipt.classification}
                    compact
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {drillId ? (
        <PersonDetailDrawer
          personId={drillId}
          onClose={() => setDrillId(null)}
          adminPersonId={adminPersonId ?? undefined}
          isAdmin={isAdmin}
        />
      ) : null}
    </>
  );
}
