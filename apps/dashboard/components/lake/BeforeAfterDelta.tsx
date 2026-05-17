/**
 * BeforeAfterDelta — compact rendering of the before→after dict
 * diff on /lake/catalog-drift rows (L2 Sub-wave D, 2026-06-09).
 *
 * Per-drift_kind rendering:
 *
 *   * ``column_type_changed`` — render ``varchar(255) → text`` style
 *     (extracts ``type`` key from before/after dicts when present;
 *     falls back to a JSON-compact stringification if not).
 *   * ``table_added`` / ``column_added`` — render ``+ <descriptor>``
 *     in additive green; descriptor comes from ``after`` dict's
 *     ``table_id`` / ``column_name`` key when present, else
 *     JSON-stringify of the dict.
 *   * ``table_removed`` / ``column_removed`` — render ``− <descriptor>``
 *     in destructive red with strikethrough; descriptor comes from
 *     ``before``.
 *
 * Honest empty: when both before AND after are NULL (which should
 * never happen for any legal drift_kind given the ledger payload's
 * model_post_init invariants), render an italic em-dash.
 */

"use client";

import type { CatalogDriftKind } from "../../lib/catalog-drift";

export interface BeforeAfterDeltaProps {
  driftKind: CatalogDriftKind;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  /** Test-id suffix so multiple deltas on a page each get a unique
   *  ``data-testid``. */
  testIdSuffix: string;
}

/** Extract a short human-readable descriptor from a before/after
 *  dict. Prefers ``type`` (column_type_changed) then ``table_id``
 *  (table_added/_removed) then ``column_name`` (column_added/_removed)
 *  then a JSON-compact stringification of the dict. */
function descriptorOf(dict: Record<string, unknown> | null): string {
  if (dict === null) return "—";
  if (typeof dict.type === "string") return dict.type;
  if (typeof dict.table_id === "string") return dict.table_id;
  if (typeof dict.column_name === "string") return dict.column_name;
  if (typeof dict.name === "string") return dict.name;
  // Fall back to a compact JSON stringification — strategy-emitted
  // evidence shouldn't normally hit this branch, but if it does we
  // want the page to render readably rather than crash.
  try {
    const s = JSON.stringify(dict);
    return s.length > 64 ? `${s.slice(0, 61)}…` : s;
  } catch {
    return "(unrenderable)";
  }
}

export function BeforeAfterDelta({
  driftKind,
  before,
  after,
  testIdSuffix,
}: BeforeAfterDeltaProps): JSX.Element {
  const baseStyle: React.CSSProperties = {
    fontFamily: "var(--wb-font-serif)",
    fontSize: 12,
  };

  if (driftKind === "column_type_changed") {
    // Both before AND after are required for column_type_changed
    // per the ledger payload's model_post_init invariant.
    const beforeStr = descriptorOf(before);
    const afterStr = descriptorOf(after);
    return (
      <span
        data-testid={`catalog-drift-delta-${testIdSuffix}`}
        data-drift-kind={driftKind}
        style={{
          ...baseStyle,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <code
          className="wb-mono"
          data-testid={`catalog-drift-delta-before-${testIdSuffix}`}
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink, #2a2620)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: "1px 6px",
            border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          }}
        >
          {beforeStr}
        </code>
        <span
          className="wb-mono"
          aria-hidden="true"
          style={{
            color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          →
        </span>
        <code
          className="wb-mono"
          data-testid={`catalog-drift-delta-after-${testIdSuffix}`}
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: "1px 6px",
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
          }}
        >
          {afterStr}
        </code>
      </span>
    );
  }

  if (driftKind === "table_added" || driftKind === "column_added") {
    const desc = descriptorOf(after);
    return (
      <span
        data-testid={`catalog-drift-delta-${testIdSuffix}`}
        data-drift-kind={driftKind}
        className="wb-mono"
        style={{
          ...baseStyle,
          color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        <span aria-hidden="true" style={{ fontWeight: 700 }}>
          +
        </span>
        <code
          data-testid={`catalog-drift-delta-after-${testIdSuffix}`}
          style={{ fontSize: 11 }}
        >
          {desc}
        </code>
      </span>
    );
  }

  if (driftKind === "table_removed" || driftKind === "column_removed") {
    const desc = descriptorOf(before);
    return (
      <span
        data-testid={`catalog-drift-delta-${testIdSuffix}`}
        data-drift-kind={driftKind}
        className="wb-mono"
        style={{
          ...baseStyle,
          color: "#a8323e",
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        <span aria-hidden="true" style={{ fontWeight: 700 }}>
          −
        </span>
        <code
          data-testid={`catalog-drift-delta-before-${testIdSuffix}`}
          style={{ fontSize: 11, textDecoration: "line-through" }}
        >
          {desc}
        </code>
      </span>
    );
  }

  // Defensive fallback — should never render given the 5-value enum,
  // but keep the surface legible if a future addition slips past a
  // stale dashboard.
  return (
    <span
      data-testid={`catalog-drift-delta-${testIdSuffix}`}
      data-drift-kind={driftKind}
      style={{
        ...baseStyle,
        fontStyle: "italic",
        color: "var(--wb-color-hash-gray, #7c7569)",
      }}
    >
      —
    </span>
  );
}
