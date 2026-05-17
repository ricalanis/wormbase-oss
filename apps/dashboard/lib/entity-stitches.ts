/**
 * /lake/entity-stitches read-side accessors — L8 Sub-wave D (2026-06-07).
 *
 * Reads the ``projection_entity_stitches`` table (v026) populated by the
 * L8 Compounding axis (Sub-wave B's composite stitcher built on
 * ``LakeLoopComposite[ProposedEntityStitch]`` and reading L5's confirmed
 * semantic types via the **reused** L6 ``ConfirmedSemanticTypeReader``
 * Protocol — second consumer of the same Protocol; the third cross-axis
 * chain after L4→L3 and L6→L5).
 *
 * One row per ``(company_id, stitch_id)`` with state ∈
 * {proposed, confirmed, rejected}.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise — the page renders an empty state in both cases.
 * We never substitute fixtures.
 *
 * L8 is the 6th lake-side axis AND the 3rd cross-axis chain (after
 * L4→L3 and L6→L5). The strategy status banner reads BOTH the L8 env
 * knobs AND the count of L5 ``confirmed`` semantic types for the
 * tenant. The ``name_match`` strategy is honest about its optional L5
 * dependency:
 *
 *   * L8 off                                   → ``disabled``
 *   * L8 on, anchor off                        → ``productive · fuzzy-only`` (no L5 read)
 *   * L8 on, anchor on, L5 off                 → ``configured · L5-disabled``
 *   * L8 on, anchor on, L5 on, 0 confirmed     → ``configured · awaiting-L5-types``
 *   * L8 on, anchor on, L5 on, ≥1 confirmed    → ``productive · L5-dependent`` (with count)
 *
 * ``schema_shape`` is productive on bare catalog metadata when L8 is
 * enabled AND the catalog-mirror Wave 2 substrate
 * (``projection_catalog_tables``) carries ≥1 folded
 * ``catalog_table_imported`` entry for the tenant. Wave 2 (2026-06-10
 * — Sub-wave C) flips the banner from "productive (when columns
 * available) · currently quiet" to ``productive · per-connector`` once
 * substrate entries land. csv_local / dbt / snowflake are productive
 * today via the catalog_column_extractors registry; other connectors
 * graduate by registering an extractor.
 *
 * ``sample_overlap`` honest-stub posture today — when the sampler is
 * the production ``NoopSampler``, the strategy emits no proposals
 * (empty samples → 0.0 Jaccard → below threshold). Note labels it
 * ``configured · empty-upstream`` when the sub-knob is on.
 *
 * Sub-wave C handoff concerns honored:
 *
 *   * #1 SchemaShape no-op surfaced honestly in banner ("currently
 *     quiet — awaits per-column catalog imports").
 *   * #2 Pair enumeration O(N²) — the high-density advisory triggers
 *     on rows > 200.
 *   * #3 ``entity_kind`` admin override out of scope today; confirm
 *     button posts without override.
 *   * #4 NameMatch fuzzy → entity_kind="other" rendered as muted slate
 *     chip (the "unclassified" tier).
 *   * #5 Tenant scope closure returns [] today, moot for this surface.
 */

import { getCatalogTableImportCount } from "./catalog-mirror";
import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** 8-value strict ``EntityKind`` Literal from the ledger payload.
 *  Pinned here so the dashboard stays in lock-step with the ledger
 *  schema — adding a new entity_kind requires updating this union (a
 *  load-bearing compile error). Mirrors
 *  :data:`wormbase_ledger.entries.EntityKind` and L8 strategies'
 *  :data:`EntityKind` exactly. ``other`` is the catch-all + the
 *  fallback for fuzzy-name-only matches (per handoff concern #4 —
 *  rendered as muted slate so it reads as "unclassified"). */
export type EntityKind =
  | "person"
  | "organization"
  | "transaction"
  | "product"
  | "event"
  | "location"
  | "session"
  | "other";

/** One of the 3 inference strategies. */
export type EntityStitchStrategy =
  | "name_match"
  | "sample_overlap"
  | "schema_shape";

