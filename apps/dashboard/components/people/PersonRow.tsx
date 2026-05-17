import { Receipt } from "../../lib/receipts";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";

/**
 * PersonRow — single row in the People table. SMALL CAPS serif headers; mono
 * roles; rectangular chips (NOT pills) for owned domains.
 */
export function PersonRow({ row, alt }: { row: PersonRowModel; alt: boolean }) {
  return (
    <tr
      data-testid={`person-${row.personId}`}
      style={{
        background: alt ? "var(--wb-color-paper-deep)" : "var(--wb-color-paper)",
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
          @{row.displayName}
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <span
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-aged-ink)" }}
        >
          {row.roles.join(" · ")}
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <div
          data-testid="owned-domains"
          style={{ display: "flex", flexWrap: "wrap", gap: 6 }}
        >
          {row.ownedDomains.map((d) => (
            <span
              key={d}
              data-chip
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "3px 8px",
                border: "1px solid var(--wb-color-botanical-green)",
                color: "var(--wb-color-botanical-green-deep)",
                background: "var(--wb-color-botanical-green-soft)",
                borderRadius: 0,
              }}
            >
              {d}
            </span>
          ))}
        </div>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <span
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
        >
          {row.ownedResources.length} resources
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top", minWidth: 280 }}>
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
