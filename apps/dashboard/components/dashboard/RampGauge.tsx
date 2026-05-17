/**
 * RampGauge — knowledge-ramp counter tile (Demo-day P2).
 *
 * One tile per axis: integer count + 60-bucket sparkline of the last
 * hour. The whole tile is a deep-link into ``/trace?kind=<filter>``;
 * clicking lands the user on the trace page filtered to the entry kinds
 * that contributed to this gauge, scrolled to the most recent
 * contributing row.
 *
 * Three instances are mounted on `/dashboard` — ontology, conversational,
 * relational — wired to the ``compute_knowledge_ramp_gauges`` projection
 * in worm-core via the ``/api/v1/dashboard/ramp`` route handler.
 *
 * Empty-state rule (PRD §7 P2): when the projection returns ``count=0``
 * the tile renders ``0`` honestly plus a hint string (no fixture
 * fallback). The sparkline degrades to a flat zero baseline.
 *
 * Editorial chrome — square corners, wb-mono eyebrow + counter, serif
 * description. No Tailwind, no emojis.
 */
import Link from "next/link";

export type RampGaugeAxis = "ontology" | "conversational" | "relational";

export interface RampGaugeProps {
  axis: RampGaugeAxis;
  /** Title rendered above the count. */
  label: string;
  /** Integer count over the entire ledger (0 is a valid honest value). */
  count: number;
  /** 60 per-minute counts, oldest → newest; use 0-vector for empty. */
  sparkline: ReadonlyArray<number>;
  /** Hint string rendered under the count when ``count === 0``. */
  emptyHint: string;
  /** Hint string rendered under the count when ``count > 0``. */
  populatedHint: string;
  /**
   * Trace-filter substring published by the projection. Becomes the
   * ``?kind=<value>`` on the deep-link.
   */
  traceFilter: string;
  /**
   * Most recent contributing row's ledger seq. Threaded through to
   * ``?last_seq=<value>`` so a future trace UX can scroll the row into
   * view; ignored if 0 (empty axis).
   */
  lastSeq: number;
  /** ISO-8601 timestamp of the most recent contributing row, or null. */
  lastTs: string | null;
}

export function RampGauge(props: RampGaugeProps) {
  const {
    axis,
    label,
    count,
    sparkline,
    emptyHint,
    populatedHint,
    traceFilter,
    lastSeq,
    lastTs,
  } = props;

  const isEmpty = count === 0;
  const traceHref = buildTraceHref(traceFilter, lastSeq);
  const ariaLabel = isEmpty
    ? `${label}: 0 entries; click to filter the trace by ${traceFilter}`
    : `${label}: ${count} entries; click to filter the trace by ${traceFilter}`;

  return (
    <Link
      href={traceHref}
      data-testid={`ramp-gauge-${axis}`}
      data-axis={axis}
      data-count={count}
      data-empty={isEmpty ? "true" : "false"}
      data-trace-filter={traceFilter}
      aria-label={ariaLabel}
      style={tileStyle}
    >
      <span className="wb-mono" style={eyebrowStyle}>
        ramp · {axis}
      </span>
      <span
        data-testid={`ramp-gauge-${axis}-count`}
        className="wb-mono"
        style={countStyle(isEmpty)}
      >
        {count}
      </span>
      <span style={titleStyle}>{label}</span>
      <Sparkline values={sparkline} />
      <span style={hintStyle}>{isEmpty ? emptyHint : populatedHint}</span>
      {lastTs ? (
        <span className="wb-mono" style={tsStyle}>
          most recent · {formatRelative(lastTs)}
        </span>
      ) : null}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Sparkline — pure SVG, 60 bars, deterministic geometry
// ---------------------------------------------------------------------------

interface SparklineProps {
  values: ReadonlyArray<number>;
}

const SPARKLINE_WIDTH = 220;
const SPARKLINE_HEIGHT = 32;
const SPARKLINE_GAP = 1;

function Sparkline({ values }: SparklineProps) {
  const max = values.reduce((m, v) => (v > m ? v : m), 0);
  const buckets = values.length || 1;
  const barW = Math.max(
    1,
    (SPARKLINE_WIDTH - (buckets - 1) * SPARKLINE_GAP) / buckets,
  );
  return (
    <svg
      data-testid="ramp-gauge-sparkline"
      data-bucket-count={buckets}
      data-max={max}
      role="img"
      aria-label={`sparkline · ${buckets} buckets · max ${max}`}
      width={SPARKLINE_WIDTH}
      height={SPARKLINE_HEIGHT}
      viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
      style={{ width: "100%", height: SPARKLINE_HEIGHT, display: "block" }}
    >
      {/* Baseline rule so empty sparklines aren't invisible. */}
      <line
        x1={0}
        x2={SPARKLINE_WIDTH}
        y1={SPARKLINE_HEIGHT - 0.5}
        y2={SPARKLINE_HEIGHT - 0.5}
        stroke="var(--wb-color-rule-line)"
        strokeWidth={1}
      />
      {values.map((v, i) => {
        const h = max > 0 ? (v / max) * (SPARKLINE_HEIGHT - 2) : 0;
        const x = i * (barW + SPARKLINE_GAP);
        const y = SPARKLINE_HEIGHT - h;
        if (h === 0) return null;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={h}
            fill="var(--wb-color-botanical-green)"
          />
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildTraceHref(traceFilter: string, lastSeq: number): string {
  const params = new URLSearchParams();
  if (traceFilter) params.set("kind", traceFilter);
  if (lastSeq > 0) params.set("last_seq", String(lastSeq));
  return `/trace?${params.toString()}`;
}

function formatRelative(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Inline styles — match the editorial WormActivityTile chrome
// ---------------------------------------------------------------------------

const tileStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "16px 18px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
  textDecoration: "none",
  color: "inherit",
  cursor: "pointer",
  minWidth: 0,
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const countStyle = (isEmpty: boolean): React.CSSProperties => ({
  fontSize: 40,
  fontWeight: 600,
  lineHeight: 1,
  letterSpacing: "-0.02em",
  color: isEmpty
    ? "var(--wb-color-hash-gray)"
    : "var(--wb-color-aged-ink)",
});

const titleStyle: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: 18,
  fontWeight: 500,
  letterSpacing: "-0.01em",
  color: "var(--wb-color-aged-ink)",
};

const hintStyle: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 13,
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.4,
};

const tsStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
};
