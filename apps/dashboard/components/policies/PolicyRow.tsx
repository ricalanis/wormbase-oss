import { Receipt } from "../../lib/receipts";
import type { PolicyRow as PolicyRowModel } from "../../lib/ledger-client.types";

export function PolicyRow({ row }: { row: PolicyRowModel }) {
  return (
    <article
      data-testid={`policy-${row.policyId}`}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 18,
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 16,
        background: "var(--wb-color-paper)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          {row.name}
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            lineHeight: 1.5,
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          {row.plainLanguage}
        </p>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            wordBreak: "break-all",
          }}
        >
          gate · {row.gateImpl} · scope {row.scope}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          alignItems: "flex-end",
          minWidth: 280,
        }}
      >
        <span
          className="wb-mono"
          data-testid={`policy-fires-${row.policyId}`}
          style={{
            fontSize: 12,
            color: row.firesLast7d > 0 ? "var(--wb-color-sepia-warning)" : "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          fired {row.firesLast7d}× last 7d
        </span>
        <Receipt
          hash={row.receipt.hash}
          source={row.receipt.source}
          owner={row.receipt.owner}
          classification={row.receipt.classification}
          compact
        />
      </div>
    </article>
  );
}
