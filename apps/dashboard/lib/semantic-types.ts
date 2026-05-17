/**
 * /lake/semantic-types read-side accessors — L5 Sub-wave D (2026-06-05).
 *
 * Reads the ``projection_semantic_types`` table (v024) populated by the
 * L5 Compounding axis (Sub-wave B's composite fingerprinting service
 * built from day one on ``LakeLoopComposite[ProposedSemanticType]``).
 * One row per ``(company_id, type_id)`` with state ∈ {proposed,
 * confirmed, rejected}.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise — the page renders an empty state in both cases.
 * We never substitute fixtures.
 *
 * Strategy-status posture per L5 design §4 (mirrors L3/L7/L4 patterns):
 *
 *   * ``column_name``   — ``productive`` (regex over bare names; the
 *     only L5 strategy that needs zero upstream sampler / stats and so
 *     graduates to productive whenever L5 is enabled).
 *   * ``value_pattern`` — ``configured · empty-upstream`` when L5 +
 *     value_pattern env knobs are on (Wave 1 sampler hook not yet
 *     emitting); ``disabled`` when env knob OFF.
 *   * ``distribution``  — ``configured · empty-upstream`` when L5 +
 *     distribution env knobs are on (per-column historical stats not
 *     yet emitting); ``disabled`` when env knob OFF.
 *
 * The page renders these honestly via the shared ``CapabilityBadges``
 * component (handoff concern #4: strategies that lack real upstream
 * today must say so, not pretend to be productive).
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** One of the 19 strict semantic-type values from
 *  :class:`SemanticTypeProposedPayload`. Pinned here so the dashboard
 *  surface stays in lock-step with the ledger schema — adding a new
 *  semantic_type to the ledger requires updating this union (a load-
 *  bearing compile error). */
export type SemanticTypeValue =
  // Identity
  | "email"
  | "phone_e164"
  | "phone_us"
  // Temporal
  | "iso_date"
  | "iso_datetime"
  | "unix_timestamp"
  // Identifiers
  | "uuid_v4"
  | "uuid_v7"
  | "business_id"
  // Geo/locale
  | "country_iso"
  | "language_iso"
  | "currency_iso"
  // PII (sensitive)
  | "pii_name"
  | "pii_address"
  | "pii_ssn"
  | "pii_credit_card"
  // Metric
  | "metric_count"
  | "metric_amount"
  | "metric_rate"
  // Catch-all
  | "other";

/** One row in the /lake/semantic-types page table. */
export interface SemanticTypeRow {
  /** Deterministic hash over (table_id, column, semantic_type). */
  typeId: string;
  /** UUID of the catalog table whose column was fingerprinted. */
  tableId: string;
  /** Column name. */
  column: string;
  /** Strict 19-value Literal enum from the ledger payload. */
  semanticType: SemanticTypeValue;
  /** Confidence float in [0.0, 1.0]. */
  confidence: number;
  /** Strategy that produced (or last-updated) the proposal. */
  strategy: "column_name" | "value_pattern" | "distribution";
  /** Human-readable explanation rendered on the row detail panel. */
  reasoning: string;
  /** Structured evidence dict surfaced verbatim on the detail panel
   *  (e.g. ``{"match_count": 18, "sample_n": 20, "regex": "..."}``). */
  evidence: Record<string, unknown>;
  /** Current state — ``"proposed"`` | ``"confirmed"`` | ``"rejected"``. */
  state: "proposed" | "confirmed" | "rejected";
  /** ISO-8601 timestamp the state last changed. */
  stateChangedAt: string;
  /** Person UUID that last changed state; ``null`` while in proposed. */
  stateChangedBy: string | null;
}

/**
 * Per-page filter for /lake/semantic-types (2026-05-16).
 *
 * Producer-side deep-link filter — narrows the rendered tables to a
 * single L5 semantic type identified by its primary-key ``typeId``.
 * Honored by every projection accessor below. Surfaces the
 * ``?type_id=<id>`` URL param landed on producer pages alongside the
 * consumer-page ``upstream_*_id`` filter family from ``be0bbc7``.
 */
export interface SemanticTypeFilter {
  typeId?: string;
}