/** One row in the /lake/entity-stitches page table. */
export interface EntityStitchRow {
  /** Deterministic SHA-256(:32 hex) hash over the canonical pair of
   *  (source_id, table_id, column) triples — order-independent. */
  stitchId: string;
  /** A-endpoint source UUID. */
  srcSourceIdA: string;
  /** A-endpoint table id. */
  srcTableA: string;
  /** A-endpoint column name. */
  srcColumnA: string;
  /** B-endpoint source UUID. */
  srcSourceIdB: string;
  /** B-endpoint table id. */
  srcTableB: string;
  /** B-endpoint column name. */
  srcColumnB: string;
  /** L5 semantic type that drove this stitch, when applicable. Set on
   *  ``name_match`` proposals from the semantic-type-anchor path;
   *  ``null`` for fuzzy-name-only / sample-overlap / schema-shape
   *  proposals. When set, the dashboard renders a
   *  "view L5 semantic type →" cross-axis link. */
  upstreamSemanticTypeId: string | null;
  /** Strict 8-value Literal enum from the ledger payload. */
  entityKind: EntityKind;
  /** Confidence float in [0.0, 1.0]. */
  confidence: number;
  /** Strategy that produced (or last-updated) the proposal. */
  strategy: EntityStitchStrategy;
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
export interface EntityStitchStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` field convention). */
  strategy: EntityStitchStrategy;
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce proposals today against this tenant. */
  productive: boolean;
  /** Short doc-string surfaced in the banner. */
  note: string;
  /** Honest status banner badge keyword. */
  badge: "production" | "configured-stubbed" | "disabled";
  /** Optional override label for the badge, e.g.
   *  ``productive · L5-dependent`` or
   *  ``configured · awaiting-L5-types``. */
  badgeLabelOverride?: string;
}

/**
 * Per-page filter for /lake/entity-stitches (2026-05-16). Surfaces
 * the URL param produced by the L5↦L8 reverse-arc badge (R3) on the
 * producer-side /lake/semantic-types page. When set, narrows the
 * rendered tables to stitches derived from the specified upstream L5
 * semantic type (NameMatch anchor path). Honest empty when no rows
 * match.
 */
export interface EntityStitchFilter {
  upstreamSemanticTypeId?: string;
  /**
   * Producer-side primary-key deep-link (2026-05-16 — Lake-Side Overview
   * activity-stream drill-in coverage). When set, narrows the rendered
   * tables to the single entity-stitch identified by ``stitchId``.
   * Honest empty when no row matches. ``stitch_id`` is a first-class
   * column on ``projection_entity_stitches``.
   */
  stitchId?: string;
}

/**
 * L5-dependency probe summary surfaced by the dependency banner.
 * Mirrors :class:`L5DependencyState` from L6's surface. Surfaced when
 * the NameMatch anchor is enabled but L5 has zero confirmed types —
 * operators need to understand why the anchor path is wired but quiet.
 */
export interface L5DependencyState {
  /** True iff ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` is truthy. */
  l5Enabled: boolean;
  /** Number of ``confirmed`` ``projection_semantic_types`` rows for this tenant. */
  confirmedSemanticTypeCount: number;
}

