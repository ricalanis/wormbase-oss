/**
 * RecentCallsTable — paginated audit log of inbound MCP calls (Block J6).
 *
 * Source: ``getMcpCalls(companyId)`` returns rows of
 * ``projection_mcp_calls`` (one row per call, written through the
 * ``record_mcp_call`` PEVR primitive on the worm-core side).
 *
 * Privacy posture (per MCP-integration spec §8.3): the audit log is
 * MORE sensitive than the data it audits. We surface ``args_hash``
 * (sha256 hex; raw args never persist) and clip the display to the
 * first 12 chars; we surface the caller person id as an opaque uuid
 * suffix and never their email.
 *
 * Honest empty state: when ``rows.length === 0`` we render copy that
 * names the trigger flow ("connect Claude Desktop, run a tool");
 * NEVER fixture rows.
 *
 * Pagination is intentionally simple — the read accessor caps at 50
 * rows; this component renders all of them. Operators who need
 * deeper audit history use ``query_audit_trail`` via MCP itself.
 */

"use client";

import { useMemo, useState } from "react";
import type { McpCallRow } from "../../lib/ledger-client.types";
import { EmptyState } from "../chrome/EmptyState";
import { chipStyle, type ChipTone } from "../people/_styles";

type SortKey = "startedAt" | "toolName" | "outcome" | "latencyMs";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "startedAt", label: "Started" },
  { key: "toolName", label: "Tool" },
  { key: "outcome", label: "Outcome" },
  { key: "latencyMs", label: "Latency" },
];

function outcomeTone(outcome: string): ChipTone {
  if (outcome === "ok") return "green";
  if (outcome === "error" || outcome === "timeout") return "sepia";
  if (outcome === "denied") return "ink";
  return "neutral";
}

function comparator(a: McpCallRow, b: McpCallRow, key: SortKey): number {
  switch (key) {
    case "startedAt": {
      const aT = Date.parse(a.startedAt);
      const bT = Date.parse(b.startedAt);
      return aT - bT;
    }
    case "toolName":
      return a.toolName.localeCompare(b.toolName);
    case "outcome":
      return a.outcome.localeCompare(b.outcome);
    case "latencyMs":
      return a.latencyMs - b.latencyMs;
  }
}

/** Mask the args_hash to the privacy-safe display form: first 12 hex
 *  chars, ellipsis, last 4. Full hash is never copied to clipboard via
 *  this column — the call detail drawer (J5 / future) is the only
 *  surface that exposes the full hash. */
function displayArgsHash(hash: string): string {
  if (!hash) return "—";
  if (hash.length <= 16) return hash;
  return `${hash.slice(0, 12)}…${hash.slice(-4)}`;
}

/** Mask the caller person id to the display-safe form: first 8 chars
 *  + ellipsis. ``null`` becomes ``mcp-anonymous``. Email never surfaces
 *  (privacy: caller person id alone is enough to cross-reference with
 *  /people, where finer-grained access controls apply). */
function displayCallerId(callerPersonId: string | null): string {
  if (!callerPersonId) return "mcp-anonymous";
  return callerPersonId.length <= 12
    ? callerPersonId
    : `${callerPersonId.slice(0, 8)}…`;
}

export function RecentCallsTable({ rows }: { rows: McpCallRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("startedAt");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = rows.slice();
    arr.sort((a, b) => {
      const c = comparator(a, b, sortKey);
      return sortDir === "asc" ? c : -c;
    });
    return arr;
  }, [rows, sortKey, sortDir]);

  function handleHeaderClick(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "startedAt" || key === "latencyMs" ? "desc" : "asc");
    }
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        testId="mcp-recent-calls-empty"
        eyebrow="no mcp calls yet"
        title="No MCP clients have called this server."
        description={
          "Connect Claude Desktop, Cursor, or another MCP-aware client to " +
          "this tenant's MCP endpoint. Each tool invocation, resource " +
          "read, and prompt fetch lands here as one auditable row."
        }
      />
    );
  }

  return (
    <table
      data-testid="mcp-recent-calls"
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
            Caller
          </th>
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
            Args (sha256)
          </th>
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
            Client
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((row) => (
          <tr
            key={row.mcpCallId}
            data-testid="mcp-call-row"
            style={{
              borderBottom: "1px solid var(--wb-color-paper-edge)",
            }}
          >
            <td
              className="wb-mono"
              style={{
                padding: "10px 12px",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {new Date(row.startedAt).toISOString().slice(0, 19) + "Z"}
            </td>
            <td
              className="wb-mono"
              style={{
                padding: "10px 12px",
                fontSize: 13,
                color: "var(--wb-color-aged-ink)",
              }}
            >
              {row.toolName}
            </td>
            <td style={{ padding: "10px 12px" }}>
              <span
                data-testid={`mcp-call-outcome-${row.outcome}`}
                style={chipStyle(outcomeTone(row.outcome))}
              >
                {row.outcome}
              </span>
            </td>
            <td
              className="wb-mono"
              style={{
                padding: "10px 12px",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {row.latencyMs.toLocaleString()} ms
            </td>
            <td
              className="wb-mono"
              data-testid="mcp-call-caller"
              style={{
                padding: "10px 12px",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {displayCallerId(row.callerPersonId)}
            </td>
            <td
              className="wb-mono"
              data-testid="mcp-call-args-hash"
              title={"sha256: " + row.argsHash}
              style={{
                padding: "10px 12px",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {displayArgsHash(row.argsHash)}
            </td>
            <td
              style={{
                padding: "10px 12px",
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                fontSize: 12,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {row.clientUa ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
