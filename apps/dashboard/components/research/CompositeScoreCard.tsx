"use client";
/**
 * CompositeScoreCard — descending loss curve over the trailing 7-day
 * window (Demo-day P1).
 *
 * Renders ≥9 sampled points from `getCompositeScoreSeries`. Each point
 * is clickable: clicking opens `/trace?seqLo=…&seqHi=…` filtered to
 * the contributing ledger range. The top-contributing-reactivity badge
 * surfaces below each point so the demo arc can call out *which*
 * Reactivity moved the curve.
 *
 * Display value is the LeCun loss-style projection: `1 - score`. The
 * lower the curve descends, the better the worm is performing
 * autoresearch within the trailing window.
 *
 * Empty state: when the series is empty (Postgres unreachable, brand-new
 * tenant), the card renders a brief honest empty message rather than a
 * fabricated baseline. Per CLAUDE.md ¶9 — no flow-bypass, no fixture.
 */

import Link from "next/link";
import type { CompositeScoreSeries } from "../../lib/ledger-client.types";

const CHART_W = 640;
const CHART_H = 160;
const PAD_X = 32;
const PAD_Y = 24;

export interface CompositeScoreCardProps {
  series: CompositeScoreSeries;
}

export function CompositeScoreCard({ series }: CompositeScoreCardProps) {
  const points = series.points;
  const hasPoints = points.length > 0;

  // Loss is 1 - score. Range is always [0, 1] so the chart axis is fixed.
  const lossPoints = points.map((p, i) => ({
    i,
    point: p,
    loss: Math.max(0, Math.min(1, 1 - p.score)),
  }));

  const scaleX = (i: number): number => {
    if (lossPoints.length === 1) return CHART_W / 2;
    return PAD_X + ((CHART_W - 2 * PAD_X) * i) / (lossPoints.length - 1);
  };
  const scaleY = (loss: number): number =>
    PAD_Y + (CHART_H - 2 * PAD_Y) * loss;

  const path = lossPoints
    .map(
      ({ i, loss }) =>
        `${i === 0 ? "M" : "L"} ${scaleX(i).toFixed(1)} ${scaleY(loss).toFixed(1)}`,
    )
    .join(" ");

  const firstLoss = lossPoints[0]?.loss;
  const lastLoss = lossPoints[lossPoints.length - 1]?.loss;
  const direction =
    typeof firstLoss === "number" && typeof lastLoss === "number"
      ? lastLoss < firstLoss
        ? "descending"
        : lastLoss > firstLoss
          ? "ascending"
          : "flat"
      : "flat";

  return (
    <section
      data-testid="composite-score-card"
      data-direction={direction}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderTop: "1px solid var(--wb-color-rule-line)",
        paddingTop: 24,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. IX.b · composite_score · loss-style · trailing {series.windowDays}d
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          Composite score
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Equal-weighted fold over gate precision, propose→keep, ramp delta,
          and reactivity confirm rate. Lower is better — the curve descends
          as the worm earns trust.
        </p>
      </header>

      {!hasPoints ? (
        <p
          data-testid="composite-score-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No ledger entries yet. The composite curve fills in once the
          install arc starts firing experiments and confirming reactivities.
        </p>
      ) : (
        <>
          <svg
            data-testid="composite-score-svg"
            width={CHART_W}
            height={CHART_H}
            role="img"
            aria-label="composite score loss curve"
            style={{
              maxWidth: "100%",
              border: "1px solid var(--wb-color-rule-line)",
              background: "var(--wb-color-paper)",
            }}
          >
            <line
              x1={PAD_X}
              y1={PAD_Y}
              x2={PAD_X}
              y2={CHART_H - PAD_Y}
              stroke="var(--wb-color-rule-line)"
              strokeWidth={1}
            />
            <line
              x1={PAD_X}
              y1={CHART_H - PAD_Y}
              x2={CHART_W - PAD_X}
              y2={CHART_H - PAD_Y}
              stroke="var(--wb-color-rule-line)"
              strokeWidth={1}
            />
            <path
              d={path}
              fill="none"
              stroke="var(--wb-color-botanical-green-deep, #4a6b3a)"
              strokeWidth={1.5}
            />
            {lossPoints.map(({ i, loss, point }) => (
              <Link
                key={`${point.ledgerHeight}-${i}`}
                href={{
                  pathname: "/trace",
                  query: {
                    seqLo: point.contributingSeqLo,
                    seqHi: point.contributingSeqHi,
                  },
                }}
                data-testid={`composite-score-point-${i}`}
                data-ledger-height={point.ledgerHeight}
                data-loss={loss.toFixed(4)}
              >
                <circle
                  cx={scaleX(i)}
                  cy={scaleY(loss)}
                  r={4}
                  fill="var(--wb-color-botanical-green-deep, #4a6b3a)"
                  style={{ cursor: "pointer" }}
                >
                  <title>
                    seq {point.contributingSeqLo}–{point.contributingSeqHi} ·
                    loss {loss.toFixed(3)} · top reactivity{" "}
                    {point.topContributorReactivityId || "—"}
                  </title>
                </circle>
              </Link>
            ))}
          </svg>
          <ul
            data-testid="composite-score-badges"
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 6,
            }}
          >
            {lossPoints.map(({ i, point, loss }) => (
              <li
                key={`${point.ledgerHeight}-${i}-badge`}
                data-testid={`composite-score-badge-${i}`}
                style={{
                  fontFamily: "var(--wb-font-mono)",
                  fontSize: 10,
                  letterSpacing: "0.04em",
                  padding: "2px 8px",
                  border: "1px solid var(--wb-color-rule-line)",
                  borderRadius: 0,
                  color: "var(--wb-color-aged-ink)",
                  background: "var(--wb-color-paper)",
                }}
              >
                <strong>#{point.ledgerHeight}</strong>
                {" · loss "}
                {loss.toFixed(2)}
                {" · "}
                {point.topContributorReactivityId
                  ? `top: ${point.topContributorReactivityId}`
                  : "top: —"}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
