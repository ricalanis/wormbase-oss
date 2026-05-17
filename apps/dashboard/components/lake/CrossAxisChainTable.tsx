/**
 * CrossAxisChainTable — 7-row chain panel for /lake/overview.
 *
 * Lists every cross-axis chain in the lake stack with a one-line
 * description + producer + consumer page links. Bidirectional chains
 * (currently L4 ↔ L2) render with a "↔ bidirectional" marker on the
 * row so admins can tell the row carries two-way data flow.
 */
import Link from "next/link";

import type { CrossAxisChainRow } from "../../lib/lake-overview";

export interface CrossAxisChainTableProps {
  rows: CrossAxisChainRow[];
}

export function CrossAxisChainTable({
  rows,
}: CrossAxisChainTableProps): JSX.Element {
  return (
    <table
      data-testid="lake-overview-chain-table"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontSize: 12,
      }}
    >
      <thead>
        <tr
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          <th style={{ padding: "6px 8px", textAlign: "left", width: 110 }}>
            Chain
          </th>
          <th style={{ padding: "6px 8px", textAlign: "left" }}>
            Description
          </th>
          <th style={{ padding: "6px 8px", textAlign: "left", width: 180 }}>
            Producer
          </th>
          <th style={{ padding: "6px 8px", textAlign: "left", width: 180 }}>
            Consumer
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.forward}
            data-testid={`lake-overview-chain-row-${row.forward.replace(/[^A-Za-z0-9]+/g, "-")}`}
            data-bidirectional={row.isBidirectional ? "true" : "false"}
            style={{
              borderTop: "1px solid var(--wb-color-paper-edge, #ddd3bd)",
            }}
          >
            <td
              style={{
                padding: "8px 8px",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
              }}
            >
              <code className="wb-mono" style={{ fontSize: 12 }}>
                {row.forward}
              </code>
              {row.isBidirectional ? (
                <span
                  data-testid={`lake-overview-chain-bidirectional-${row.forward.replace(/[^A-Za-z0-9]+/g, "-")}`}
                  className="wb-mono"
                  style={{
                    marginLeft: 6,
                    fontSize: 9,
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                  }}
                >
                  ↔ bidirectional
                </span>
              ) : null}
            </td>
            <td
              style={{
                padding: "8px 8px",
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                color: "var(--wb-color-aged-ink, #463f33)",
              }}
            >
              {row.description}
            </td>
            <td style={{ padding: "8px 8px" }}>
              <Link
                data-testid={`lake-overview-chain-producer-${row.forward.replace(/[^A-Za-z0-9]+/g, "-")}`}
                href={row.producerPage}
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                }}
              >
                {row.producerPage}
              </Link>
            </td>
            <td style={{ padding: "8px 8px" }}>
              <Link
                data-testid={`lake-overview-chain-consumer-${row.forward.replace(/[^A-Za-z0-9]+/g, "-")}`}
                href={row.consumerPage}
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                }}
              >
                {row.consumerPage}
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