/** Per-strategy productivity signal surfaced by the status banner. */
export interface SemanticTypeStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` field convention). */
  strategy: "column_name" | "value_pattern" | "distribution";
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce proposals today against this tenant. */
  productive: boolean;
  /**
   * Short doc-string surfaced in the banner. Distinguishes the three
   * postures: productive / configured · empty-upstream / disabled.
   */
  note: string;
  /**
   * Honest status banner badge keyword. Mirrors :class:`CapabilityStatus`
   * values so the page can drop straight into the shared
   * ``CapabilityBadges`` component.
   */
  badge: "production" | "configured-stubbed" | "disabled";
  /**
   * Optional override label for the badge. ``value_pattern`` +
   * ``distribution`` use this for the ``configured · empty-upstream``
   * posture per L5 design §4.
   */
  badgeLabelOverride?: string;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface SemanticTypeQueryRow extends Record<string, unknown> {
  type_id: string;
  table_id: string;
  column: string;
  semantic_type: string;
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

function mapRow(r: SemanticTypeQueryRow): SemanticTypeRow {
  return {
    typeId: r.type_id,
    tableId: r.table_id,
    column: r.column,
    semanticType: r.semantic_type as SemanticTypeValue,
    confidence: toFloat(r.confidence),
    strategy: r.strategy as SemanticTypeRow["strategy"],
    reasoning: r.reasoning,
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`SemanticTypeFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * Currently a single optional predicate (``typeId`` → primary-key
 * column).
 */
function _composeSemanticTypeFilter(
  filter: SemanticTypeFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.typeId) {
    predicates.push(`AND type_id = $${p}`);
    values.push(filter.typeId);
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
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) semantic-
 * type proposal for a tenant, newest first. The page's "Pending
 * Proposals" section renders these with Confirm/Reject actions for
 * admins.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state.
 */
