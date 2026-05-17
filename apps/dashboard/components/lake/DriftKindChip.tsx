/**
 * DriftKindChip — colored chip for the strict 5-value
 * ``drift_kind`` enum surfaced on /lake/catalog-drift rows
 * (L2 Sub-wave D, 2026-06-09).
 *
 * Unlike L1's ``ProposedKindChip`` (free-form connector-registry
 * string), L2's ``drift_kind`` is a strict 5-value
 * ``Literal[...]`` (per spec §3.5):
 *
 *   - ``table_added`` — green (additive)
 *   - ``table_removed`` — red (destructive)
 *   - ``column_added`` — emerald (additive · smaller scope)
 *   - ``column_removed`` — rose (destructive · smaller scope)
 *   - ``column_type_changed`` — amber (warning · neutral)
 *
 * The 5 enum values are pinned at the ledger boundary
 * (:data:`wormbase_ledger.entries.CatalogDriftKind`); the chip
 * mirrors that pin — every value renders with a deterministic
 * color. Unlike L1's free-form unknown-tier fallback, there is no
 * "unknown" branch here: a value outside the 5-tuple is a programmer
 * error and falls through to a muted neutral palette as a defensive
 * guard, not as a productive UI state.
 */

"use client";

import type { CatalogDriftKind } from "../../lib/catalog-drift";

interface ChipColors {
  bg: string;
  fg: string;
  border: string;
}

/** Per-kind visual signature. The 5 enum values get distinct palette
 *  slots; out-of-enum values fall back to a muted neutral palette as
 *  a defensive guard (this is a programmer-error path, not a normal
 *  UI state — the ledger-side `Literal[...]` validator enforces the
 *  enum at write time). */
function kindChipStyle(kind: CatalogDriftKind | string): ChipColors {
  switch (kind) {
    case "table_added":
      // Botanical green — additive at the table level.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-botanical-green-deep, #2d5d3a)",
        border: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      };
    case "table_removed":
      // Deep red — destructive at the table level.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#a8323e",
        border: "#a8323e",
      };
    case "column_added":
      // Emerald — additive at the column level (smaller scope; same
      // family as table_added).
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#3d7350",
        border: "#3d7350",
      };
    case "column_removed":
      // Rose — destructive at the column level (smaller scope; same
      // family as table_removed but lighter).
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#a8366a",
        border: "#a8366a",
      };
    case "column_type_changed":
      // Amber — warning + neutral; type change is neither additive
      // nor destructive but signals a contract change.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
        border: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    default:
      // Defensive fallback — should never render in production
      // because the ledger Literal[...] validator pins the 5-tuple
      // at write time. Render muted neutral so the chip stays
      // legible if a future addition slips past a stale dashboard.
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
  }
}

const KNOWN_KINDS: ReadonlySet<string> = new Set<CatalogDriftKind>([
  "table_added",
  "table_removed",
  "column_added",
  "column_removed",
  "column_type_changed",
]);

function isKnown(kind: string): boolean {
  return KNOWN_KINDS.has(kind);
}

export interface DriftKindChipProps {
  kind: CatalogDriftKind | string;
  /** Test-id suffix so multiple chips on a page each get a unique
   *  ``data-testid``. */
  testIdSuffix: string;
}

export function DriftKindChip({
  kind,
  testIdSuffix,
}: DriftKindChipProps): JSX.Element {
  const c = kindChipStyle(kind);
  const known = isKnown(kind);
  return (
    <span
      data-testid={`catalog-drift-kind-chip-${testIdSuffix}`}
      data-kind={kind}
      data-known={known ? "true" : "false"}
      data-color={c.fg}
      aria-label={
        known ? `drift_kind=${kind}` : `drift_kind=${kind} (unknown)`
      }
      className="wb-mono"
      style={{
        display: "inline-block",
        padding: "2px 8px",
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.fg,
        fontSize: 10,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontWeight: 600,
        opacity: known ? 1.0 : 0.7,
      }}
    >
      {kind}
    </span>
  );
}