/** Aggregate count for the high-density advisory + headline. */
export interface EntityStitchCounts {
  proposed: number;
  confirmed: number;
  rejected: number;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface EntityStitchQueryRow extends Record<string, unknown> {
  stitch_id: string;
  src_source_id_a: string;
  src_table_a: string;
  src_column_a: string;
  src_source_id_b: string;
  src_table_b: string;
  src_column_b: string;
  upstream_semantic_type_id: string | null;
  entity_kind: string;
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

function mapRow(r: EntityStitchQueryRow): EntityStitchRow {
  return {
    stitchId: r.stitch_id,
    srcSourceIdA: r.src_source_id_a,
    srcTableA: r.src_table_a,
    srcColumnA: r.src_column_a,
    srcSourceIdB: r.src_source_id_b,
    srcTableB: r.src_table_b,
    srcColumnB: r.src_column_b,
    upstreamSemanticTypeId: r.upstream_semantic_type_id,
    entityKind: r.entity_kind as EntityKind,
    confidence: toFloat(r.confidence),
    strategy: r.strategy as EntityStitchStrategy,
    reasoning: r.reasoning,
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for an
 * :class:`EntityStitchFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * Currently a single optional predicate (``upstreamSemanticTypeId``
 * → first-class column). Shape mirrors the other accessors'
 * composer helpers for symmetry across the bundle.
 */
function _composeEntityStitchFilter(
  filter: EntityStitchFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.upstreamSemanticTypeId) {
    predicates.push(`AND upstream_semantic_type_id = $${p}`);
    values.push(filter.upstreamSemanticTypeId);
    p += 1;
  }
  if (filter.stitchId) {
    predicates.push(`AND stitch_id = $${p}`);
    values.push(filter.stitchId);
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
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) entity-
 * stitch proposal for a tenant, newest first.
 *
 * Optional ``filter`` narrows the result set to rows derived from a
 * specific upstream L5 semantic type (anchor-path proposals). Honest
 * empty when no rows match.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state. No
 * FIXTURE return per CLAUDE.md §9.
 */
export async function getProposedEntityStitches(
  companyId: string,
  opts: { limit?: number; filter?: EntityStitchFilter } = {},
): Promise<EntityStitchRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeEntityStitchFilter(opts.filter, 2);

  const sql = `
    SELECT
      stitch_id,
      src_source_id_a,
      src_table_a,
      src_column_a,
      src_source_id_b,
      src_table_b,
      src_column_b,
      upstream_semantic_type_id,
      entity_kind,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_entity_stitches
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, stitch_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<EntityStitchQueryRow>(sql, [
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
 * Fetch every confirmed entity-stitch proposal for a tenant.
 *
 * Optional ``filter`` mirrors :func:`getProposedEntityStitches`.
 */
export async function getConfirmedEntityStitches(
  companyId: string,
  opts: { limit?: number; filter?: EntityStitchFilter } = {},
): Promise<EntityStitchRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeEntityStitchFilter(opts.filter, 2);

  const sql = `
    SELECT
      stitch_id,
      src_source_id_a,
      src_table_a,
      src_column_a,
      src_source_id_b,
      src_table_b,
      src_column_b,
      upstream_semantic_type_id,
      entity_kind,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_entity_stitches
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, stitch_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<EntityStitchQueryRow>(sql, [
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
 * Fetch rejected entity-stitch proposals in the last ``days`` (default
 * 30) for strategy-tuning audit. Surfaced collapsed by default.
 */
export async function getRejectedEntityStitches(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: EntityStitchFilter } = {},
): Promise<EntityStitchRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeEntityStitchFilter(opts.filter, 3);

  const sql = `
    SELECT
      stitch_id,
      src_source_id_a,
      src_table_a,
      src_column_a,
      src_source_id_b,
      src_table_b,
      src_column_b,
      upstream_semantic_type_id,
      entity_kind,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_entity_stitches
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, stitch_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<EntityStitchQueryRow>(sql, [
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
 * Return the latest projection row for a single (company_id,
 * stitch_id). Used by the detail panel + the click-through audit view.
 */
export async function getEntityStitchEvidence(
  companyId: string,
  stitchId: string,
): Promise<EntityStitchRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      stitch_id,
      src_source_id_a,
      src_table_a,
      src_column_a,
      src_source_id_b,
      src_table_b,
      src_column_b,
      upstream_semantic_type_id,
      entity_kind,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_entity_stitches
    WHERE company_id = $1
      AND stitch_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<EntityStitchQueryRow>(sql, [companyId, stitchId]);
    if (res.rows.length === 0) return null;
    return mapRow(res.rows[0]);
  } catch {
    return null;
  }
}

/**
 * Probe the L5-dependency state for this tenant. Reads the env knob
 * for L5 + counts confirmed ``projection_semantic_types`` rows.
 *
 * Returns ``confirmedSemanticTypeCount = 0`` when the table is missing
 * or the query throws — the page renders an honest "no L5 confirmed
 * types available" banner (mirrors L6's L5-dependency banner).
 */
export async function getL5DependencyStateForStitches(
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
    if (res.rows.length === 0)
      return { l5Enabled, confirmedSemanticTypeCount: 0 };
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
 * banner on ``/lake/entity-stitches``. Reads the L8 env knobs + the L5
 * confirmed-type count probe (the 3rd cross-axis chain — reusing L6's
 * Protocol shape on the backend).
 *
 * Strategy posture per L8 design §7:
 *
 *   * ``name_match`` — 4 honest states keyed off the L8 anchor sub-
 *     knob + the L5 confirmed-type count probe:
 *       - anchor off                                 → ``productive · fuzzy-only``
 *       - anchor on, L5 disabled                     → ``configured · L5-disabled``
 *       - anchor on, L5 on, 0 confirmed types        → ``configured · awaiting-L5-types``
 *       - anchor on, L5 on, ≥1 confirmed type        → ``productive · L5-dependent``
 *     Fuzzy-name path always runs independently when L8 is on; the
 *     anchor path is additive.
 *
 *   * ``schema_shape`` — productive on bare catalog metadata when L8
 *     is on AND ``projection_catalog_tables`` (catalog-mirror Wave 2
 *     substrate) has ≥1 folded entry for the tenant.
 *     - L8 off                                   → ``disabled``
 *     - L8 on, substrate empty                   → ``productive (when columns available)`` + "currently quiet — awaits per-table catalog imports" qualifier
 *     - L8 on, ≥1 folded entry                   → ``productive · per-connector``
 *
 *   * ``sample_overlap`` — honest-stub posture. When the sub-knob is
 *     enabled but the sampler is the production ``NoopSampler``
 *     (empty-upstream), the strategy emits no proposals. Labelled
 *     ``configured · empty-upstream``.
 *
 * Tenant-isolation: this reader composes env-knob state (process-
 * global) with a per-tenant L5 confirmed-type count probe. The L8
 * surface itself is env-gated.
 */
export async function getEntityStitchStrategyStatus(
  companyId: string,
): Promise<EntityStitchStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED,
  );
  const semanticAnchorEnabled =
    discoveryEnabled &&
    isTruthy(
      process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED,
    );
  const sampleOverlapEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED);

  // name_match — fuzzy path always runs when L8 is on; anchor path is
  // additive and depends on L5.
  let nameMatchBadge: EntityStitchStrategyStatus["badge"];
  let nameMatchOverride: string | undefined;
  let nameMatchNote: string;
  let nameMatchProductive = false;

  let l5State: L5DependencyState = {
    l5Enabled: false,
    confirmedSemanticTypeCount: 0,
  };
  if (semanticAnchorEnabled) {
    l5State = await getL5DependencyStateForStitches(companyId);
  }

  if (!discoveryEnabled) {
    nameMatchBadge = "disabled";
    nameMatchNote =
      "Disabled — set WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true to wire the L8 inference axis. NameMatch fires on shared L5 confirmed semantic types (anchor path) AND normalised-Levenshtein column name similarity ≥0.70 (fuzzy path, no upstream dependency).";
  } else if (!semanticAnchorEnabled) {
    nameMatchBadge = "production";
    nameMatchOverride = "productive · fuzzy-only";
    nameMatchProductive = true;
    nameMatchNote =
      "Productive — fuzzy-name path only (normalised-Levenshtein similarity ≥0.70 → 0.60-0.75 confidence). The L5 anchor path is off (set WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED=true to wire it as a second cross-axis chain through L6's reused ConfirmedSemanticTypeReader Protocol). Fuzzy-only proposals always carry entity_kind=other (no entity-class signal from bare names).";
  } else if (!l5State.l5Enabled) {
    nameMatchBadge = "configured-stubbed";
    nameMatchOverride = "configured · L5-disabled";
    nameMatchProductive = true; // fuzzy path is still productive
    nameMatchNote =
      "Configured but L5 is disabled — the L5-anchor path of NameMatch depends on L5's confirmed-semantic-type projection. The fuzzy-name sub-path still runs (entity_kind=other for those proposals). Set WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true and confirm at least one semantic type in /lake/semantic-types to wake the anchor path.";
  } else if (l5State.confirmedSemanticTypeCount === 0) {
    nameMatchBadge = "configured-stubbed";
    nameMatchOverride = "configured · awaiting-L5-types";
    nameMatchProductive = true; // fuzzy path is still productive
    nameMatchNote =
      "Configured but awaiting L5 confirmations — the anchor path is wired against L5's projection but no confirmed semantic types exist for this tenant yet. The fuzzy-name sub-path still runs (entity_kind=other for those proposals). Confirm a type in /lake/semantic-types and the anchor path graduates to productive automatically.";
  } else {
    nameMatchBadge = "production";
    nameMatchOverride = "productive · L5-dependent";
    nameMatchProductive = true;
    const n = l5State.confirmedSemanticTypeCount;
    nameMatchNote = `Productive — anchor path is reading ${n} confirmed L5 semantic type${n === 1 ? "" : "s"} for this tenant (second consumer of L6's reused ConfirmedSemanticTypeReader Protocol). When both endpoints share a confirmed semantic type (e.g. both pii_email), proposes at 0.90 confidence with entity_kind inferred from the type (e.g. email/pii_* → person, business_id → organization). The fuzzy-name sub-path runs alongside at 0.60-0.75 with entity_kind=other.`;
  }

  // schema_shape — productive when L8 on AND catalog-mirror Wave 2
  // substrate has folded ≥1 ``catalog_table_imported`` entry for the
  // tenant. Wave 2 (2026-06-10) ships the substrate — banner drops
  // the "currently quiet" qualifier when entries exist.
  let schemaShapeNote: string;
  let schemaShapeBadge: EntityStitchStrategyStatus["badge"];
  let schemaShapeOverride: string | undefined;
  let schemaShapeProductive = false;
  if (!discoveryEnabled) {
    schemaShapeBadge = "disabled";
    schemaShapeNote =
      "Disabled — set WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true to wire the L8 inference axis. SchemaShape compares parent-table structure (column-count delta ≤2, shared name-set ratio ≥0.5) and proposes stitches for matching-name column pairs at 0.50-0.75.";
  } else {
    // Probe the Wave 2 substrate count for this tenant. Cheap
    // single-COUNT(*) query; reused via the shared catalog-mirror
    // accessor (also consumed by the L2 banner posture).
    const catalogTableImportCount = await getCatalogTableImportCount(companyId);
    if (catalogTableImportCount === 0) {
      schemaShapeBadge = "configured-stubbed";
      schemaShapeOverride = "productive (when columns available)";
      schemaShapeProductive = false;
      schemaShapeNote =
        "Configured — productive on bare catalog metadata (compares column-count delta ≤2, shared name-set ratio ≥0.5; emits matching-name pairs at 0.50-0.75). currently quiet — awaits per-table catalog imports (the parent-table column-list lookup closure returns [] for this tenant because no ``catalog_table_imported`` entries have been folded yet; SchemaShape graduates to productive once a connector with a registered ``catalog_column_extractor`` runs against a source — csv_local / dbt / snowflake do so today). entity_kind defaults to other (schema shape alone doesn't disambiguate entity class).";
    } else {
      schemaShapeBadge = "production";
      schemaShapeOverride = "productive · per-connector";
      schemaShapeProductive = true;
      const n = catalogTableImportCount;
      schemaShapeNote = `Productive — reading ${n} folded ``catalog_table_imported`` entr${n === 1 ? "y" : "ies"} from the catalog-mirror Wave 2 substrate (``projection_catalog_tables``). The strategy compares parent-table structure (column-count delta ≤2, shared name-set ratio ≥0.5) and emits matching-name pairs at 0.50-0.75. csv_local / dbt / snowflake emit per-table entries via the catalog_column_extractors registry; opaque-secret connectors land entries with ``columns=()`` (honest-empty-upstream) and contribute no shape signal until an extractor is registered. entity_kind defaults to other (schema shape alone doesn't disambiguate entity class).`;
    }
  }

  // sample_overlap — honest-stub posture (NoopSampler today).
  let sampleOverlapNote: string;
  let sampleOverlapBadge: EntityStitchStrategyStatus["badge"];
  let sampleOverlapOverride: string | undefined;
  if (!sampleOverlapEnabled) {
    sampleOverlapBadge = "disabled";
    sampleOverlapNote =
      "Disabled — set WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true and WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED=true to wire the value-overlap strategy. SampleOverlap samples up to 200 distinct values from each endpoint via L7's reused SamplerProtocol and proposes at 0.50-0.85 when Jaccard ≥0.50.";
  } else {
    sampleOverlapBadge = "configured-stubbed";
    sampleOverlapOverride = "configured · empty-upstream";
    sampleOverlapNote =
      "Configured but empty-upstream — the production NoopSampler returns empty sets, so SampleOverlap emits no proposals (empty samples → 0.0 Jaccard → below threshold). Wires through L7's reused SamplerProtocol; graduates to productive once a real per-source sampler is bound (post Sub-wave C). entity_kind defaults to other (value overlap alone doesn't disambiguate entity class).";
  }

  return [
    {
      strategy: "name_match",
      configured: discoveryEnabled,
      productive: nameMatchProductive,
      badge: nameMatchBadge,
      badgeLabelOverride: nameMatchOverride,
      note: nameMatchNote,
    },
    {
      strategy: "sample_overlap",
      configured: sampleOverlapEnabled,
      productive: false, // NoopSampler today
      badge: sampleOverlapBadge,
      badgeLabelOverride: sampleOverlapOverride,
      note: sampleOverlapNote,
    },
    {
      strategy: "schema_shape",
      configured: discoveryEnabled,
      productive: schemaShapeProductive,
      badge: schemaShapeBadge,
      badgeLabelOverride: schemaShapeOverride,
      note: schemaShapeNote,
    },
  ];
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  isTruthy,
  mapRow,
  _composeEntityStitchFilter,
};
