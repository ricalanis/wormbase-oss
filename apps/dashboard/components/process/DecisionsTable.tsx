"use client";

/**
 * Decisions table — Step 3c, /decisions surface.
 *
 * Renders one row per ``emit_decision_recorded`` ledger entry, with sort by
 * date (default), filter by channel, and a short link to the source
 * messages so you can replay where the decision came from. Each row carries
 * a Receipt — process retrieval is governance-shaped, not magic.
 */

import { useMemo, useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { DecisionRow } from "../../lib/ledger-client.types";
import { EmptyState } from "../chrome/EmptyState";

export interface DecisionsTableProps {
  rows: DecisionRow[];
  /**
   * Optional row-click handler. When supplied, the row becomes a
   * keyboard/mouse-clickable region (W2.A7). When absent the table
   * stays read-only (back-compat with existing pages).
   */
  onRowClick?: (decision: DecisionRow) => void;
}

type SortKey = "date" | "confidence";
type SortDir = "asc" | "desc";

export function DecisionsTable({ rows, onRowClick }: DecisionsTableProps) {
  const [channel, setChannel] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const channels = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) set.add(r.channelId);
    return ["all", ...Array.from(set).sort()];
  }, [rows]);

  const filtered = useMemo(() => {
    const out = channel === "all"
      ? rows.slice()
      : rows.filter((r) => r.channelId === channel);
    out.sort((a, b) => {
      if (sortKey === "date") {
        const cmp = a.decisionAt.localeCompare(b.decisionAt);
        return sortDir === "asc" ? cmp : -cmp;
      }
      const cmp = a.confidence - b.confidence;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, channel, sortKey, sortDir]);

  function toggleSort(k: SortKey) {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir("desc");
    }
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        testId="decisions-empty"
        eyebrow="no decisions yet"
        title="Decisions surface as your team converges in chat."
        description={
          "The worm watches channel chatter and promotes sentences with " +
          "explicit decisions (\"we decided X\", \"let's go with Y\", " +
          "\"approved\", \"agreed\") into ledger entries. Each row will " +
          "carry the channel, the participants, the evidence message ids, " +
          "and a confidence score. Drop the worm into channels where " +
          "decisions get made — first decisions typically land within a few " +
          "hours of the first decision-grade chatter."
        }
        cta={{ label: "Add the worm to more channels", href: "/channels" }}
        secondaryCta={{ label: "What's recurring?", href: "#recurring-questions" }}
      />
    );
  }

  return (
    <div data-testid="decisions-table">
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "center",
          paddingBottom: 12,
        }}
      >
        <label
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Channel:&nbsp;
          <select
            data-testid="decisions-filter-channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              padding: "4px 8px",
              borderRadius: 0,
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper)",
            }}
          >
            {channels.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {filtered.length} decision{filtered.length === 1 ? "" : "s"}
        </span>
      </div>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          borderTop: "1px solid var(--wb-color-aged-ink)",
        }}
      >
        <thead>
          <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
            <th
              scope="col"
              data-testid="decisions-sort-date"
              onClick={() => toggleSort("date")}
              style={{
                ...thStyle,
                cursor: "pointer",
              }}
            >
              date {sortKey === "date" ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </th>
            <th scope="col" style={thStyle}>
              decision
            </th>
            <th scope="col" style={thStyle}>
              channel
            </th>
            <th
              scope="col"
              data-testid="decisions-sort-confidence"
              onClick={() => toggleSort("confidence")}
              style={{ ...thStyle, cursor: "pointer" }}
            >
              confidence {sortKey === "confidence" ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </th>
            <th scope="col" style={thStyle}>
              evidence
            </th>
            <th scope="col" style={thStyle}>
              receipt
            </th>
            <th scope="col" style={thStyle}>
              chain
            </th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((r, i) => (
            <tr
              key={r.decisionId}
              data-testid={`decision-${r.decisionId}`}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onRowClick(r);
                      }
                    }
                  : undefined
              }
              role={onRowClick ? "button" : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              style={{
                background: i % 2 === 1 ? "var(--wb-color-paper-deep)" : "transparent",
                borderBottom: "1px solid var(--wb-color-paper-edge)",
                cursor: onRowClick ? "pointer" : undefined,
              }}
            >
              <td style={tdStyle}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {formatDate(r.decisionAt)}
                </span>
              </td>
              <td style={{ ...tdStyle, fontFamily: "var(--wb-font-serif)" }}>
                {r.decisionText}
              </td>
              <td style={tdStyle}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {r.channelId}
                </span>
              </td>
              <td style={tdStyle}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {(r.confidence * 100).toFixed(0)}%
                </span>
              </td>
              <td style={tdStyle}>
                {r.evidenceMessageIds.slice(0, 3).map((mid) => (
                  <span
                    key={mid}
                    data-testid={`decision-evidence-${mid}`}
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      marginRight: 8,
                      borderBottom: "1px dotted var(--wb-color-botanical-green)",
                    }}
                  >
                    {mid}
                  </span>
                ))}
              </td>
              <td style={tdStyle}>
                <Receipt
                  hash={r.receipt.hash}
                  source={r.receipt.source}
                  owner={r.receipt.owner}
                  classification={r.receipt.classification}
                  compact
                />
              </td>
              <td style={tdStyle}>
                <a
                  href={`/trace/decision/${encodeURIComponent(r.decisionId)}`}
                  data-testid={`decision-chain-link-${r.decisionId}`}
                  className="wb-mono"
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    fontSize: 11,
                    letterSpacing: "0.04em",
                    color: "var(--wb-color-botanical-green-deep)",
                    textDecoration: "none",
                    borderBottom:
                      "1px dotted var(--wb-color-botanical-green-deep)",
                    padding: "2px 0",
                  }}
                >
                  view chain →
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 16px",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const tdStyle: React.CSSProperties = {
  padding: "10px 16px",
  verticalAlign: "top",
  fontSize: 13,
};

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}
