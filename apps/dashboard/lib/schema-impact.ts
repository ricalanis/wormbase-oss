/**
 * /lake/schema-impact read-side accessors — L4 Sub-wave D (2026-06-02).
 *
 * Reads the ``projection_schema_impacts`` table (v023) populated by the
 * L4 Compounding axis (Sub-wave B's CompositeSchemaImpactService composing
 * LineageEdgeImpactStrategy + DbtTestImpactStrategy +
 * TypeCoercionImpactStrategy). One row per (company_id, impact_id) with
 * state ∈ {proposed, confirmed, rejected}.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise. The page renders an empty state in both cases —
 * we never substitute fixtures.
 *
 * NEW (and distinctive) for L4: the strategy status banner reads BOTH
 * the L4 env knobs AND the count of L3 ``confirmed`` lineage edges for
 * the tenant. ``lineage_edge`` strategy is honest about its L3
 * dependency:
 *
 *   * L3 disabled                      → ``disabled``
 *   * L3 enabled + 0 confirmed edges   → ``configured · awaiting-L3-edges``
 *   * L3 enabled + ≥1 confirmed edges  → ``productive · L3-dependent``
 *
 * This implements Sub-wave C handoff concern #9 (L3-dependency
 * surfacing) on the read side.
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** One row in the /lake/schema-impact page table. */
export interface SchemaImpactRow {
  /** Deterministic hash over (source_id, src_table, src_column, change_kind, tgt_table_id, tgt_column). */
  impactId: string;
  /** Connector source UUID (the upstream source whose column changed). */
  sourceId: string;
  /** Upstream table name. */
  srcTable: string;
  /** Upstream column name (the one that changed). */
  srcColumn: string;
  /** Change kind — ``column_added`` | ``column_dropped`` | ``column_type_changed``. */
  changeKind: "column_added" | "column_dropped" | "column_type_changed";
  /** Impact kind — one of 5 values; see spec §3.4. */
  impactKind:
    | "tgt_column_orphaned"
    | "tgt_column_type_mismatch"
    | "tgt_column_unaware"
    | "dbt_test_breakage"
    | "type_coercion_required";
  /** UUID of the affected downstream catalog table. */
  tgtTableId: string;
  /** Affected downstream column name. */
  tgtColumn: string;
  /**
   * L3 lineage edge that drove this impact, when applicable.
   * ``null`` for non-edge-driven strategies (e.g. ``type_coercion``
   * deriving from bare type metadata).
   */
  upstreamLineageEdgeId: string | null;
  /** Confidence float in [0.0, 1.0] from the inference strategy. */
  confidence: number;
  /** Strategy that produced (or last-updated) the proposal. */
  strategy:
    | "lineage_edge"
    | "dbt_test"
    | "type_coercion"
    | "governance_classification"
    | "semantic_type"
    | "composite";
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

/** Per-strategy productivity signal surfaced by the status banner. */
export interface SchemaImpactStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` enum). */
  strategy:
    | "lineage_edge"
    | "dbt_test"
    | "type_coercion"
    | "governance_classification"
    | "semantic_type";
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce impacts today against this tenant. */
  productive: boolean;
  /**
   * Short doc-string surfaced in the banner. Distinguishes the four
   * postures: productive · L3-dependent / configured · awaiting-L3-edges /
   * configured · empty-upstream / disabled.
   */
  note: string;
  /**
   * Honest status banner badge keyword. Mirrors :class:`CapabilityStatus`
   * values so the page can drop straight into the shared
   * ``CapabilityBadges`` component.
   */
  badge: "production" | "configured-stubbed" | "disabled";
  /**
   * Optional override label for the badge. L4's `lineage_edge`
   * strategy uses this to surface the ``productive · L3-dependent`` or
   * ``configured · awaiting-L3-edges`` posture; ``dbt_test`` uses it
   * for ``configured · empty-upstream``.
   */
  badgeLabelOverride?: string;
}

/**
 * Per-page filter for /lake/schema-impact (2026-05-16). Surfaces the
 * URL params produced by the reverse-arc badges (R1 + R5 + R6) and
 * the L4↦L2 Half B catalog-drift badge. Any subset of fields may be
 * set; absent fields widen the query (no predicate added). Fields
 * compose with AND when multiple are present.
 *
 * Filter sources:
 *
 *   * ``upstreamLineageEdgeId``      — R1 from L3 lineage page
 *   * ``upstreamClassificationId``   — R5 from L6 column-classification page
 *   * ``upstreamSemanticTypeId``     — R6 from L5 semantic-types page
 *   * ``sourceId`` + ``srcTable``    — L4↦L2 Half B from L2 catalog-drift page
 *     [+ optional ``srcColumn``]       (composite: all 3 narrow to a
 *                                        single column-level drift)
 */
export interface SchemaImpactFilter {
  upstreamLineageEdgeId?: string;
  upstreamClassificationId?: string;
  upstreamSemanticTypeId?: string;
  sourceId?: string;
  srcTable?: string;
  srcColumn?: string;
  /**
   * Producer-side primary-key deep-link (2026-05-16 — Lake-Side Overview
   * activity-stream drill-in coverage). When set, narrows the rendered
   * tables to the single impact identified by ``impactId``. Honest
   * empty when no row matches. Mirrors the producer-deep-links bundle
   * (``bdee480``) pattern for L3 ``edgeId`` / L5 ``typeId`` /
   * L6 ``classificationId`` / L2 ``driftId``.
   */
  impactId?: string;
}

/**
 * L3-dependency probe summary surfaced by the dependency banner.
 * Concern #9: when L3 is enabled but has zero confirmed edges, the L4
 * page renders an explicit "no L3 edges available — L4 awaits L3
 * confirmations" panel.
 */
export interface L3DependencyState {
  /** True iff ``WORMBASE_LINEAGE_DISCOVERY_ENABLED`` is truthy. */
  l3Enabled: boolean;
  /** Number of ``confirmed`` ``projection_lineage_edges`` rows for this tenant. */
  confirmedEdgeCount: number;
}

/**
 * L6-dependency probe summary surfaced by the dependency banner.
 * Mirrors :class:`L3DependencyState` for the L6→L4 cross-axis chain
 * (5th cross-axis chain shipped 2026-06-10). When L6 is enabled but
 * has zero confirmed classifications, the page renders an explicit
 * "no L6 classifications available — governance elevation awaits L6
 * confirmations" panel.
 */
export interface L6DependencyState {
  /** True iff ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED`` is truthy. */
  l6Enabled: boolean;
  /** Number of ``confirmed`` ``projection_column_classifications`` rows for this tenant. */
  confirmedClassificationCount: number;
}

/**
 * L5-dependency probe summary surfaced by the dependency banner.
 * Mirrors :class:`L3DependencyState` + :class:`L6DependencyState` for
 * the L5→L4 cross-axis chain (6th cross-axis chain, last of the 3
 * originally-foreshadowed peer-axis chains). When L5 is enabled but
 * has zero confirmed semantic types, the page renders an explicit
 * "no L5 semantic types available — semantic-type elevation awaits L5
 * confirmations" panel.
 */
export interface L5DependencyState {
  /** True iff ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` is truthy. */
  l5Enabled: boolean;
  /** Number of ``confirmed`` ``projection_semantic_types`` rows for this tenant. */
  confirmedSemanticTypeCount: number;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface SchemaImpactQueryRow extends Record<string, unknown> {
  impact_id: string;
  source_id: string;
  src_table: string;
  src_column: string;
  change_kind: string;
  impact_kind: string;
  tgt_table_id: string;
  tgt_column: string;
  upstream_lineage_edge_id: string | null;
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

function mapRow(r: SchemaImpactQueryRow): SchemaImpactRow {
  return {
    impactId: r.impact_id,
    sourceId: r.source_id,
    srcTable: r.src_table,
    srcColumn: r.src_column,
    changeKind: r.change_kind as SchemaImpactRow["changeKind"],
    impactKind: r.impact_kind as SchemaImpactRow["impactKind"],
    tgtTableId: r.tgt_table_id,
    tgtColumn: r.tgt_column,
    upstreamLineageEdgeId: r.upstream_lineage_edge_id,
    confidence: toFloat(r.confidence),
    strategy: r.strategy as SchemaImpactRow["strategy"],
    reasoning: r.reasoning,
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`SchemaImpactFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * ``nextParam`` is the 1-based index for the next placeholder
 * (callers already use ``$1`` for ``companyId``; pass ``2`` so the
 * filter starts at ``$2``). Returns the fragment to append directly
 * after an existing WHERE-clause (each predicate starts with
 * ``AND ``), and the in-order parameter values.
 *
 * Filter-to-SQL mapping:
 *   * ``upstreamLineageEdgeId``    → ``upstream_lineage_edge_id = $N`` (first-class column)
 *   * ``upstreamClassificationId`` → ``evidence->>'upstream_classification_id' = $N`` (JSON evidence)
 *   * ``upstreamSemanticTypeId``   → ``evidence->>'upstream_semantic_type_id' = $N`` (JSON evidence)
 *   * ``sourceId``                  → ``source_id = $N``
 *   * ``srcTable``                  → ``src_table = $N``
 *   * ``srcColumn``                 → ``src_column = $N``
 *
 * Note on JSON evidence keys: when a composite impact merges multiple
 * strategies on the same canonical tuple, the evidence dict stores
 * both top-level keys (single-strategy rows) AND strategy-keyed
 * sub-dicts (merged rows). The accessors check both paths with an
 * OR — see the predicate composition in
 * ``_composeSchemaImpactFilter`` for the JSON path matrix.
 *
 * Returns ``{ where: "", values: [] }`` when the filter is undefined
 * or empty — caller appends nothing to the existing SQL.
 */
function _composeSchemaImpactFilter(
  filter: SchemaImpactFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.upstreamLineageEdgeId) {
    predicates.push(`AND upstream_lineage_edge_id = $${p}`);
    values.push(filter.upstreamLineageEdgeId);
    p += 1;
  }
  if (filter.upstreamClassificationId) {
    // Composite-merged rows store the classification id under the
    // ``governance_classification`` strategy key; single-strategy rows
    // store it at the top level. Match either.
    predicates.push(
      `AND (evidence->>'upstream_classification_id' = $${p} OR evidence->'governance_classification'->>'upstream_classification_id' = $${p})`,
    );
    values.push(filter.upstreamClassificationId);
    p += 1;
  }
  if (filter.upstreamSemanticTypeId) {
    // Mirror of the classification path — top-level OR
    // ``semantic_type`` strategy sub-dict.
    predicates.push(
      `AND (evidence->>'upstream_semantic_type_id' = $${p} OR evidence->'semantic_type'->>'upstream_semantic_type_id' = $${p})`,
    );
    values.push(filter.upstreamSemanticTypeId);
    p += 1;
  }
  if (filter.sourceId) {
    predicates.push(`AND source_id = $${p}`);
    values.push(filter.sourceId);
    p += 1;
  }
  if (filter.srcTable) {
    predicates.push(`AND src_table = $${p}`);
    values.push(filter.srcTable);
    p += 1;
  }
  if (filter.srcColumn) {
    predicates.push(`AND src_column = $${p}`);
    values.push(filter.srcColumn);
    p += 1;
  }
  if (filter.impactId) {
    predicates.push(`AND impact_id = $${p}`);
    values.push(filter.impactId);
    p += 1;
  }

  return {
    where: predicates.length === 0 ? "" : "\n      " + predicates.join("\n      "),
    values,
  };
}

// ─── Postgres-bound accessors ─────────────────────────────────────────────

/**
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) schema
 * impact for a tenant, newest first. The page's "Pending Proposals"
 * section renders these with Confirm/Reject actions for admins.
 *
 * Optional ``filter`` narrows the result set to rows derived from a
 * specific upstream entity (lineage edge / classification / semantic
 * type / source-table-column tuple). Honest empty: when filter
 * predicates match zero rows, returns ``[]`` — same empty UI as the
 * unfiltered path.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state.
 */
export async function getProposedSchemaImpacts(
  companyId: string,
  opts: { limit?: number; filter?: SchemaImpactFilter } = {},
): Promise<SchemaImpactRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeSchemaImpactFilter(opts.filter, 2);

  const sql = `
    SELECT
      impact_id,
      source_id,
      src_table,
      src_column,
      change_kind,
      impact_kind,
      tgt_table_id,
      tgt_column,
      upstream_lineage_edge_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, impact_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SchemaImpactQueryRow>(sql, [
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
 * Fetch every confirmed schema impact for a tenant. The page's
 * confirmed section renders these as a table; clicking expands the
 * evidence + reasoning panel.
 *
 * Optional ``filter`` mirrors :func:`getProposedSchemaImpacts` —
 * narrows the result set to rows derived from a specific upstream
 * entity. Honest empty when no rows match.
 */
export async function getConfirmedSchemaImpacts(
  companyId: string,
  opts: { limit?: number; filter?: SchemaImpactFilter } = {},
): Promise<SchemaImpactRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeSchemaImpactFilter(opts.filter, 2);

  const sql = `
    SELECT
      impact_id,
      source_id,
      src_table,
      src_column,
      change_kind,
      impact_kind,
      tgt_table_id,
      tgt_column,
      upstream_lineage_edge_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, impact_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SchemaImpactQueryRow>(sql, [
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
 * Fetch rejected schema impacts in the last ``days`` (default 30) for
 * strategy-tuning audit. Surfaced collapsed by default.
 */
export async function getRejectedSchemaImpacts(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: SchemaImpactFilter } = {},
): Promise<SchemaImpactRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // companyId is $1, days is $2 — filter starts at $3.
  const { where, values } = _composeSchemaImpactFilter(opts.filter, 3);

  const sql = `
    SELECT
      impact_id,
      source_id,
      src_table,
      src_column,
      change_kind,
      impact_kind,
      tgt_table_id,
      tgt_column,
      upstream_lineage_edge_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, impact_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<SchemaImpactQueryRow>(sql, [
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
 * Return the latest projection row for a single (company_id, impact_id).
 * Used by the detail panel + the click-through audit view.
 */
export async function getSchemaImpactEvidence(
  companyId: string,
  impactId: string,
): Promise<SchemaImpactRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      impact_id,
      source_id,
      src_table,
      src_column,
      change_kind,
      impact_kind,
      tgt_table_id,
      tgt_column,
      upstream_lineage_edge_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND impact_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<SchemaImpactQueryRow>(sql, [companyId, impactId]);
    if (res.rows.length === 0) return null;
    return mapRow(res.rows[0]);
  } catch {
    return null;
  }
}

/**
 * Probe the L3-dependency state for this tenant. Reads the env knob
 * for L3 + counts confirmed ``projection_lineage_edges`` rows.
 *
 * Returns ``confirmedEdgeCount = 0`` when the table is missing or the
 * query throws — the page renders an honest "no L3 edges available"
 * banner per Sub-wave C handoff concern #9.
 */
export async function getL3DependencyState(
  companyId: string,
): Promise<L3DependencyState> {
  const l3Enabled = isTruthy(process.env.WORMBASE_LINEAGE_DISCOVERY_ENABLED);
  if (!postgresEnabled()) {
    return { l3Enabled, confirmedEdgeCount: 0 };
  }

  const sql = `
    SELECT COUNT(*)::int AS n
    FROM projection_lineage_edges
    WHERE company_id = $1
      AND state = 'confirmed'
  `;

  try {
    const res = await pgQuery<{ n: number | string }>(sql, [companyId]);
    if (res.rows.length === 0) return { l3Enabled, confirmedEdgeCount: 0 };
    const raw = res.rows[0].n;
    const parsed = typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return {
      l3Enabled,
      confirmedEdgeCount: Number.isFinite(parsed) ? parsed : 0,
    };
  } catch {
    return { l3Enabled, confirmedEdgeCount: 0 };
  }
}

/**
 * Probe the L6-dependency state for this tenant. Reads the L6 env
 * knob + counts confirmed ``projection_column_classifications`` rows.
 *
 * Returns ``confirmedClassificationCount = 0`` when the table is
 * missing or the query throws — the page renders an honest
 * "no L6 classifications available" banner when the governance
 * sub-knob is on but L6 hasn't yet shipped confirmed rows.
 *
 * Surface mirrors :func:`getL3DependencyState` for the L4 axis's two
 * cross-axis dependencies (L3 and L6).
 */
export async function getL6DependencyState(
  companyId: string,
): Promise<L6DependencyState> {
  const l6Enabled = isTruthy(
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED,
  );
  if (!postgresEnabled()) {
    return { l6Enabled, confirmedClassificationCount: 0 };
  }

  const sql = `
    SELECT COUNT(*)::int AS n
    FROM projection_column_classifications
    WHERE company_id = $1
      AND state = 'confirmed'
  `;

  try {
    const res = await pgQuery<{ n: number | string }>(sql, [companyId]);
    if (res.rows.length === 0) {
      return { l6Enabled, confirmedClassificationCount: 0 };
    }
    const raw = res.rows[0].n;
    const parsed =
      typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return {
      l6Enabled,
      confirmedClassificationCount: Number.isFinite(parsed) ? parsed : 0,
    };
  } catch {
    return { l6Enabled, confirmedClassificationCount: 0 };
  }
}

/**
 * Probe the L5-dependency state for this tenant. Reads the L5 env
 * knob (``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED``) + counts
 * confirmed ``projection_semantic_types`` rows.
 *
 * Returns ``confirmedSemanticTypeCount = 0`` when the table is
 * missing or the query throws — the page renders an honest
 * "no L5 semantic types available" banner when the semantic_type
 * sub-knob is on but L5 hasn't yet shipped confirmed rows.
 *
 * Surface mirrors :func:`getL6DependencyState` for L4's third
 * cross-axis dependency (L3 + L6 + L5) — same row-counting shape,
 * same env-gated honesty.
 */
export async function getL5DependencyState(
  companyId: string,
): Promise<L5DependencyState> {
  const l5Enabled = isTruthy(
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED,
  );
  if (!postgresEnabled()) {
    return { l5Enabled, confirmedSemanticTypeCount: 0 };
  }

  const sql = `
    SELECT COUNT(*)::int AS n
    FROM projection_semantic_types
    WHERE company_id = $1
      AND state = 'confirmed'
  `;

  try {
    const res = await pgQuery<{ n: number | string }>(sql, [companyId]);
    if (res.rows.length === 0) {
      return { l5Enabled, confirmedSemanticTypeCount: 0 };
    }
    const raw = res.rows[0].n;
    const parsed =
      typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return {
      l5Enabled,
      confirmedSemanticTypeCount: Number.isFinite(parsed) ? parsed : 0,
    };
  } catch {
    return { l5Enabled, confirmedSemanticTypeCount: 0 };
  }
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the status
 * banner on ``/lake/schema-impact``. Reads the L4 env knobs + folds in
 * Sub-wave C handoff concerns:
 *
 *   * ``lineage_edge`` — productive when L3 is enabled AND L3 has
 *     ≥1 confirmed edge for this tenant; ``configured · awaiting-L3-edges``
 *     when L3 enabled but no confirmed edges yet (concern #9);
 *     ``disabled`` when the L4 master switch is off.
 *
 *   * ``dbt_test`` — ``configured · empty-upstream`` when L4 + dbt-test
 *     env knobs are on; ``disabled`` otherwise. Wave 1's catalog-manifest
 *     mirror does not yet emit dbt tests, so the strategy is wired
 *     correctly but its upstream is empty. Same honest posture as L7's
 *     ``dbt_tests`` strategy.
 *
 *   * ``type_coercion`` — productive when L4 is enabled. Operates on
 *     bare column type metadata that Wave 1 already mirrors; produces
 *     impacts immediately. No L3 dependency.
 *
 * Tenant-isolation: this reader composes env-knob state (process-global)
 * with a per-tenant L3 confirmed-edge count. The L4 surface itself is
 * env-gated, but the L3 dependency probe is per-tenant.
 */
export async function getSchemaImpactStrategyStatus(
  companyId: string,
): Promise<SchemaImpactStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED,
  );
  const dbtTestEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED);
  const governanceEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED);
  const semanticTypeEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED);

  const l3State = await getL3DependencyState(companyId);
  const l6State = await getL6DependencyState(companyId);
  const l5State = await getL5DependencyState(companyId);
  const lineageEdgeProductive =
    discoveryEnabled && l3State.l3Enabled && l3State.confirmedEdgeCount > 0;
  const lineageEdgeAwaiting =
    discoveryEnabled && l3State.l3Enabled && l3State.confirmedEdgeCount === 0;

  const governanceProductive =
    governanceEnabled && l6State.confirmedClassificationCount > 0;
  const governanceAwaiting =
    governanceEnabled && l6State.confirmedClassificationCount === 0;

  const semanticTypeProductive =
    semanticTypeEnabled && l5State.confirmedSemanticTypeCount > 0;
  const semanticTypeAwaiting =
    semanticTypeEnabled && l5State.confirmedSemanticTypeCount === 0;

  let governanceBadge: SchemaImpactStrategyStatus["badge"];
  let governanceOverride: string | undefined;
  let governanceNote: string;
  if (!governanceEnabled) {
    governanceBadge = "disabled";
    governanceNote =
      "Disabled — set WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED=true to wire the L6→L4 cross-axis chain. The strategy elevates impact severity when a changed column has an L6 confirmed classification at regulated / pii / confidential.";
  } else if (governanceProductive) {
    governanceBadge = "production";
    governanceOverride = "productive · L6-dependent";
    governanceNote = `Productive — reading ${l6State.confirmedClassificationCount} confirmed L6 column classification${l6State.confirmedClassificationCount === 1 ? "" : "s"} for this tenant. When a regulated / pii / confidential column changes, the strategy elevates the impact with governance_severity ∈ {critical, high}.`;
  } else if (governanceAwaiting) {
    governanceBadge = "configured-stubbed";
    governanceOverride = "configured · awaiting-L6-classifications";
    governanceNote =
      "Configured but awaiting L6 confirmations — the strategy is wired against L6's projection but no confirmed column classifications exist for this tenant yet. Confirm a classification in /lake/column-classification and the strategy graduates to productive automatically.";
  } else {
    governanceBadge = "configured-stubbed";
    governanceOverride = "configured · awaiting-L6-classifications";
    governanceNote =
      "Configured but awaiting L6 confirmations — confirm a classification in /lake/column-classification to start elevating impacts.";
  }

  let semanticTypeBadge: SchemaImpactStrategyStatus["badge"];
  let semanticTypeOverride: string | undefined;
  let semanticTypeNote: string;
  if (!semanticTypeEnabled) {
    semanticTypeBadge = "disabled";
    semanticTypeNote =
      "Disabled — set WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED=true to wire the L5→L4 cross-axis chain (6th chain, last of the 3 originally-foreshadowed peer-axis chains). The strategy elevates impact severity to high when a changed column has an L5 confirmed semantic type (email / uuid / phone / pii_* / custom).";
  } else if (semanticTypeProductive) {
    semanticTypeBadge = "production";
    semanticTypeOverride = "productive · L5-dependent";
    semanticTypeNote = `Productive — reading ${l5State.confirmedSemanticTypeCount} confirmed L5 semantic type${l5State.confirmedSemanticTypeCount === 1 ? "" : "s"} for this tenant. When a column with a confirmed semantic type changes, the strategy elevates the impact with semantic_type_severity=high so reviewers know to check the change against the semantic constraint (e.g. an email VARCHAR→INTEGER violates the email type).`;
  } else if (semanticTypeAwaiting) {
    semanticTypeBadge = "configured-stubbed";
    semanticTypeOverride = "configured · awaiting-L5-semantic-types";
    semanticTypeNote =
      "Configured but awaiting L5 confirmations — the strategy is wired against L5's projection but no confirmed semantic types exist for this tenant yet. Confirm a semantic type in /lake/semantic-types and the strategy graduates to productive automatically.";
  } else {
    semanticTypeBadge = "configured-stubbed";
    semanticTypeOverride = "configured · awaiting-L5-semantic-types";
    semanticTypeNote =
      "Configured but awaiting L5 confirmations — confirm a semantic type in /lake/semantic-types to start elevating impacts.";
  }

  let lineageEdgeBadge: SchemaImpactStrategyStatus["badge"];
  let lineageEdgeOverride: string | undefined;
  let lineageEdgeNote: string;
  if (!discoveryEnabled) {
    lineageEdgeBadge = "disabled";
    lineageEdgeNote =
      "Disabled — set WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true to wire the L4 inference axis.";
  } else if (lineageEdgeProductive) {
    lineageEdgeBadge = "production";
    lineageEdgeOverride = "productive · L3-dependent";
    lineageEdgeNote = `Productive — reading ${l3State.confirmedEdgeCount} confirmed L3 lineage edge${l3State.confirmedEdgeCount === 1 ? "" : "s"} for this tenant. When an upstream column changes, the strategy maps it to downstream tables/columns via L3's projection.`;
  } else if (lineageEdgeAwaiting) {
    lineageEdgeBadge = "configured-stubbed";
    lineageEdgeOverride = "configured · awaiting-L3-edges";
    lineageEdgeNote =
      "Configured but awaiting L3 confirmations — the strategy is wired against L3's projection but no confirmed lineage edges exist for this tenant yet. Confirm an edge in /lake/lineage and the strategy graduates to productive automatically.";
  } else {
    // L4 on, L3 off — strategy is wired but has no upstream to read.
    lineageEdgeBadge = "configured-stubbed";
    lineageEdgeOverride = "configured · L3-disabled";
    lineageEdgeNote =
      "Configured but L3 is disabled — the lineage_edge strategy depends on L3's confirmed-edge projection. Set WORMBASE_LINEAGE_DISCOVERY_ENABLED=true and confirm at least one edge to wake the strategy.";
  }

  return [
    {
      strategy: "lineage_edge",
      configured: discoveryEnabled,
      productive: lineageEdgeProductive,
      badge: lineageEdgeBadge,
      badgeLabelOverride: lineageEdgeOverride,
      note: lineageEdgeNote,
    },
    {
      strategy: "dbt_test",
      configured: dbtTestEnabled,
      productive: false,
      badge: dbtTestEnabled ? "configured-stubbed" : "disabled",
      badgeLabelOverride: dbtTestEnabled
        ? "configured · empty-upstream"
        : undefined,
      note: dbtTestEnabled
        ? "Configured but empty upstream — the strategy is wired correctly; Wave 1's catalog-manifest mirror does not yet emit dbt tests, so the dbt-test reader returns []. Once the Wave 1 mirror emits dbt-test rows the strategy graduates to productive automatically."
        : "Disabled — depends on WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED + WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED + Wave 1 dbt-test mirroring.",
    },
    {
      strategy: "type_coercion",
      configured: discoveryEnabled,
      productive: discoveryEnabled,
      badge: discoveryEnabled ? "production" : "disabled",
      note: discoveryEnabled
        ? "Productive — reasons over column type transitions (varchar↔int / nullable↔not_null / etc.) using bare type metadata that Wave 1 already mirrors. No L3 dependency."
        : "Disabled — set WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true to wire the L4 inference axis.",
    },
    {
      strategy: "governance_classification",
      configured: governanceEnabled,
      productive: governanceProductive,
      badge: governanceBadge,
      badgeLabelOverride: governanceOverride,
      note: governanceNote,
    },
    {
      strategy: "semantic_type",
      configured: semanticTypeEnabled,
      productive: semanticTypeProductive,
      badge: semanticTypeBadge,
      badgeLabelOverride: semanticTypeOverride,
      note: semanticTypeNote,
    },
  ];
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  isTruthy,
  mapRow,
  _composeSchemaImpactFilter,
};
