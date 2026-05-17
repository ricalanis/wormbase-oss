"use client";

import { type ReactNode, useState } from "react";

export type LedgerEntryType =
  | "propose"
  | "execute"
  | "verify"
  | "resolve"
  | "source_connected"
  | "ingest_profiled"
  | "ingest_landed"
  | "memory_written"
  | "concept_proposed"
  | "concept_confirmed"
  | "chat_received"
  | "chat_sent"
  | "gate_fired"
  | "kpi_answered"
  | "heuristic_experiment"
  | "policy_applied";

export interface LedgerEntryProps {
  /** ISO timestamp. */
  timestamp: string;
  /** Canonical ledger entry type. Renders as a bordered badge. */
  entryType: LedgerEntryType;
  /** Short hash (6–12 chars). */
  hash: string;
  /** Human summary of the entry. Serif. */
  summary: ReactNode;
  /** Optional JSON-ish expansion shown on click. */
  detail?: ReactNode;
  /** Actor that produced the entry (e.g. "worm", "@ricardo-bot"). */
  actor?: string;
}

/**
 * Field Notebook LedgerEntry — mono-styled data row.
 *
 * A single line of the worm's journal. Timestamp + type badge + hash + summary.
 * Click to expand the payload. Thin rule below every row — dense, no shadow,
 * no bubble.
 */
export function LedgerEntry({
  timestamp,
  entryType,
  hash,
  summary,
  detail,
  actor,
}: LedgerEntryProps) {
  const [open, setOpen] = useState(false);

  const badgeColor = badgeColorMap[entryType] ?? "var(--wb-color-aged-ink)";

  return (
    <div
      data-entry-type={entryType}
      style={{
        borderBottom: "1px solid var(--wb-color-rule-line)",
        padding: "10px 0",
        display: "flex",
        flexDirection: "column",
        gap: "4px",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "110px 160px 90px 1fr auto",
          columnGap: "16px",
          alignItems: "baseline",
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: "var(--wb-text-xs)",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {timestamp}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: "10px",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: badgeColor,
            border: `1px solid ${badgeColor}`,
            padding: "2px 6px",
            width: "fit-content",
            justifySelf: "start",
          }}
        >
          {entryType}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: "var(--wb-text-xs)",
            color: "var(--wb-color-aged-ink)",
            fontWeight: 600,
          }}
        >
          #{hash}
        </span>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-sm)",
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {summary}
        </span>
        <div
          style={{
            display: "inline-flex",
            gap: "8px",
            alignItems: "center",
          }}
        >
          {actor ? (
            <span
              className="wb-mono"
              style={{
                fontSize: "var(--wb-text-xs)",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {actor}
            </span>
          ) : null}
          {detail ? (
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
              className="wb-mono"
              style={{
                background: "transparent",
                border: "1px solid var(--wb-color-rule-line)",
                color: "var(--wb-color-aged-ink)",
                fontSize: "10px",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "2px 6px",
                cursor: "pointer",
              }}
            >
              {open ? "close" : "expand"}
            </button>
          ) : null}
        </div>
      </div>
      {open && detail ? (
        <pre
          className="wb-mono"
          style={{
            margin: "8px 0 4px",
            padding: "10px 12px",
            background: "var(--wb-color-paper-deep)",
            border: "1px solid var(--wb-color-rule-line)",
            fontSize: "var(--wb-text-xs)",
            color: "var(--wb-color-aged-ink)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            overflowX: "auto",
          }}
        >
          {detail}
        </pre>
      ) : null}
    </div>
  );
}

const badgeColorMap: Partial<Record<LedgerEntryType, string>> = {
  propose: "var(--wb-color-botanical-green)",
  execute: "var(--wb-color-aged-ink)",
  verify: "var(--wb-color-aged-ink-soft)",
  resolve: "var(--wb-color-botanical-green-deep)",
  gate_fired: "var(--wb-color-sepia-warning)",
  heuristic_experiment: "var(--wb-color-botanical-green)",
  policy_applied: "var(--wb-color-aged-ink)",
  kpi_answered: "var(--wb-color-botanical-green-deep)",
};
