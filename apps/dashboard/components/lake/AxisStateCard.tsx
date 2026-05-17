/**
 * AxisStateCard — single card in the /lake/overview axis grid.
 *
 * Shows axis label + descriptive name + proposed / affirmed / rejected
 * counts + a color-coded health chip + a link to the axis's detail
 * page. Honors the 3-pattern affirmative-state doctrine: the badge
 * prose carries the per-axis affirmative state name verbatim
 * (``confirmed`` / ``promoted`` / ``acknowledged``).
 *
 * Color logic on the health chip:
 *   * gray   — proposed = 0 AND affirmed = 0 AND rejected = 0 (no activity).
 *   * green  — proposed > 0 AND affirmed ≥ proposed (mostly affirmed).
 *   * amber  — proposed > 0 AND affirmed < proposed (mostly pending).
 *   * stone  — affirmed > 0 OR rejected > 0 only (no pending — steady state).
 */
import Link from "next/link";

import type { AxisStateRow } from "../../lib/lake-overview";

export interface AxisStateCardProps {
  row: AxisStateRow;
}

interface HealthChip {
  label: string;
  bg: string;
  fg: string;
  border: string;
  health: "green" | "amber" | "stone" | "gray";
}

function healthChip(row: AxisStateRow): HealthChip {
  const noActivity =
    row.proposedCount === 0 &&
    row.affirmedCount === 0 &&
    row.rejectedCount === 0;
  if (noActivity) {
    return {
      label: "no activity",
      bg: "var(--wb-color-paper-deep, #f4eee1)",
      fg: "var(--wb-color-hash-gray, #7c7569)",
      border: "var(--wb-color-paper-edge, #ddd3bd)",
      health: "gray",
    };
  }
  if (row.proposedCount === 0) {
    return {
      label: "steady",
      bg: "var(--wb-color-paper-deep, #f4eee1)",
      fg: "var(--wb-color-aged-ink, #463f33)",
      border: "var(--wb-color-paper-edge, #ddd3bd)",
      health: "stone",
    };
  }
  if (row.affirmedCount >= row.proposedCount) {
    return {
      label: "healthy",
      bg: "var(--wb-color-botanical-green-soft, #d8e2cb)",
      fg: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      border: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      health: "green",
    };
  }
  return {
    label: "review pending",
    bg: "var(--wb-color-sepia-warning-soft, #f4e4c4)",
    fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
    border: "var(--wb-color-sepia-warning-deep, #b6741c)",
    health: "amber",
  };
}

export function AxisStateCard({ row }: AxisStateCardProps): JSX.Element {
  const chip = healthChip(row);
  const total = row.proposedCount + row.affirmedCount + row.rejectedCount;
  return (
    <article
      data-testid={`lake-overview-axis-card-${row.axis}`}
      data-axis={row.axis}
      data-health={chip.health}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 14,
        border: "1px solid var(--wb-color-paper-edge, #ddd3bd)",
        background: "var(--wb-color-paper, #faf6e9)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          {row.axis} · {row.axisName}
        </span>
        <span
          data-testid={`lake-overview-axis-chip-${row.axis}`}
          data-health={chip.health}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "2px 6px",
            background: chip.bg,
            color: chip.fg,
            border: `1px solid ${chip.border}`,
          }}
        >
          {chip.label}
        </span>
      </header>
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 4,
          margin: 0,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <dt
            className="wb-mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            proposed
          </dt>
          <dd
            data-testid={`lake-overview-axis-count-${row.axis}-proposed`}
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              color: "var(--wb-color-aged-ink, #463f33)",
            }}
          >
            {row.proposedCount}
          </dd>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <dt
            className="wb-mono"
            data-testid={`lake-overview-axis-affirmative-label-${row.axis}`}
            style={{
              fontSize: 9,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {row.affirmativeStateLabel}
          </dt>
          <dd
            data-testid={`lake-overview-axis-count-${row.axis}-affirmed`}
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
            }}
          >
            {row.affirmedCount}
          </dd>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <dt
            className="wb-mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            rejected
          </dt>
          <dd
            data-testid={`lake-overview-axis-count-${row.axis}-rejected`}
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {row.rejectedCount}
          </dd>
        </div>
      </dl>
      <footer
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.10em",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          {total} total
        </span>
        <Link
          data-testid={`lake-overview-axis-link-${row.axis}`}
          href={row.axisHref}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
            color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
          }}
        >
          Open page →
        </Link>
      </footer>
    </article>
  );
}
