/**
 * RecentActivityStream — last-N activity rows for /lake/overview.
 *
 * One row per state-change across the 8 lake-side projections, with
 * relative-timestamp formatting + drill-in links that use the
 * producer-side deep-link primary-key URL param when the axis's page
 * supports it.
 *
 * Honest empty when the activity list is empty: renders a single
 * panel pointing the operator at the activity feed + the per-axis
 * env knobs.
 */
import Link from "next/link";

import type { RecentActivityRow } from "../../lib/lake-overview";

export interface RecentActivityStreamProps {
  rows: RecentActivityRow[];
  /** Override the "now" timestamp the relative formatter compares
   *  against. Tests inject a fixed clock; production renders against
   *  ``new Date()``. */
  now?: Date;
}

/** Render a relative-time string ("3m ago" / "1h ago" / "2d ago").
 *  Falls back to the ISO date string for items older than 30 days. */
export function _formatRelative(ts: Date, now: Date = new Date()): string {
  const ms = now.getTime() - ts.getTime();
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return ts.toISOString().slice(0, 10);
}

function actionTone(action: string): string {
  // confirmed / promoted / acknowledged → green; rejected → muted;
  // proposed → ink.
  if (
    action === "confirmed" ||
    action === "promoted" ||
    action === "acknowledged"
  ) {
    return "var(--wb-color-botanical-green-deep, #2d5d3a)";
  }
  if (action === "rejected") return "var(--wb-color-hash-gray, #7c7569)";
  return "var(--wb-color-aged-ink, #463f33)";
}

export function RecentActivityStream({
  rows,
  now,
}: RecentActivityStreamProps): JSX.Element {
  if (rows.length === 0) {
    return (
      <section
        data-testid="lake-overview-activity-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge, #ddd3bd)",
          background: "var(--wb-color-paper-deep, #f4eee1)",
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          Recent activity · 0
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray, #7c7569)",
            fontSize: 13,
          }}
        >
          No lake activity yet. Once the inference axes start firing on
          incoming catalog snapshots, state changes appear here across
          all 8 axes — newest first.
        </p>
      </section>
    );
  }

  return (
    <ol
      data-testid="lake-overview-activity-stream"
      style={{
        margin: 0,
        padding: 0,
        listStyle: "none",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {rows.map((row, idx) => (
        <li
          key={`${row.axis}-${row.ts.toISOString()}-${idx}`}
          data-testid={`lake-overview-activity-row-${idx}`}
          data-axis={row.axis}
          data-action={row.action}
          style={{
            display: "grid",
            gridTemplateColumns: "70px 60px 1fr 80px",
            gap: 8,
            alignItems: "baseline",
            padding: "6px 8px",
            borderBottom:
              "1px solid var(--wb-color-paper-edge, #ddd3bd)",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {_formatRelative(row.ts, now)}
          </span>
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.10em",
              color: "var(--wb-color-aged-ink, #463f33)",
            }}
          >
            {row.axis}
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
            }}
          >
            <span
              data-testid={`lake-overview-activity-action-${idx}`}
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.10em",
                textTransform: "uppercase",
                color: actionTone(row.action),
                marginRight: 6,
              }}
            >
              {row.action}
            </span>
            <span style={{ color: "var(--wb-color-aged-ink, #463f33)" }}>
              {row.description}
            </span>
          </span>
          {row.href ? (
            <Link
              data-testid={`lake-overview-activity-link-${idx}`}
              href={row.href}
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 11,
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textAlign: "right",
              }}
            >
              Open →
            </Link>
          ) : (
            <span />
          )}
        </li>
      ))}
    </ol>
  );
}
