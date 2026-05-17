/**
 * /lake/lineage read-side accessors — L3 Sub-wave D (2026-05-29).
 *
 * Reads the projection_lineage_edges table populated by the L3
 * Compounding axis (Sub-wave B's LineageInferenceService composing
 * NamingHeuristic + SampleOverlap + DbtManifest strategies). One row
 * per (company_id, edge_id) with state ∈ {proposed, confirmed, rejected}.
 *
 * Strategy: Postgres first when DATABASE_URL is set; honest empty
 * fallback otherwise. The page renders an empty state in both cases —
 * we never substitute fixtures.
 *
 * Also surfaces strategy productivity gauges so the operator-facing
 * banner can label what's actually wired today. Sub-wave C concern #1
 * (column lists empty in catalog mirror) and concern #2 (NoopSampler
 * stub) demand this: the dashboard MUST honestly distinguish
 * "configured but no-op" from "disabled" from "productive."
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** One row in the /lake/lineage page table. */
export interface LineageEdgeRow {
  /** Deterministic hash over (src_table_id, src_column, tgt_table_id, tgt_column). */
  edgeId: string;
  /** UUID of the upstream catalog table. */
  srcTableId: string;
  /** Upstream column name; ``null`` for whole-table edges (dbt-manifest). */
  srcColumn: string | null;
  /** UUID of the downstream catalog table. */
  tgtTableId: string;
  /** Downstream column name; ``null`` for whole-table edges. */
  tgtColumn: string | null;
  /** Confidence float in [0.0, 1.0] from the inference strategy. */
  confidence: number;
  /** Strategy that produced (or last-updated) the proposal. */
  strategy: string;
  /** Human-readable explanation rendered on the row detail panel. */
  reasoning: string;
  /** Structured evidence dict surfaced verbatim on the detail panel. */
  evidence: Record<string, unknown>;
  /** Current state — ``"proposed"`` | ``"confirmed"`` | ``"rejected"``. */
  state: "proposed" | "confirmed" | "rejected";
  /** ISO-8601 timestamp the state last changed. */
  stateChangedAt: string;
  /** Person UUID that last changed state; ``null`` while in proposed. */
  stateChangedBy: string | null;
}

/**
 * Per-page filter for /lake/lineage (2026-05-16).
 *
 * Producer-side deep-link filter — narrows the rendered tables to a
 * single L3 edge identified by its primary-key ``edgeId``. Honored by
 * every projection accessor below. Surfaces the ``?edge_id=<id>`` URL
 * param landed on producer pages alongside the consumer-page
 * ``upstream_*_id`` filter family from ``be0bbc7``.
 *
 * Symmetric pair: consumer pages filter by ``upstream_*_id``
 * (potentially many rows); producer pages filter by primary-key
 * ``edgeId`` (at most one row).
 */
export interface LineageFilter {
  edgeId?: string;
}

/** Per-strategy productivity signal surfaced by the status banner. */
export interface LineageStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` enum). */
  strategy: string;
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce edges today against this tenant's catalog. */
  productive: boolean;
  /**
   * Short doc-string surfaced in the banner. Distinguishes "productive"
   * from "configured but stubbed" from "disabled."
   */
  note: string;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface LineageEdgeQueryRow extends Record<string, unknown> {
  edge_id: string;
  src_table_id: string;
  src_column: string | null;
  tgt_table_id: string;
  tgt_column: string | null;
  confidence: number | string;
  strategy: string;
  reasoning: string;
  evidence: Record<string, unknown> | null;
  state: "proposed" | "confirmed" | "rejected";
  state_changed_at: string | Date;
  state_changed_by: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

function toFloat(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v;
  const parsed = Number.parseFloat(v);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toIso(v: string | Date): string {
  if (v instanceof Date) return v.toISOString();
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toISOString();
}

function isTruthy(raw: string | undefined): boolean {
  if (!raw) return false;
  const v = raw.trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

function mapRow(r: LineageEdgeQueryRow): LineageEdgeRow {
  return {
    edgeId: r.edge_id,
    srcTableId: r.src_table_id,
    srcColumn: r.src_column,
    tgtTableId: r.tgt_table_id,
    tgtColumn: r.tgt_column,
    confidence: toFloat(r.confidence),
    strategy: r.strategy,
    reasoning: r.reasoning,
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`LineageFilter`. Always parameterized — never interpolates
 * user-controlled values into SQL.
 *
 * Currently a single optional predicate (``edgeId`` → primary-key
 * column). Returns ``{ where: "", values: [] }`` when the filter is
 * undefined or empty.
 */
function _composeLineageFilter(
  filter: LineageFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.edgeId) {
    predicates.push(`AND edge_id = $${p}`);
    values.push(filter.edgeId);
    p += 1;
  }

  return {
    where:
      predicates.length === 0 ? "" : "\n      " + predicates.join("\n      "),
    values,
  };
}

// ─── Postgres-bound accessors ─────────────────────────────────────────────

/**
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) lineage
 * edge for a tenant, newest first. The page's "Pending Proposals"
 * section renders these with Confirm/Reject actions for admins.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state.
 */
export async function getProposedLineageEdges(
  companyId: string,
  opts: { limit?: number; filter?: LineageFilter } = {},
): Promise<LineageEdgeRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeLineageFilter(opts.filter, 2);

  const sql = `
    SELECT
      edge_id,
      src_table_id,
      src_column,
      tgt_table_id,
      tgt_column,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_lineage_edges
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, edge_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<LineageEdgeQueryRow>(sql, [
      companyId,
      ...values,
      limit,
    ]);
    return res.rows.map(mapRow);
  } catch {
    return [];
  }
}

