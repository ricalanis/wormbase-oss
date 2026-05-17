/**
 * LedgerThroughputCard — sparkline of ledger entries per minute.
 *
 * Renders the last `windowMinutes` 1-minute buckets as a stacked SVG
 * sparkline. Each bar height is `count / max(counts)`; empty buckets
 * render as a thin baseline tick so the absence of activity is still
 * visible. The total over the window is shown in the header.
 *
 * The card is presentational: it does not poll; the parent /ops page
 * polls the proxy and re-renders with fresh data.
 */

import type { LedgerThroughput } from "../../lib/ledger-client.types";

const SPARK_WIDTH = 360;
const SPARK_HEIGHT = 56;
const BAR_GAP = 2;

export function LedgerThroughputCard({
  throughput,
}: {
  throughput: LedgerThroughput;
}) {
  const buckets = throughput.buckets ?? [];
  const counts = buckets.map((b) => b.count);
  const peak = counts.length > 0 ? Math.max(1, ...counts) : 1;
  const barW =
    buckets.length > 0
      ? Math.max(2, (SPARK_WIDTH - BAR_GAP * (buckets.length - 1)) / buckets.length)
      : SPARK_WIDTH;
  return (
    <section
      data-testid="ops-ledger-throughput"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Ledger throughput · last {throughput.windowMinutes} min
      </span>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 32,
            fontWeight: 500,
            color: "var(--wb-color-aged-ink)",
          }}
          data-testid="ops-ledger-throughput-total"
        >
          {throughput.totalLastWindow.toLocaleString()}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          peak {peak.toLocaleString()} / min
        </span>
      </div>
      {buckets.length === 0 ? (
        <p
          data-testid="ops-ledger-throughput-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No throughput buckets reported yet — worm-core may still be warming.
        </p>
      ) : (
        <svg
          data-testid="ops-ledger-throughput-spark"
          role="img"
          aria-label={`Ledger entries per minute, last ${throughput.windowMinutes} minutes`}
          width={SPARK_WIDTH}
          height={SPARK_HEIGHT}
          viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
          style={{ display: "block" }}
        >
          {buckets.map((b, i) => {
            const h = Math.max(1, (b.count / peak) * (SPARK_HEIGHT - 4));
            const x = i * (barW + BAR_GAP);
            const y = SPARK_HEIGHT - h;
            return (
              <rect
                key={b.bucketStart}
                data-testid={`ops-ledger-throughput-bar-${i}`}
                data-count={b.count}
                x={x}
                y={y}
                width={barW}
                height={h}
                fill={
                  b.count === 0
                    ? "var(--wb-color-paper-edge)"
                    : "var(--wb-color-botanical-green-deep)"
                }
              >
                <title>
                  {b.bucketStart} · {b.count} entries
                </title>
              </rect>
            );
          })}
        </svg>
      )}
    </section>
  );
}
