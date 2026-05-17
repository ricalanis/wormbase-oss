/**
 * ConnectorCatalogRow — single row in the /lake/surfaces marketplace
 * shell (L3 Sub-wave D + Onboarding Sub-wave D polish).
 *
 * Renders the connector kind, status badge, capability set, connection
 * state, and the per-tenant probe result (Sub-wave D polish: honest
 * "works / degraded / failed / unknown" pill, never fake-positive).
 * Production rows with no active source get an "Add source" affordance
 * pointing at ``/sources/new/{kind}`` (the existing connector-picker
 * page). Stripe routes to ``/sources/new/stripe`` which renders the
 * OAuth-graduated landing. Coming-soon rows are muted with no action.
 */

import Link from "next/link";

import type {
  ConnectorCatalogRow as Row,
  ConnectorProbeState,
} from "../../lib/connectors";

export interface ConnectorCatalogRowProps {
  row: Row;
}

function badgeStyle(state: Row["connectionState"]): {
  label: string;
  color: string;
} {
  switch (state) {
    case "connected":
      return {
        label: "connected",
        color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      };
    case "available":
      return {
        label: "always-available",
        color: "var(--wb-color-hash-gray, #7c7569)",
      };
    case "disconnected":
      return {
        label: "disconnected",
        color: "var(--wb-color-hash-gray, #7c7569)",
      };
  }
}

function statusColor(status: Row["status"]): string {
  switch (status) {
    case "production":
      return "var(--wb-color-botanical-green-deep, #2d5d3a)";
    case "preview":
      return "var(--wb-color-sepia-warning-deep, #b6741c)";
    case "coming_soon":
      return "var(--wb-color-hash-gray, #7c7569)";
  }
}

function probeLabelAndColor(state: ConnectorProbeState | null | undefined): {
  label: string;
  color: string;
} {
  switch (state) {
    case "works":
      return {
        label: "probe · works",
        color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      };
    case "degraded":
      return {
        label: "probe · degraded",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "failed":
      return {
        label: "probe · failed",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "unknown":
    default:
      return {
        label: "probe · unknown",
        color: "var(--wb-color-hash-gray, #7c7569)",
      };
  }
}

/**
 * Resolve the "Add source" link target per connector. Stripe routes to
 * its OAuth-graduated landing at ``/sources/new/stripe``; everything
 * else routes to the generic configurator at ``/sources/new/{kind}``.
 */
function addSourceHref(kind: string): string {
  if (kind === "stripe") return "/sources/new/stripe";
  return `/sources/new/${encodeURIComponent(kind)}`;
}

export function ConnectorCatalogRow({
  row,
}: ConnectorCatalogRowProps): JSX.Element {
  const badge = badgeStyle(row.connectionState);
  const probe = probeLabelAndColor(row.probe?.state ?? null);
  const muted = row.status === "coming_soon";
  return (
    <li
      data-testid={`connector-row-${row.kind}`}
      style={{
        display: "grid",
        gridTemplateColumns:
          "minmax(180px, 220px) 1fr minmax(140px, 170px) minmax(100px, 120px)",
        gap: 12,
        alignItems: "baseline",
        padding: "10px 12px",
        borderTop: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
        opacity: muted ? 0.7 : 1,
        background: "var(--wb-color-paper, #f8f3e1)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <strong
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            color: "var(--wb-color-aged-ink, #2a2620)",
          }}
        >
          {row.label}
        </strong>
        <code
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          {row.kind}
        </code>
      </div>
      <div
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          fontStyle: "italic",
          color: "var(--wb-color-aged-ink, #2a2620)",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <span>{row.description}</span>
        {row.capabilities.length > 0 ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {row.capabilities.join(" · ")}
          </span>
        ) : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          data-testid={`connector-status-${row.kind}`}
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: statusColor(row.status),
          }}
        >
          {row.status.replace("_", " ")}
        </span>
        <span
          className="wb-mono"
          data-testid={`connector-connection-${row.kind}`}
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: badge.color,
          }}
        >
          {badge.label}
          {row.activeSourceCount > 1 ? ` · ${row.activeSourceCount}` : ""}
        </span>
        {row.status !== "coming_soon" ? (
          <Link
            href={`/status/connector/${encodeURIComponent(row.kind)}`}
            data-testid={`connector-probe-${row.kind}`}
            title={row.probe?.reason ?? "probe state"}
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: probe.color,
              textDecoration: "none",
            }}
          >
            {probe.label}
          </Link>
        ) : null}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        {row.status === "coming_soon" ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Notify me (v1.5)
          </span>
        ) : row.connectionState === "available" ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            No setup
          </span>
        ) : (
          <Link
            href={addSourceHref(row.kind)}
            data-testid={`connector-add-source-${row.kind}`}
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              padding: "5px 10px",
              border: "1px solid var(--wb-color-aged-ink, #2a2620)",
              background: "var(--wb-color-paper, #f8f3e1)",
              color: "var(--wb-color-aged-ink, #2a2620)",
              textDecoration: "none",
            }}
          >
            {row.connectionState === "connected" ? "Add another" : "Add source"}
          </Link>
        )}
      </div>
    </li>
  );
}