/**
 * Fetch every confirmed lineage edge for a tenant. The page's
 * confirmed section renders these as a table or basic SVG graph.
 */
export async function getConfirmedLineageEdges(
  companyId: string,
  opts: { limit?: number; filter?: LineageFilter } = {},
): Promise<LineageEdgeRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeLineageFilter(opts.filter, 2);

  const sql = `
    SELECT
      edge_id,
      src_table_id,
      src_column,
      tgt_table_id,
      tgt_column,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_lineage_edges
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, edge_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<LineageEdgeQueryRow>(sql, [
      companyId,
      ...values,
      limit,
    ]);
    return res.rows.map(mapRow);
  } catch {
    return [];
  }
}

/**
 * Fetch rejected lineage edges in the last ``days`` (default 30) for
 * strategy-tuning audit. Surfaced collapsed by default.
 */
export async function getRejectedLineageEdges(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: LineageFilter } = {},
): Promise<LineageEdgeRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeLineageFilter(opts.filter, 3);

  const sql = `
    SELECT
      edge_id,
      src_table_id,
      src_column,
      tgt_table_id,
      tgt_column,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_lineage_edges
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, edge_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<LineageEdgeQueryRow>(sql, [
      companyId,
      days,
      ...values,
      limit,
    ]);
    return res.rows.map(mapRow);
  } catch {
    return [];
  }
}

/**
 * Return the latest projection row for a single (company_id, edge_id).
 * Used by the detail panel + the click-through audit view.
 */
export async function getLineageEdgeEvidence(
  companyId: string,
  edgeId: string,
): Promise<LineageEdgeRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      edge_id,
      src_table_id,
      src_column,
      tgt_table_id,
      tgt_column,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_lineage_edges
    WHERE company_id = $1
      AND edge_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<LineageEdgeQueryRow>(sql, [companyId, edgeId]);
    if (res.rows.length === 0) return null;
    return mapRow(res.rows[0]);
  } catch {
    return null;
  }
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the status
 * banner on ``/lake/lineage``. Reads the L3 env knobs + folds in the
 * Sub-wave C empirical truths:
 *
 *   * ``dbt_manifest`` — productive when ``WORMBASE_LINEAGE_DISCOVERY_ENABLED``
 *     is truthy. Reads Wave 1's catalog-manifest mirror; the only strategy
 *     that yields edges today.
 *
 *   * ``naming_heuristic`` — configured (when the same master switch is
 *     on) but gated on column-list mirroring. Wave 1's CatalogTable does
 *     not yet emit columns, so ``column_list`` is empty on every catalog
 *     row — the heuristic yields zero edges.
 *
 *   * ``sample_overlap`` — configured when
 *     ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED`` is truthy AND the master
 *     switch is on. NoopSampler is the production fallback; until a real
 *     sampler is wired the strategy's telemetry counter increments but
 *     no edges land. Productive=false in either case until columns +
 *     real sampler are both shipped.
 *
 * Tenant-isolation: this reader is process-env-scoped (env knobs are
 * global to the dashboard process), so ``companyId`` is currently
 * accepted but unused. Kept on the signature for symmetry + future
 * per-tenant overrides.
 */
