import { Receipt } from "../../lib/receipts";
import type { DomainRow as DomainRowModel } from "../../lib/ledger-client.types";

export function DomainRow({ row, alt }: { row: DomainRowModel; alt: boolean }) {
  const sev =
    row.classificationDefault === "pii" ||
    row.classificationDefault === "restricted"
      ? "warn"
      : row.classificationDefault === "public"
        ? "ok"
        : "neutral";
  return (
    <tr
      data-testid={`domain-${row.domainId}`}
      data-sev={sev}
      style={{
        background: alt ? "var(--wb-color-paper-deep)" : "var(--wb-color-paper)",
      }}
    >
      <td style={{ padding: "12px 16px" }}>
        <span style={{ fontFamily: "var(--wb-font-serif)", fontSize: 18, fontWeight: 500 }}>
          {row.name}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="wb-mono" style={{ fontSize: 12 }}>
          @{row.owner}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span
          data-chip
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "3px 8px",
            border: `1px solid ${
              sev === "warn"
                ? "var(--wb-color-sepia-warning)"
                : sev === "ok"
                  ? "var(--wb-color-botanical-green)"
                  : "var(--wb-color-hash-gray)"
            }`,
            color:
              sev === "warn"
                ? "var(--wb-color-sepia-warning)"
                : sev === "ok"
                  ? "var(--wb-color-botanical-green-deep)"
                  : "var(--wb-color-aged-ink)",
            background:
              sev === "warn"
                ? "var(--wb-color-sepia-warning-soft)"
                : sev === "ok"
                  ? "var(--wb-color-botanical-green-soft)"
                  : "var(--wb-color-paper-deep)",
            borderRadius: 0,
          }}
        >
          {row.classificationDefault}
        </span>
      </td>
      <td style={{ padding: "12px 16px" }}>
        <span className="wb-mono" style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}>
          {row.resourceCount} resources
        </span>
      </td>
      <td style={{ padding: "12px 16px", minWidth: 280 }}>
        <Receipt
          hash={row.receipt.hash}
          source={row.receipt.source}
          owner={row.receipt.owner}
          classification={row.receipt.classification}
          compact
        />
      </td>
    </tr>
  );
}
