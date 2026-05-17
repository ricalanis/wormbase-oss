"use client";
/**
 * ConnectorCard — one card per connector kind in /sources/new grid.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Three card states driven by `status`:
 *   - production: green pill; full-color card; routes to /sources/new/<kind>
 *     on click.
 *   - preview: amber pill + tooltip; clicking still routes to the form
 *     (the per-connector page renders a "preview" banner inline).
 *   - coming_soon: gray pill; muted card (50% opacity); aria-disabled;
 *     clicking is suppressed and a tooltip explains the ETA per docs.
 *
 * Capability honesty is non-negotiable — coming_soon connectors NEVER
 * route to a config form, never start an OAuth flow, never call
 * `Connector.authenticate`. The picker labels them honestly.
 */
import Link from "next/link";
import type { ConnectorEntry, ConnectorStatus } from "../../app/api/v1/connectors/list/route";

interface StatusVisuals {
  pillLabel: string;
  pillColor: string;
  pillBorder: string;
  cardBg: string;
  cardBorderLeft: string;
  opacity: number;
  cursor: string;
}

function visualsFor(status: ConnectorStatus): StatusVisuals {
  switch (status) {
    case "production":
      return {
        pillLabel: "production",
        pillColor: "var(--wb-color-botanical-green-deep)",
        pillBorder: "var(--wb-color-botanical-green)",
        cardBg: "var(--wb-color-paper)",
        cardBorderLeft: "3px solid var(--wb-color-botanical-green)",
        opacity: 1,
        cursor: "pointer",
      };
    case "preview":
      return {
        pillLabel: "preview",
        pillColor: "var(--wb-color-sepia-warning-deep)",
        pillBorder: "var(--wb-color-sepia-warning-deep)",
        cardBg: "var(--wb-color-paper)",
        cardBorderLeft: "3px solid var(--wb-color-sepia-warning-deep)",
        opacity: 0.95,
        cursor: "pointer",
      };
    case "coming_soon":
    default:
      return {
        pillLabel: "coming soon",
        pillColor: "var(--wb-color-hash-gray)",
        pillBorder: "var(--wb-color-paper-edge)",
        cardBg: "var(--wb-color-paper-deep)",
        cardBorderLeft: "3px solid var(--wb-color-hash-gray)",
        opacity: 0.5,
        cursor: "not-allowed",
      };
  }
}

export function ConnectorCard({ entry }: { entry: ConnectorEntry }) {
  const v = visualsFor(entry.status);
  const isComingSoon = entry.status === "coming_soon";
  const tooltip = isComingSoon
    ? `${entry.status_note} ETA per docs.`
    : entry.status_note;

  const cardInner = (
    <>
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
          }}
        >
          {entry.label}
        </span>
        <span
          className="wb-mono"
          data-testid={`connector-status-pill-${entry.kind}`}
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: v.pillColor,
            border: `1px solid ${v.pillBorder}`,
            padding: "1px 6px",
            borderRadius: 0,
            whiteSpace: "nowrap",
          }}
        >
          {v.pillLabel}
        </span>
      </header>
      <span
        data-testid={`connector-status-note-${entry.kind}`}
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          color: isComingSoon
            ? "var(--wb-color-hash-gray)"
            : "var(--wb-color-aged-ink)",
          fontStyle: isComingSoon ? "italic" : "normal",
          lineHeight: 1.4,
        }}
      >
        {entry.status_note}
      </span>
      <div
        style={{ display: "flex", flexWrap: "wrap", gap: 4 }}
        data-testid={`connector-caps-${entry.kind}`}
      >
        {entry.capabilities.map((cap) => (
          <span
            key={cap}
            className="wb-mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
              border: "1px solid var(--wb-color-paper-edge)",
              padding: "1px 5px",
              borderRadius: 0,
            }}
          >
            {cap}
          </span>
        ))}
      </div>
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          color: "var(--wb-color-aged-ink-soft)",
        }}
      >
        kind: {entry.kind}
      </span>
    </>
  );

  const sharedStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    textAlign: "left",
    padding: 14,
    background: v.cardBg,
    border: "1px solid var(--wb-color-paper-edge)",
    borderLeft: v.cardBorderLeft,
    borderRadius: 0,
    opacity: v.opacity,
    cursor: v.cursor,
    color: "var(--wb-color-aged-ink)",
    textDecoration: "none",
  };

  if (isComingSoon) {
    return (
      <div
        data-testid={`connector-card-${entry.kind}`}
        data-status={entry.status}
        data-kind={entry.kind}
        aria-disabled="true"
        title={tooltip}
        style={sharedStyle}
      >
        {cardInner}
      </div>
    );
  }

  return (
    <Link
      href={`/sources/new/${encodeURIComponent(entry.kind)}`}
      data-testid={`connector-card-${entry.kind}`}
      data-status={entry.status}
      data-kind={entry.kind}
      title={tooltip}
      style={sharedStyle}
    >
      {cardInner}
    </Link>
  );
}
