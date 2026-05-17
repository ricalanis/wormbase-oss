"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { InsightCard } from "../../lib/ledger-client.types";

export function InsightsPanel({ insights }: { insights: InsightCard[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const visible = insights.filter((i) => !dismissed.has(i.insightId));

  if (visible.length === 0) {
    return (
      <p
        data-testid="insights-panel-empty"
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No insights yet — the worm will surface gold-mart cards here as
        process maps and recurring questions firm up.
      </p>
    );
  }

  return (
    <ul
      data-testid="insights-panel"
      style={{
        padding: 0,
        margin: 0,
        listStyle: "none",
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 12,
      }}
    >
      {visible.map((i) => (
        <li
          key={i.insightId}
          data-testid={`insight-${i.insightId}`}
          style={{
            border: "1px solid var(--wb-color-paper-edge)",
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 10,
            background: "var(--wb-color-paper)",
          }}
        >
          <header style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
            <span
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {i.kind}
            </span>
            <span
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 16,
                fontWeight: 500,
              }}
            >
              {i.title}
            </span>
          </header>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              lineHeight: 1.55,
              color: "var(--wb-color-aged-ink-soft)",
            }}
          >
            {i.summary}
          </p>
          <Receipt
            hash={i.receipt.hash}
            source={i.receipt.source}
            owner={i.receipt.owner}
            classification={i.receipt.classification}
            compact
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={() =>
                setDismissed((s) => new Set([...s, i.insightId]))
              }
              data-testid={`insight-dismiss-${i.insightId}`}
              style={{
                background: "transparent",
                border: "1px solid var(--wb-color-aged-ink)",
                borderRadius: 0,
                padding: "6px 10px",
                cursor: "pointer",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
              }}
            >
              Dismiss
            </button>
            <button
              type="button"
              data-testid={`insight-act-${i.insightId}`}
              style={{
                background: "var(--wb-color-botanical-green)",
                color: "var(--wb-color-paper)",
                border: "1px solid var(--wb-color-botanical-green-deep)",
                borderRadius: 0,
                padding: "6px 10px",
                cursor: "pointer",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
              }}
            >
              Act
            </button>
            <button
              type="button"
              data-testid={`insight-schedule-${i.insightId}`}
              style={{
                background: "var(--wb-color-paper)",
                border: "1px solid var(--wb-color-aged-ink)",
                borderRadius: 0,
                padding: "6px 10px",
                cursor: "pointer",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
              }}
            >
              Schedule weekly
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
