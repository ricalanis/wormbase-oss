/**
 * KpiCompareView — side-by-side hash + value diff for two replay timestamps.
 *
 * Phase 3 Task 3E (validation gap P2.7). Pure read+replay surface: each
 * column is the most-recent ``emit_kpi_node`` ledger row for the KPI
 * whose ``ts <= T``. Same id, same writer, same ledger → identical hash
 * across two replays at the same T. The view makes that determinism
 * visible.
 *
 * Three on-screen states:
 *
 *   - Empty (no T1 nor T2 picked): the form sits alone with an honest hint.
 *   - Single replay (only T1 OR T2): show that column, dim the other.
 *   - Both replays: show both columns with a "matches" / "differs" badge
 *     that compares (hash + value).
 */

import type { KpiReplaySnapshot } from "../../lib/server/kpi-compare";

interface Props {
  kpiId: string;
  t1: string | null;
  t2: string | null;
  snapshotA: KpiReplaySnapshot;
  snapshotB: KpiReplaySnapshot;
}

const CARD_STYLE: React.CSSProperties = {
  border: "1px solid var(--wb-color-paper-edge)",
  padding: 16,
  background: "var(--wb-color-paper-deep)",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const LABEL_STYLE: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const HASH_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  wordBreak: "break-all",
  color: "var(--wb-color-aged-ink)",
};

const VALUE_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 18,
  color: "var(--wb-color-aged-ink)",
};

function ColumnCard({
  side,
  ts,
  snap,
}: {
  side: "A" | "B";
  ts: string | null;
  snap: KpiReplaySnapshot;
}) {
  const dim = !ts;
  return (
    <article
      data-testid={`kpi-compare-col-${side}`}
      data-found={snap.found ? "true" : "false"}
      style={{ ...CARD_STYLE, opacity: dim ? 0.45 : 1 }}
    >
      <span className="wb-mono" style={LABEL_STYLE}>
        Replay {side} · until_ts
      </span>
      <span
        data-testid={`kpi-compare-col-${side}-ts-input`}
        className="wb-mono"
        style={{ fontSize: 12, color: "var(--wb-color-hash-gray)" }}
      >
        {ts ?? "(no timestamp picked)"}
      </span>

      {!ts ? (
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pick a timestamp on the left to populate this side.
        </p>
      ) : !snap.found ? (
        <p
          data-testid={`kpi-compare-col-${side}-empty`}
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No emit_kpi_node row for this id at or before this timestamp. The
          worm hadn&rsquo;t proposed it yet.
        </p>
      ) : (
        <>
          <span style={LABEL_STYLE}>value</span>
          <span data-testid={`kpi-compare-col-${side}-value`} style={VALUE_STYLE}>
            {snap.value === null ? "—" : String(snap.value)}
          </span>
          <span style={LABEL_STYLE}>row hash</span>
          <span data-testid={`kpi-compare-col-${side}-hash`} style={HASH_STYLE}>
            {snap.hash}
          </span>
          <span style={LABEL_STYLE}>row ts · seq</span>
          <span
            className="wb-mono"
            style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
          >
            {snap.rowTs} · seq {snap.rowSeq}
          </span>
          <span style={LABEL_STYLE}>scanned rows</span>
          <span
            className="wb-mono"
            style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
          >
            {snap.scanCount}
          </span>
        </>
      )}
    </article>
  );
}

function MatchBadge({
  snapA,
  snapB,
}: {
  snapA: KpiReplaySnapshot;
  snapB: KpiReplaySnapshot;
}) {
  if (!snapA.found || !snapB.found) return null;
  const sameHash = snapA.hash === snapB.hash;
  const sameValue =
    snapA.value === null && snapB.value === null
      ? true
      : snapA.value === snapB.value;
  const matches = sameHash && sameValue;

  return (
    <div
      data-testid="kpi-compare-match-badge"
      data-matches={matches ? "true" : "false"}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "8px 12px",
        border: `1px solid ${
          matches
            ? "var(--wb-color-botanical-green-deep)"
            : "var(--wb-color-sepia-warning-deep)"
        }`,
        background: "var(--wb-color-paper-deep)",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: matches
            ? "var(--wb-color-botanical-green-deep)"
            : "var(--wb-color-sepia-warning-deep)",
        }}
      >
        {matches
          ? "hashes match · replay is deterministic"
          : "hashes differ · ledger advanced between T1 and T2"}
      </span>
      <span style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}>
        hash {sameHash ? "==" : "!="} · value {sameValue ? "==" : "!="}
      </span>
    </div>
  );
}

export function KpiCompareView({ kpiId, t1, t2, snapshotA, snapshotB }: Props) {
  const onlyOne = (t1 && !t2) || (!t1 && t2);
  const neither = !t1 && !t2;

  return (
    <section
      data-testid="kpi-compare-view"
      data-state={
        neither ? "empty" : onlyOne ? "single" : "compare"
      }
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span className="wb-mono" style={LABEL_STYLE}>
          KPI · {kpiId}
        </span>
      </header>

      <MatchBadge snapA={snapshotA} snapB={snapshotB} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <ColumnCard side="A" ts={t1} snap={snapshotA} />
        <ColumnCard side="B" ts={t2} snap={snapshotB} />
      </div>

      {neither ? (
        <p
          data-testid="kpi-compare-empty-hint"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pick two replay timestamps to compare hash + value side-by-side.
          The same kpi at the same T must produce the same hash — that is
          the determinism contract.
        </p>
      ) : null}
    </section>
  );
}
