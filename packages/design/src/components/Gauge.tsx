"use client";

import { type CSSProperties, useEffect, useRef, useState } from "react";

export interface GaugeProps {
  label: string;
  /** Target value 0–100. */
  value: number;
  /** Label displayed under the arc — defaults to "%". */
  unit?: string;
  /** When true, the mounted animation is skipped (used in tests / reduced motion). */
  instant?: boolean;
  /** Stagger index for orchestrated page load. */
  staggerIndex?: number;
  style?: CSSProperties;
}

/**
 * Field Notebook Gauge — arc shape, breathing idle animation (±0.5% per 3s),
 * botanical green arc, mono percentage label. The worm is alive but controlled.
 */
export function Gauge({
  label,
  value,
  unit = "%",
  instant = false,
  staggerIndex = 0,
  style,
}: GaugeProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const [displayValue, setDisplayValue] = useState(instant ? clamped : 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (instant) {
      setDisplayValue(clamped);
      return;
    }

    const delay = staggerIndex * 80;
    const duration = 900;
    let start: number | null = null;
    const from = 0;
    const to = clamped;

    const timeout = setTimeout(() => {
      const tick = (t: number) => {
        if (start === null) start = t;
        const elapsed = t - start;
        const p = Math.min(1, elapsed / duration);
        // ease-out-cubic for a decisive arrival
        const eased = 1 - Math.pow(1 - p, 3);
        setDisplayValue(from + (to - from) * eased);
        if (p < 1) rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    }, delay);

    return () => {
      clearTimeout(timeout);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [clamped, instant, staggerIndex]);

  // Arc geometry — 180° open arc, 120 viewBox
  const size = 140;
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = Math.PI * radius; // half circle
  const progress = (displayValue / 100) * circumference;

  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "var(--wb-space-2)",
        animation: instant
          ? undefined
          : `wb-breathe var(--wb-duration-breathing) var(--wb-ease-breathing) infinite`,
        ...style,
      }}
    >
      <svg
        width={size}
        height={size / 2 + 18}
        viewBox={`0 0 ${size} ${size / 2 + 18}`}
        aria-hidden="true"
      >
        <path
          d={describeArc(size / 2, size / 2, radius)}
          stroke="var(--wb-color-rule-line)"
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="butt"
        />
        <path
          d={describeArc(size / 2, size / 2, radius)}
          stroke="var(--wb-color-botanical-green)"
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="butt"
          strokeDasharray={`${progress} ${circumference - progress}`}
        />
        <text
          x={size / 2}
          y={size / 2 + 2}
          textAnchor="middle"
          fontFamily="var(--wb-font-mono)"
          fontSize="22"
          fontWeight={600}
          fill="var(--wb-color-aged-ink)"
        >
          {Math.round(displayValue)}
          <tspan
            fontSize="12"
            fill="var(--wb-color-hash-gray)"
            dx="2"
            dy="-6"
          >
            {unit}
          </tspan>
        </text>
      </svg>
      <div
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: "var(--wb-text-sm)",
          color: "var(--wb-color-aged-ink)",
          letterSpacing: "0.02em",
          textAlign: "center",
        }}
      >
        {label}
      </div>
    </div>
  );
}

function describeArc(cx: number, cy: number, r: number): string {
  // 180° arc from (cx-r, cy) to (cx+r, cy) sweeping through the top
  const start = `${cx - r} ${cy}`;
  const end = `${cx + r} ${cy}`;
  return `M ${start} A ${r} ${r} 0 0 1 ${end}`;
}
