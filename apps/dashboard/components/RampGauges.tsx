import { Gauge } from "@wormbase/design";
import { Receipt } from "../lib/receipts";
import type { RampGaugeRow } from "../lib/ledger-client.types";

/**
 * RampGauges — six-axis Knowledge Ramp wired to live ledger projections.
 *
 * Each gauge displays its arc + a Receipt below proving it's ledger-derived
 * (PRD §4.4: "the Receipt is NOT optional; it is the visual proof that the
 * gauge is ledger-derived"). The arc breathes (±0.5% / 3s) via the Gauge
 * primitive's idle animation.
 */

export interface RampGaugesProps {
  axes: RampGaugeRow[];
}

export function RampGauges({ axes }: RampGaugesProps) {
  return (
    <section
      aria-label="Knowledge ramp · six axes"
      data-testid="ramp-gauges-section"
      style={{ display: "flex", flexDirection: "column", gap: 20 }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          borderBottom: "1px solid var(--wb-color-aged-ink)",
          paddingBottom: 8,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-lg)",
            fontWeight: 600,
            letterSpacing: "-0.005em",
          }}
        >
          Knowledge ramp
        </h2>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          projection · live · ramp_gauge_v1
        </span>
      </header>

      <div
        data-testid="ramp-gauges"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          columnGap: 24,
          rowGap: 32,
          padding: "16px 0 8px",
        }}
      >
        {axes.map((axis, i) => (
          <figure
            key={axis.axis}
            data-testid={`gauge-${axis.axis}`}
            data-value={axis.value}
            style={{
              margin: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
            }}
          >
            <Gauge label={axis.label} value={axis.value} staggerIndex={i} />
            <figcaption
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                fontSize: 13,
                color: "var(--wb-color-aged-ink-soft)",
                textAlign: "center",
                maxWidth: 220,
              }}
            >
              {axis.hint}
            </figcaption>
            <div style={{ width: "100%", maxWidth: 280 }}>
              <Receipt
                hash={axis.receipt.hash}
                source={axis.receipt.source}
                owner={axis.receipt.owner}
                classification={axis.receipt.classification}
                compact
              />
            </div>
          </figure>
        ))}
      </div>

      <footer
        style={{
          borderTop: "1px solid var(--wb-color-rule-line)",
          paddingTop: 12,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: "var(--wb-text-sm)",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Six axes. Each breathes ±0.5% every three seconds — the worm is alive
        but controlled. Values come from the <span className="wb-mono">
        ramp_gauge_v1</span> projection seeded by the worm-core ramp loop.
      </footer>
    </section>
  );
}
