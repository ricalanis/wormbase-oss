/**
 * KPI compare-two-runs accessor — Phase 3 Task 3E.
 *
 * Read-only replay surface: given a KPI id and a wall-clock timestamp T,
 * fold the most-recent ``emit_kpi_node`` ledger row for that id where
 * ``ts <= T`` and emit a deterministic "snapshot at T" record carrying:
 *
 *   - the canonical scalar value the KPI carried at T (``args.value`` if
 *     written; ``null`` until a value lands)
 *   - the ledger-row sha256 at T (the canonical bytes proof — same id,
 *     same write, same hash)
 *   - the ts of the contributing row (so the side-by-side view can show
 *     "this is the kpi as of <T>" without lying about the resolution)
 *   - the entry count scanned for that tenant up to T (debug surface; the
 *     replay-determinism story rests on identical hash + value at fixed T)
 *
 * Mirrors ``packages/wormbase-tools/src/wormbase_tools/projections/kpis.py``
 * @ ``fold_kpis``: a KPI's value comes from the most-recent
 * ``emit_kpi_node`` (or its companion ``emit_source_golded``) write. We
 * keep the read narrow — pure SQL, no I/O outside Postgres — so the
 * /kpis/compare page is genuinely a read+replay surface, not a write.
 *
 * No new entry kinds, no new projections — the row is whatever the
 * ledger already carries.
 */

import { DEFAULT_COMPANY_ID, pgQuery } from "../ledger-client";

export interface KpiReplaySnapshot {
  /** True iff at least one ``emit_kpi_node`` row for this id exists with ts <= T. */
  found: boolean;
  /** The canonical scalar value carried by the row at T. ``null`` until a value lands. */
  value: number | string | null;
  /** sha256 hex of the contributing ledger row at T. ``""`` when ``found === false``. */
  hash: string;
  /** ISO-8601 ts of the contributing ledger row. ``null`` when ``found === false``. */
  rowTs: string | null;
  /** ledger seq of the contributing row (debug surface). 0 when not found. */
  rowSeq: number;
  /** Total ``emit_kpi_node`` rows for the tenant scanned up to T (debug surface). */
  scanCount: number;
}

type KpiNodeReplayRow = {
  ts: Date | string;
  seq: string | number;
  hash_hex: string;
  value: unknown;
} & Record<string, unknown>;

type ScanCountRow = {
  scan_count: string | number;
} & Record<string, unknown>;

/**
 * Coerce a ledger ``args.value`` payload into a canonical scalar.
 *
 * Mirrors ``_normalize_value`` in
 * ``packages/wormbase-tools/src/wormbase_tools/projections/kpis.py``: scalars
 * pass through; ``{value: x}`` resolves to ``x``; single-key dicts resolve
 * to their inner value; everything else is JSON-stringified deterministically
 * (sorted keys, no whitespace) so two snapshots of the same payload produce
 * byte-identical strings.
 */
export function normalizeKpiValue(raw: unknown): number | string | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === "number" || typeof raw === "string") return raw;
  if (typeof raw === "boolean") return raw ? "true" : "false";
  if (Array.isArray(raw)) return JSON.stringify(raw);
  if (typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const inner = obj.value;
    if (typeof inner === "number" || typeof inner === "string") return inner;
    const keys = Object.keys(obj);
    if (keys.length === 1) {
      const only = obj[keys[0]];
      if (typeof only === "number" || typeof only === "string") return only;
    }
    // Deterministic fallback: canonical JSON with sorted keys.
    const sorted: Record<string, unknown> = {};
    for (const k of keys.sort()) sorted[k] = obj[k];
    return JSON.stringify(sorted);
  }
  return String(raw);
}

/**
 * Replay a single KPI to wall-clock timestamp ``untilTs``.
 *
 * SQL-only — picks the most-recent ``emit_kpi_node`` execute row for
 * ``kpiId`` whose ``ts <= untilTs``. Empty / unknown / out-of-range
 * timestamps return ``found: false`` so the caller can render an honest
 * empty state side-by-side without throwing.
 */
export async function replayKpiAtTimestamp(
  companyId: string,
  kpiId: string,
  untilTs: string,
): Promise<KpiReplaySnapshot> {
  const empty: KpiReplaySnapshot = {
    found: false,
    value: null,
    hash: "",
    rowTs: null,
    rowSeq: 0,
    scanCount: 0,
  };

  if (!companyId || !kpiId || !untilTs) return empty;

  const rowSql = `
    SELECT ts,
           seq,
           encode(hash, 'hex') AS hash_hex,
           payload->'args'->'value' AS value
      FROM ledger
     WHERE company_id = $1
       AND kind = 'execute'
       AND payload->>'tool' = 'emit_kpi_node'
       AND payload->'args'->>'id' = $2
       AND ts <= $3::timestamptz
     ORDER BY seq DESC
     LIMIT 1
  `;
  const countSql = `
    SELECT COUNT(*)::text AS scan_count
      FROM ledger
     WHERE company_id = $1
       AND kind = 'execute'
       AND payload->>'tool' = 'emit_kpi_node'
       AND payload->'args'->>'id' = $2
       AND ts <= $3::timestamptz
  `;

  try {
    const [rowRes, countRes] = await Promise.all([
      pgQuery<KpiNodeReplayRow>(rowSql, [companyId, kpiId, untilTs]),
      pgQuery<ScanCountRow>(countSql, [companyId, kpiId, untilTs]),
    ]);

    const scanCount = countRes.rows.length
      ? Number(countRes.rows[0].scan_count) || 0
      : 0;

    if (rowRes.rows.length === 0) {
      return { ...empty, scanCount };
    }
    const row = rowRes.rows[0];
    const tsIso =
      row.ts instanceof Date
        ? row.ts.toISOString()
        : new Date(String(row.ts)).toISOString();
    return {
      found: true,
      value: normalizeKpiValue(row.value),
      hash: row.hash_hex ?? "",
      rowTs: tsIso,
      rowSeq: Number(row.seq) || 0,
      scanCount,
    };
  } catch {
    // tryPg-style fallback — surface as "not found" rather than throwing
    // out of an RSC. The compare view's empty-state messaging covers this.
    return empty;
  }
}

/**
 * Replay both timestamps in parallel — convenience for the compare page.
 *
 * Returns ``[A, B]`` where each entry is a self-describing snapshot. The
 * page is the only consumer; this wrapper is exported so the unit tests
 * can drive both replays through one call site.
 */
export async function replayKpiCompare(
  kpiId: string,
  t1: string | null,
  t2: string | null,
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<{ a: KpiReplaySnapshot; b: KpiReplaySnapshot }> {
  const [a, b] = await Promise.all([
    t1 ? replayKpiAtTimestamp(companyId, kpiId, t1) : emptySnapshot(),
    t2 ? replayKpiAtTimestamp(companyId, kpiId, t2) : emptySnapshot(),
  ]);
  return { a, b };
}

function emptySnapshot(): KpiReplaySnapshot {
  return {
    found: false,
    value: null,
    hash: "",
    rowTs: null,
    rowSeq: 0,
    scanCount: 0,
  };
}
