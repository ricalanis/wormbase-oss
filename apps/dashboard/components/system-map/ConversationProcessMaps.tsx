"use client";

/**
 * ConversationProcessMaps — /system-map's "Conversation Process Maps" lens (P10).
 *
 * Renders the gold artifacts the worm proposed from chatter: each
 * ``data_product_proposed{kind: "process_map"}`` entry becomes a row;
 * clicking a row expands its node/edge graph inline.
 *
 * The component is read-only — the dashboard's existing /data-products
 * surface owns the ``confirm`` and ``archive`` actions. Linking out to
 * ``/data-products/{id}`` keeps the lens narrow: "what process maps has
 * the worm seen?" — admin acts elsewhere.
 *
 * Visual style mirrors PeopleRoster + DataProductsTable: wb-mono ids,
 * serif names, square chips, top + bottom inked rule.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import type {
  ProcessMapDataProductRow,
  ProcessMapEdge,
} from "../../lib/ledger-client.types";

export interface ConversationProcessMapsProps {
  processMaps: ProcessMapDataProductRow[];
}

function statusTone(s: string): "green" | "sepia" | "muted" | "neutral" {
  if (s === "generated") return "green";
  if (s === "proposed") return "sepia";
  if (s === "archived") return "muted";
  return "neutral";
}

function shortPersonId(pid: string): string {
  if (!pid) return "—";
  return pid.length > 8 ? `${pid.slice(0, 8)}…` : pid;
}

function formatTs(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toISOString().slice(0, 10);
}

export function ConversationProcessMaps({
  processMaps,
}: ConversationProcessMapsProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const totalEdges = useMemo(
    () =>
      processMaps.reduce((acc, pm) => acc + pm.payload.edges.length, 0),
    [processMaps],
  );
  const totalNodes = useMemo(
    () =>
      processMaps.reduce((acc, pm) => acc + pm.payload.nodes.length, 0),
    [processMaps],
  );

  if (processMaps.length === 0) {
    // Empty state per the production-dashboard "no silent panels"
    // invariant — every panel renders an honest empty when its data
    // source is empty. Matches the EmptyState pattern used elsewhere
    // without importing it (keeps this lens self-contained).
    return (
      <section
        data-testid="conversation-process-maps-empty"
        style={{
          marginTop: 24,
          padding: "24px 16px",
          borderTop: "1px solid var(--wb-color-rule, #1a1a1a)",
          borderBottom: "1px solid var(--wb-color-rule, #1a1a1a)",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          Conversation process maps
        </h2>
        <p
          style={{
            margin: "8px 0 0",
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray, #5f5b53)",
          }}
        >
          The worm has not yet observed enough recurring questions to
          propose a process map. Once an asker→askee→topic triplet
          recurs three times within a 14-day window, a proposal lands
          here for confirmation.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="conversation-process-maps"
      style={{
        marginTop: 24,
        borderTop: "1px solid var(--wb-color-rule, #1a1a1a)",
        borderBottom: "1px solid var(--wb-color-rule, #1a1a1a)",
        padding: "16px 0",
      }}
    >
      <header
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          paddingBottom: 12,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #5f5b53)",
          }}
        >
          Pl. IX·b · Gold from chatter · {processMaps.length}
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          Conversation process maps
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray, #5f5b53)",
          }}
        >
          {processMaps.length} proposal{processMaps.length === 1 ? "" : "s"} ·{" "}
          {totalNodes} actor{totalNodes === 1 ? "" : "s"} ·{" "}
          {totalEdges} edge{totalEdges === 1 ? "" : "s"} synthesized from
          recurring threaded questions.
        </p>
      </header>

      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {processMaps.map((pm) => {
          const isExpanded = expandedId === pm.dataProductId;
          return (
            <li
              key={pm.dataProductId}
              data-testid={`process-map-row-${pm.dataProductId}`}
              style={{
                border: "1px solid var(--wb-color-rule, #d6d3cc)",
                padding: "10px 12px",
              }}
            >
              <button
                type="button"
                onClick={() =>
                  setExpandedId(isExpanded ? null : pm.dataProductId)
                }
                aria-expanded={isExpanded}
                aria-controls={`pm-detail-${pm.dataProductId}`}
                style={{
                  appearance: "none",
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  margin: 0,
                  textAlign: "left",
                  cursor: "pointer",
                  width: "100%",
                  display: "grid",
                  gridTemplateColumns: "1fr auto auto auto",
                  gap: 12,
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 15,
                    fontWeight: 500,
                  }}
                >
                  {pm.name}
                </span>
                <span
                  className="wb-mono"
                  data-testid={`process-map-status-${pm.dataProductId}`}
                  data-tone={statusTone(pm.status)}
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    padding: "2px 6px",
                    border: "1px solid currentColor",
                    color:
                      statusTone(pm.status) === "green"
                        ? "var(--wb-color-positive, #1f6b3a)"
                        : statusTone(pm.status) === "sepia"
                          ? "var(--wb-color-sepia, #8a6f33)"
                          : "var(--wb-color-hash-gray, #5f5b53)",
                  }}
                >
                  {pm.status}
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #5f5b53)",
                  }}
                >
                  {pm.payload.edges.length} edges ·{" "}
                  {Math.round(pm.payload.confidence * 100)}% confidence
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray, #5f5b53)",
                  }}
                >
                  {formatTs(pm.proposedAt)}
                </span>
              </button>

              {isExpanded && (
                <div
                  id={`pm-detail-${pm.dataProductId}`}
                  data-testid={`process-map-detail-${pm.dataProductId}`}
                  style={{
                    marginTop: 12,
                    paddingTop: 12,
                    borderTop:
                      "1px dotted var(--wb-color-rule, #d6d3cc)",
                  }}
                >
                  <ProcessMapEdgeTable edges={pm.payload.edges} />
                  <p
                    style={{
                      margin: "12px 0 0",
                      fontSize: 12,
                      color: "var(--wb-color-hash-gray, #5f5b53)",
                    }}
                  >
                    Window {formatTs(pm.payload.windowStart)} →{" "}
                    {formatTs(pm.payload.windowEnd)} · receipt{" "}
                    <span className="wb-mono">{pm.receipt.hash}</span>
                  </p>
                  <Link
                    href={`/data-products/${pm.dataProductId}`}
                    data-testid={`process-map-link-${pm.dataProductId}`}
                    style={{
                      display: "inline-block",
                      marginTop: 8,
                      fontSize: 12,
                      fontFamily: "var(--wb-font-serif)",
                      textDecoration: "underline",
                    }}
                  >
                    Confirm or archive in /data-products →
                  </Link>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ProcessMapEdgeTable({ edges }: { edges: ProcessMapEdge[] }) {
  if (edges.length === 0) {
    return (
      <p
        style={{
          margin: 0,
          fontSize: 12,
          color: "var(--wb-color-hash-gray, #5f5b53)",
        }}
      >
        Edges absent — this proposal arrived without a recorded triplet
        history. (Likely a replay artifact; investigate via /trace.)
      </p>
    );
  }
  return (
    <table
      data-testid="process-map-edges"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontSize: 12,
      }}
    >
      <thead>
        <tr style={{ textAlign: "left" }}>
          <th
            style={{
              padding: "4px 8px",
              borderBottom: "1px solid var(--wb-color-rule, #d6d3cc)",
              fontFamily: "var(--wb-font-serif)",
              fontWeight: 500,
            }}
          >
            From (asker)
          </th>
          <th
            style={{
              padding: "4px 8px",
              borderBottom: "1px solid var(--wb-color-rule, #d6d3cc)",
              fontFamily: "var(--wb-font-serif)",
              fontWeight: 500,
            }}
          >
            To (askee)
          </th>
          <th
            style={{
              padding: "4px 8px",
              borderBottom: "1px solid var(--wb-color-rule, #d6d3cc)",
              fontFamily: "var(--wb-font-serif)",
              fontWeight: 500,
            }}
          >
            Topic
          </th>
          <th
            style={{
              padding: "4px 8px",
              borderBottom: "1px solid var(--wb-color-rule, #d6d3cc)",
              fontFamily: "var(--wb-font-serif)",
              fontWeight: 500,
              textAlign: "right",
            }}
          >
            Frequency
          </th>
        </tr>
      </thead>
      <tbody>
        {edges.map((e, i) => (
          <tr
            key={`${e.fromPersonId}-${e.toPersonId}-${e.topic}-${i}`}
            data-testid="process-map-edge-row"
          >
            <td className="wb-mono" style={{ padding: "4px 8px" }}>
              {shortPersonId(e.fromPersonId)}
            </td>
            <td className="wb-mono" style={{ padding: "4px 8px" }}>
              {shortPersonId(e.toPersonId)}
            </td>
            <td style={{ padding: "4px 8px" }}>{e.topic}</td>
            <td
              className="wb-mono"
              style={{ padding: "4px 8px", textAlign: "right" }}
            >
              {e.frequency}×
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
