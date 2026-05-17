"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type { BusinessDefProposal } from "../../lib/ledger-client.types";

type Status = "pending" | "accepted" | "rejected";

export function BusinessDefsPanel({
  proposals,
  onConfirm,
  onReject,
}: {
  proposals: BusinessDefProposal[];
  onConfirm?: (term: string) => void | Promise<void>;
  onReject?: (term: string) => void | Promise<void>;
}) {
  const [statuses, setStatuses] = useState<Record<string, Status>>({});

  return (
    <ul
      data-testid="business-defs-panel"
      style={{
        padding: 0,
        margin: 0,
        listStyle: "none",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {proposals.map((p) => {
        const status: Status = statuses[p.term] ?? "pending";
        return (
          <li
            key={p.term}
            data-testid={`business-def-${p.term.replace(/\s+/g, "-")}`}
            data-status={status}
            style={{
              borderLeft: "2px solid var(--wb-color-botanical-green)",
              borderTop: "1px solid var(--wb-color-paper-edge)",
              borderRight: "1px solid var(--wb-color-paper-edge)",
              borderBottom: "1px solid var(--wb-color-paper-edge)",
              padding: 14,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <header style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 17,
                  fontWeight: 500,
                }}
              >
                {p.term}
              </span>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                  marginLeft: "auto",
                }}
              >
                proposed by worm · src {p.sourceHash}
              </span>
            </header>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 14,
                lineHeight: 1.5,
                color: "var(--wb-color-aged-ink)",
              }}
            >
              {p.proposedDefinition}
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                data-testid={`confirm-${p.term.replace(/\s+/g, "-")}`}
                onClick={async () => {
                  setStatuses((s) => ({ ...s, [p.term]: "accepted" }));
                  await onConfirm?.(p.term);
                }}
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
                Accept
              </button>
              <button
                type="button"
                data-testid={`reject-${p.term.replace(/\s+/g, "-")}`}
                onClick={async () => {
                  setStatuses((s) => ({ ...s, [p.term]: "rejected" }));
                  await onReject?.(p.term);
                }}
                style={{
                  background: "var(--wb-color-paper)",
                  color: "var(--wb-color-sepia-warning)",
                  border: "1px solid var(--wb-color-sepia-warning)",
                  borderRadius: 0,
                  padding: "6px 10px",
                  cursor: "pointer",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                }}
              >
                Reject
              </button>
            </div>
            {status === "accepted" ? (
              <Receipt
                hash={p.sourceHash}
                source="onboarding · tier 2"
                owner="ricardo"
                classification="internal"
                compact
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