export async function getProposedSemanticTypes(
  companyId: string,
  opts: { limit?: number; filter?: SemanticTypeFilter } = {},
): Promise<SemanticTypeRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeSemanticTypeFilter(opts.filter, 2);

  // ``column`` is a Postgres reserved word — always double-quoted on
  // the wire. SQLite preserves the bare identifier but accepts the
  // quoted form too; we use the quoted form universally for
  // portability.
  const sql = `
    SELECT
      type_id,
      table_id,
      "column" AS column,
      semantic_type,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_semantic_types
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, type_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SemanticTypeQueryRow>(sql, [
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
 * Fetch every confirmed semantic-type proposal for a tenant. The
 * page's confirmed section renders these as a table; clicking expands
 * the evidence + reasoning panel.
 */
export async function getConfirmedSemanticTypes(
  companyId: string,
  opts: { limit?: number; filter?: SemanticTypeFilter } = {},
): Promise<SemanticTypeRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeSemanticTypeFilter(opts.filter, 2);

  const sql = `
    SELECT
      type_id,
      table_id,
      "column" AS column,
      semantic_type,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_semantic_types
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, type_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SemanticTypeQueryRow>(sql, [
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
 * Fetch rejected semantic-type proposals in the last ``days`` (default
 * 30) for strategy-tuning audit. Surfaced collapsed by default.
 */
export async function getRejectedSemanticTypes(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: SemanticTypeFilter } = {},
): Promise<SemanticTypeRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeSemanticTypeFilter(opts.filter, 3);

  const sql = `
    SELECT
      type_id,
      table_id,
      "column" AS column,
      semantic_type,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_semantic_types
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, type_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<SemanticTypeQueryRow>(sql, [
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
 * Return the latest projection row for a single (company_id, type_id).
 * Used by the detail panel + the click-through audit view.
 */
export async function getSemanticTypeEvidence(
  companyId: string,
  typeId: string,
): Promise<SemanticTypeRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      type_id,
      table_id,
      "column" AS column,
      semantic_type,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_semantic_types
    WHERE company_id = $1
      AND type_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<SemanticTypeQueryRow>(sql, [companyId, typeId]);
    if (res.rows.length === 0) return null;
    return mapRow(res.rows[0]);
  } catch {
    return null;
  }
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the status
 * banner on ``/lake/semantic-types``. Reads the L5 env knobs.
 *
 * Strategy posture per L5 design §4:
 *
 *   * ``column_name`` — productive when L5 is enabled. Operates purely
 *     on column names from the catalog (no sampler / stats upstream
 *     dependency). Graduates immediately. ``disabled`` when L5 master
 *     switch is OFF.
 *
 *   * ``value_pattern`` — ``configured · empty-upstream`` when L5 +
 *     value_pattern env knobs are on. The strategy is wired correctly
 *     but the Wave 1 sampler hook does not yet emit sampled values,
 *     so the strategy returns ``[]`` in practice. Honest banner per
 *     handoff concern #4. ``disabled`` when value_pattern env knob is
 *     OFF.
 *
 *   * ``distribution`` — ``configured · empty-upstream`` when L5 +
 *     distribution env knobs are on. Per-column historical stats are
 *     not yet emitted; same honest posture as ``value_pattern``.
 *     ``disabled`` when distribution env knob is OFF.
 *
 * Tenant-isolation: this reader is env-knob-driven (process-global) —
 * the L5 surface itself is env-gated, so the per-tenant fingerprinting
 * loop is identically configured across all tenants today. Per-tenant
 * gauges are deferred to Phase 2 when L5 grows tenant-specific knobs.
 */
export async function getSemanticTypeStrategyStatus(
  _companyId: string,
): Promise<SemanticTypeStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED,
  );
  const valuePatternEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED);
  const distributionEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED);

  return [
    {
      strategy: "column_name",
      configured: discoveryEnabled,
      productive: discoveryEnabled,
      badge: discoveryEnabled ? "production" : "disabled",
      note: discoveryEnabled
        ? "Productive — regex-matches column names against the 19-value semantic-type lexicon (e.g. /^email/i → email). No upstream sampler / stats dependency; operates purely on catalog column names that Wave 1 already mirrors."
        : "Disabled — set WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true to wire the L5 inference axis.",
    },
    {
      strategy: "value_pattern",
      configured: valuePatternEnabled,
      productive: false,
      badge: valuePatternEnabled ? "configured-stubbed" : "disabled",
      badgeLabelOverride: valuePatternEnabled
        ? "configured · empty-upstream"
        : undefined,
      note: valuePatternEnabled
        ? "Configured but empty upstream — the strategy is wired correctly; the Wave 1 sampler hook does not yet emit sampled column values, so the per-column value reader returns []. Once the sampler emits sample batches the strategy graduates to productive automatically."
        : "Disabled — depends on WORMBASE_FINGERPRINT_DISCOVERY_ENABLED + WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED + Wave 1 sampler emission.",
    },
    {
      strategy: "distribution",
      configured: distributionEnabled,
      productive: false,
      badge: distributionEnabled ? "configured-stubbed" : "disabled",
      badgeLabelOverride: distributionEnabled
        ? "configured · empty-upstream"
        : undefined,
      note: distributionEnabled
        ? "Configured but empty upstream — the strategy is wired correctly; per-column historical-distribution stats (cardinality, length percentiles, null rate) are not yet emitted, so the stats reader returns []. Once the column-stats projection emits rows the strategy graduates to productive automatically."
        : "Disabled — depends on WORMBASE_FINGERPRINT_DISCOVERY_ENABLED + WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED + per-column stats emission.",
    },
  ];
}

// ─── Reverse-arc enrichment (Recipe Addendum #3) ─────────────────────────
//
// L5 is the **most-consumed** producer in the lake stack: 4 downstream
// axes (L6 classifications, L8 entity stitches, L7 quality checks, L4
// schema impacts) all consult L5's confirmed semantic types. This page
// surfaces all four reverse arcs as a compact "downstream counts"
// cluster on each row so operators can see at-a-glance which confirmed
// types are pulling weight across the lake.
//
// Storage shape per chain (verified empirically against the projection
// migrations + agent-gateway strategy writers):
//
//   * R2 L6→L5: ``projection_column_classifications.upstream_semantic_type_id``
//     is a NULL-able first-class column (v025 line 101). Filter is a
//     direct equality check.
//   * R3 L8→L5: ``projection_entity_stitches.upstream_semantic_type_id``
//     is a NULL-able first-class column (v026 line 107). Same shape.
//   * R4 L7→L5: ``projection_quality_checks.evidence`` is a JSON
//     column (v022 line 93); ``upstream_semantic_type_id`` lives
//     inside it (per L5→L7 close-out). Use ``evidence->>`` accessor.
//   * R6 L4→L5: ``projection_schema_impacts.evidence`` is a JSON
//     column (v023 line 101); ``upstream_semantic_type_id`` lives
//     inside it (per L5→L4 close-out: SemanticTypeImpactStrategy
//     writes evidence dict). Use ``evidence->>`` accessor.
//
// All four accessors share the same shape: state filter
// ``IN ('proposed', 'confirmed')``, GROUP BY the L5 type_id, return
// a ``Record<typeId, count>`` map. Honest empty by construction.

/** Reverse-arc lookup map: ``semanticTypeId → downstream-consumer count``. */
export type SemanticTypeReverseArcMap = Record<string, number>;

/**
 * R2 L6↦L5: count L6 column-classification rows per L5 ``type_id``
 * for a tenant. Reads ``projection_column_classifications`` (v025)
 * directly. ``upstream_semantic_type_id`` is a first-class NULL-able
 * column populated when the ``semantic_type`` strategy reads L5's
 * projection — the SQL filters out NULL rows so the map only counts
 * classifications that actually descend from a confirmed L5 type.
 *
 * State filter: ``state IN ('proposed', 'confirmed')`` — rejected
 * classifications are excluded (dispositions, not pending consequences).
 *
 * Tenant-scoped via ``companyId``. Multi-tenant safe. Honest empty
 * map on no-Postgres / query throw / empty-projection.
 */
export async function getClassificationCountBySemanticType(
  companyId: string,
): Promise<SemanticTypeReverseArcMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      upstream_semantic_type_id,
      COUNT(*)::int AS n
    FROM projection_column_classifications
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND upstream_semantic_type_id IS NOT NULL
    GROUP BY upstream_semantic_type_id
  `;

  try {
    const res = await pgQuery<{
      upstream_semantic_type_id: string;
      n: number | string;
    }>(sql, [companyId]);
    const out: SemanticTypeReverseArcMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.n === "number"
          ? row.n
          : Number.parseInt(String(row.n), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_semantic_type_id] = n;
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * R3 L8↦L5: count L8 entity-stitch rows per L5 ``type_id`` for a
 * tenant. Reads ``projection_entity_stitches`` (v026) directly.
 * ``upstream_semantic_type_id`` is a first-class NULL-able column —
 * populated when the L8 strategy's anchor came from L5's confirmed
 * projection. NULL rows (stitches inferred from non-semantic-type
 * signals) are filtered out.
 *
 * State filter: ``state IN ('proposed', 'confirmed')`` — rejected
 * stitches excluded.
 *
 * Tenant-scoped + honest empty per the shared reverse-arc contract.
 */
export async function getEntityStitchCountBySemanticType(
  companyId: string,
): Promise<SemanticTypeReverseArcMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      upstream_semantic_type_id,
      COUNT(*)::int AS n
    FROM projection_entity_stitches
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND upstream_semantic_type_id IS NOT NULL
    GROUP BY upstream_semantic_type_id
  `;

  try {
    const res = await pgQuery<{
      upstream_semantic_type_id: string;
      n: number | string;
    }>(sql, [companyId]);
    const out: SemanticTypeReverseArcMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.n === "number"
          ? row.n
          : Number.parseInt(String(row.n), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_semantic_type_id] = n;
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * R4 L7↦L5: count L7 quality-check rows per L5 ``type_id`` for a
 * tenant. Reads ``projection_quality_checks`` (v022). The
 * ``upstream_semantic_type_id`` link lives inside the JSON
 * ``evidence`` column (per L5→L7 close-out: the field is carried on
 * evidence rather than as a first-class payload field), so the SQL
 * uses the ``evidence->>'upstream_semantic_type_id'`` accessor and
 * filters out NULL paths.
 *
 * State filter: ``state IN ('proposed', 'confirmed')`` — rejected
 * checks excluded.
 *
 * Tenant-scoped + honest empty per the shared reverse-arc contract.
 */
export async function getQualityCheckCountBySemanticType(
  companyId: string,
): Promise<SemanticTypeReverseArcMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      (evidence->>'upstream_semantic_type_id') AS upstream_semantic_type_id,
      COUNT(*)::int AS n
    FROM projection_quality_checks
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND evidence ? 'upstream_semantic_type_id'
      AND (evidence->>'upstream_semantic_type_id') IS NOT NULL
    GROUP BY (evidence->>'upstream_semantic_type_id')
  `;

  try {
    const res = await pgQuery<{
      upstream_semantic_type_id: string;
      n: number | string;
    }>(sql, [companyId]);
    const out: SemanticTypeReverseArcMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.n === "number"
          ? row.n
          : Number.parseInt(String(row.n), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_semantic_type_id] = n;
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * R6 L4↦L5: count L4 schema-evolution-impact rows per L5 ``type_id``
 * for a tenant. Reads ``projection_schema_impacts`` (v023). The
 * ``upstream_semantic_type_id`` link lives inside the JSON
 * ``evidence`` column (per L5→L4 close-out: SemanticTypeImpactStrategy
 * writes evidence dict — see agent-gateway/schema_impact/strategies.py
 * line 889), so the SQL uses the ``evidence->>'upstream_semantic_type_id'``
 * accessor and filters out NULL paths.
 *
 * State filter: ``state IN ('proposed', 'confirmed')`` — rejected
 * impacts excluded. Matches the L4↦L2 Half B precedent for
 * `getImpactCountByDriftSource`.
 *
 * Tenant-scoped + honest empty per the shared reverse-arc contract.
 */
export async function getSchemaImpactCountBySemanticType(
  companyId: string,
): Promise<SemanticTypeReverseArcMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      (evidence->>'upstream_semantic_type_id') AS upstream_semantic_type_id,
      COUNT(*)::int AS n
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND evidence ? 'upstream_semantic_type_id'
      AND (evidence->>'upstream_semantic_type_id') IS NOT NULL
    GROUP BY (evidence->>'upstream_semantic_type_id')
  `;

  try {
    const res = await pgQuery<{
      upstream_semantic_type_id: string;
      n: number | string;
    }>(sql, [companyId]);
    const out: SemanticTypeReverseArcMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.n === "number"
          ? row.n
          : Number.parseInt(String(row.n), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_semantic_type_id] = n;
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
  _composeSemanticTypeFilter,
};
