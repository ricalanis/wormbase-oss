"use client";
/**
 * HeadlineMetricSparkline — small SVG line chart of metric_observed
 * samples for a single position. Deterministic layout: same points,
 * same coordinates, same hash (Triad C2 stays visible).
 */

import type { HeadlineMetricSeries } from "../../lib/ledger-client.types";

export function HeadlineMetricSparkline({
  series,
}: {
  series: HeadlineMetricSeries;
}) {
  const points = series.points;
  if (points.length === 0) {
    return (
      <p
        data-testid="sparkline-no-points"
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No samples for {series.position} · {series.metricId}.
      </p>
    );
  }

  const width = 480;
  const height = 80;
  const padX = 8;
  const padY = 8;

  const values = points.map((p) => p.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const span = maxV - minV || 1;

  const scaleX = (i: number): number => {
    if (points.length === 1) return width / 2;
    return (
      padX + ((width - 2 * padX) * i) / (points.length - 1)
    );
  };
  const scaleY = (v: number): number =>
    height - padY - ((height - 2 * padY) * (v - minV)) / span;

  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${scaleX(i).toFixed(1)} ${scaleY(p.value).toFixed(1)}`)
    .join(" ");

  return (
    <figure
      data-testid="headline-sparkline"
      data-position={series.position}
      data-metric={series.metricId}
      style={{
        margin: 0,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "12px 16px",
        border: "1px solid var(--wb-color-rule-line)",
        background: "var(--wb-color-paper)",
      }}
    >
      <figcaption
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          fontFamily: "var(--wb-font-serif)",
        }}
      >
        <span
          style={{
            fontWeight: 500,
            fontSize: "var(--wb-text-md)",
          }}
        >
          {series.position} · {series.metricId}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.14em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {points.length} sample{points.length === 1 ? "" : "s"}
        </span>
      </figcaption>
      <svg
        role="img"
        aria-label={`${series.position} ${series.metricId} sparkline`}
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: 80 }}
      >
        <path
          d={path}
          fill="none"
          stroke="var(--wb-color-botanical-green)"
          strokeWidth={1.5}
        />
        {points.map((p, i) => (
          <circle
            key={`${p.observedAt}-${i}`}
            cx={scaleX(i)}
            cy={scaleY(p.value)}
            r={2}
            fill="var(--wb-color-aged-ink)"
            data-testid={`sparkline-point-${i}`}
          />
        ))}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--wb-font-mono)",
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        <span>min {minV.toFixed(2)}</span>
        <span>max {maxV.toFixed(2)}</span>
        <span>latest {points[points.length - 1].value.toFixed(2)}</span>
      </div>
    </figure>
  );
}