export async function getLineageStrategyStatus(
  _companyId: string,
): Promise<LineageStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED,
  );
  const sampleOverlapEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED);

  return [
    {
      strategy: "dbt_manifest",
      configured: discoveryEnabled,
      productive: discoveryEnabled,
      note: discoveryEnabled
        ? "Productive — reads Wave 1 dbt-manifest catalog mirror; only L3 strategy yielding edges today."
        : "Disabled — set WORMBASE_LINEAGE_DISCOVERY_ENABLED=true to wire the L3 inference axis.",
    },
    {
      strategy: "naming_heuristic",
      configured: discoveryEnabled,
      productive: false,
      note: discoveryEnabled
        ? "Configured but gated — Wave 1 catalog mirror does not yet emit column lists, so the heuristic yields zero edges until column-list mirroring lands."
        : "Disabled — depends on WORMBASE_LINEAGE_DISCOVERY_ENABLED + column-list catalog mirroring.",
    },
    {
      strategy: "sample_overlap",
      configured: sampleOverlapEnabled,
      productive: false,
      note: sampleOverlapEnabled
        ? "Configured but no-op sampler — NoopSampler is the production fallback; telemetry counter increments but no edges land until a real sampler is wired."
        : "Disabled — requires WORMBASE_LINEAGE_DISCOVERY_ENABLED=true AND WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED=true.",
    },
  ];
}

// ─── L4↦L3 reverse-arc enrichment (Half B — reverse direction) ───────────

/**
 * Reverse-arc lookup key for a lineage edge → schema-impact count map.
 *
 * The L4→L3 forward chain populates ``upstream_lineage_edge_id`` on
 * each ``ProposedImpact`` proposed by the ``lineage_edge`` strategy.
 * This map keys directly off the L3 ``edgeId`` so the producer-page
 * row can look up its downstream-impact count without rebuilding the
 * tuple. Honest empty by construction — never null.
 */
export type SchemaImpactCountByEdgeMap = Record<string, number>;

/**
 * Count L4 schema-evolution-impact rows per L3 ``edge_id`` for a
 * tenant. Reads ``projection_schema_impacts`` (v023) — the SAME table
 * the /lake/schema-impact surface displays. State filter:
 * ``state IN ('proposed', 'confirmed')`` — rejected impacts are
 * excluded from the badge count (they are dispositions, not pending
 * consequences). Matches the L4↦L2 Half B precedent.
 *
 * ``upstream_lineage_edge_id`` is a NULL-able first-class column on
 * the projection (per v023 §"upstream_lineage_edge_id is NULLABLE —
 * type_coercion-strategy proposals derive from sample-stats rather
 * than a confirmed L3 edge and carry NULL"). The SQL filters those
 * out so the map only counts impacts that actually descend from an
 * L3 edge.
 *
 * No env knob: this is unconditional cross-axis enrichment per
 * Recipe Addendum #3. When the L4 projection is empty (e.g. master
 * env knob OFF or no impacts yet), the function returns an empty
 * map; the L3 row renders no badge. Honest by construction.
 *
 * Tenant-scoped via ``companyId``. Multi-tenant safe — the SQL
 * filters by company_id; no cross-tenant data leaks.
 *
 * Returns ``{}`` when DATABASE_URL is unset, the query throws, or
 * the projection is empty — the page renders no badges on any row.
 */
export async function getSchemaImpactCountByLineageEdge(
  companyId: string,
): Promise<SchemaImpactCountByEdgeMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      upstream_lineage_edge_id,
      COUNT(*)::int AS impact_count
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND upstream_lineage_edge_id IS NOT NULL
    GROUP BY upstream_lineage_edge_id
  `;

  try {
    const res = await pgQuery<{
      upstream_lineage_edge_id: string;
      impact_count: number | string;
    }>(sql, [companyId]);
    const out: SchemaImpactCountByEdgeMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.impact_count === "number"
          ? row.impact_count
          : Number.parseInt(String(row.impact_count), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_lineage_edge_id] = n;
    }
    return out;
  } catch {
    return {};
  }
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  isTruthy,
  mapRow,
  _composeLineageFilter,
};
