/**
 * AxisStateGrid — 4×2 grid of axis cards for /lake/overview.
 *
 * Pure layout — no per-axis logic; defers all card content to
 * :component:`AxisStateCard`. Re-orders the canonical L1..L8 reading
 * order into a stable presentational order driven by axis type:
 * compounding-axes (L3..L8) first, prequel-triage (L1, L2) last.
 */
import type { AxisStateRow } from "../../lib/lake-overview";

import { AxisStateCard } from "./AxisStateCard";

export interface AxisStateGridProps {
  rows: AxisStateRow[];
}

/** Presentation order — compounding axes first, then prequel-triage.
 *  Stable across renders so the grid layout doesn't shift. */
const PRESENTATION_ORDER = ["L3", "L4", "L5", "L6", "L7", "L8", "L1", "L2"] as const;

export function AxisStateGrid({ rows }: AxisStateGridProps): JSX.Element {
  const byAxis = new Map(rows.map((r) => [r.axis, r]));
  const ordered = PRESENTATION_ORDER.map((axis) => byAxis.get(axis)).filter(
    (r): r is AxisStateRow => r !== undefined,
  );

  return (
    <div
      data-testid="lake-overview-axis-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
      }}
    >
      {ordered.map((row) => (
        <AxisStateCard key={row.axis} row={row} />
      ))}
    </div>
  );
}
