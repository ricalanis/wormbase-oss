"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { TraceEntryRow } from "../../lib/ledger-client.types";

const QUADRANT_BORDER: Record<string, string> = {
  propose: "var(--wb-color-hash-gray)",
  execute: "var(--wb-color-aged-ink)",
  verify: "var(--wb-color-botanical-green)",
  resolve: "var(--wb-color-botanical-green-deep)",
};

export function TraceRow({ entry }: { entry: TraceEntryRow }) {
  const [open, setOpen] = useState(false);
  const summary =
    typeof entry.payload?.summary === "string"
      ? (entry.payload.summary as string)
      : "";
  return (
    <li
      data-testid={`trace-row-${entry.id}`}
      data-quadrant={entry.quadrant}
      style={{
        listStyle: "none",
        borderBottom: "1px solid var(--wb-color-paper-edge)",
        borderLeft: `3px solid ${QUADRANT_BORDER[entry.quadrant] ?? "var(--wb-color-hash-gray)"}`,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        background: "var(--wb-color-paper)",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "180px 130px 1fr 100px 24px",
          gap: 12,
          alignItems: "baseline",
        }}
      >
        <span
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
        >
          {entry.ts}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {entry.kind}
        </span>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {summary}
        </span>
        <span
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
        >
          #{entry.hash.slice(0, 8)}
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Collapse entry" : "Expand entry"}
          data-testid={`trace-toggle-${entry.id}`}
          className="wb-mono"
          style={{
            background: "transparent",
            border: "none",
            cursor: "pointer",
            color: "var(--wb-color-aged-ink)",
            fontSize: 12,
            padding: 0,
          }}
        >
          {open ? "[−]" : "[+]"}
        </button>
      </div>
      <Receipt
        hash={entry.receipt.hash}
        source={entry.receipt.source}
        owner={entry.receipt.owner}
        classification={entry.receipt.classification}
        compact
      />
      {open ? (
        <pre
          data-testid={`trace-detail-${entry.id}`}
          className="wb-mono"
          style={{
            margin: "8px 0 0",
            padding: 12,
            background: "var(--wb-color-paper-deep)",
            border: "1px solid var(--wb-color-paper-edge)",
            fontSize: 11,
            color: "var(--wb-color-aged-ink)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {`id        ${entry.id}\n` +
            `kind      ${entry.kind}\n` +
            `quadrant  ${entry.quadrant}\n` +
            `hash      ${entry.hash}\n` +
            `prevHash  ${entry.prevHash ?? "—"}\n` +
            `payload   ${JSON.stringify(entry.payload, null, 2)}`}
        </pre>
      ) : null}
    </li>
  );
}
