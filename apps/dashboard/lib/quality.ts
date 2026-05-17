/**
 * /lake/quality read-side accessors — L7 Sub-wave D (2026-05-30).
 *
 * Reads the projection_quality_checks table (v022) populated by the L7
 * Compounding axis (Sub-wave B's QualityCheckProposalService composing
 * SchemaPatternStrategy + DbtTestsStrategy + HistoricalStatsStrategy).
 * One row per (company_id, check_id) with state ∈ {proposed, confirmed,
 * rejected}.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise. The page renders an empty state in both cases —
 * we never substitute fixtures.
 *
 * Also surfaces per-strategy productivity gauges so the operator-facing
 * banner can label what's actually wired today. Sub-wave C handoff
 * concern #4 (``LedgerDbtTestReader`` returns ``[]`` because Wave 1's
 * mirror does not yet emit dbt tests) demands an honest
 * ``configured · empty-upstream`` label for ``dbt_tests`` — same posture
 * as L3's strategy banner.
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** One row in the /lake/quality page table. */
export interface QualityCheckRow {
  /** Deterministic hash over (table_id, column, check_kind, config). */
  checkId: string;
  /** UUID of the catalog table the check is bound to. */
  tableId: string;
  /** Column name; ``null`` for table-level checks (row_count / freshness). */
  column: string | null;
  /** Check kind — ``unique`` | ``not_null`` | ``enum`` | ``freshness`` | ... */
  checkKind: string;
  /** Strategy-specific config (e.g. ``{"values": [...]}`` for enum). */
  config: Record<string, unknown>;
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

/** Per-strategy productivity signal surfaced by the status banner. */
export interface QualityStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` enum). */
  strategy: string;
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce checks today against this tenant. */
  productive: boolean;
  /**
   * Short doc-string surfaced in the banner. Distinguishes
   * ``productive`` from ``configured · empty-upstream`` from
   * ``configured · stubbed`` from ``disabled``.
   */
  note: string;
  /**
   * Honest status banner badge keyword. Mirrors
   * :class:`CapabilityStatus` values so the page can drop straight into
   * the shared `CapabilityBadges` component.
   */
  badge: "production" | "configured-stubbed" | "disabled";
  /**
   * Optional override label for the badge (used to surface the
   * ``configured · empty-upstream`` posture for ``dbt_tests`` until
   * Wave 1's mirror emits tests).
   */
  badgeLabelOverride?: string;
}

/**
 * Per-page filter for /lake/quality (2026-05-16). Surfaces the URL
 * param produced by the L5↦L7 reverse-arc badge (R4) on the
 * producer-side /lake/semantic-types page. When set, narrows the
 * rendered tables to checks derived from the specified upstream L5
 * semantic type. Honest empty when no rows match.
 *
 * Note: the quality projection stores the upstream pointer in the
 * JSON ``evidence`` column (not a first-class column) — the L5→L7
 * SemanticTypeQualityCheckStrategy stamps ``evidence.upstream_semantic_type_id``
 * on each proposal. The accessor SQL uses the ``evidence->>`` JSON
 * accessor to filter.
 */
export interface QualityCheckFilter {
  upstreamSemanticTypeId?: string;
  /**
   * Producer-side primary-key deep-link (2026-05-16 — Lake-Side Overview
   * activity-stream drill-in coverage). When set, narrows the rendered
   * tables to the single quality check identified by ``checkId``. Honest
   * empty when no row matches. ``check_id`` is a first-class column on
   * ``projection_quality_checks`` — no JSON-evidence lookup needed.
   */
  checkId?: string;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface QualityCheckQueryRow extends Record<string, unknown> {
  check_id: string;
  table_id: string;
  column: string | null;
  check_kind: string;
  config: Record<string, unknown> | null;
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

function mapRow(r: QualityCheckQueryRow): QualityCheckRow {
  return {
    checkId: r.check_id,
    tableId: r.table_id,
    column: r.column,
    checkKind: r.check_kind,
    config: (r.config ?? {}) as Record<string, unknown>,
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
 * :class:`QualityCheckFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * The quality projection stores the upstream pointer in the JSON
 * ``evidence`` column. SQL uses the ``evidence->>`` accessor +
 * ``evidence ?`` containment to skip rows with no upstream pointer
 * at all.
 */
function _composeQualityCheckFilter(
  filter: QualityCheckFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.upstreamSemanticTypeId) {
    predicates.push(
      `AND evidence ? 'upstream_semantic_type_id' AND evidence->>'upstream_semantic_type_id' = $${p}`,
    );
    values.push(filter.upstreamSemanticTypeId);
    p += 1;
  }
  if (filter.checkId) {
    predicates.push(`AND check_id = $${p}`);
    values.push(filter.checkId);
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
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) quality
 * check for a tenant, newest first. The page's "Pending Proposals"
 * section renders these with Confirm/Reject actions for admins.
 *
 * Optional ``filter`` narrows the result set to rows derived from a
 * specific upstream L5 semantic type. Honest empty when no rows match.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state.
 */
export async function getProposedQualityChecks(
  companyId: string,
  opts: { limit?: number; filter?: QualityCheckFilter } = {},
): Promise<QualityCheckRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeQualityCheckFilter(opts.filter, 2);

  const sql = `
    SELECT
      check_id,
      table_id,
      "column",
      check_kind,
      config,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_quality_checks
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, check_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<QualityCheckQueryRow>(sql, [
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
 * Fetch every confirmed quality check for a tenant. The page's
 * confirmed section renders these as a table; clicking expands the
 * config + evidence + reasoning panel.
 *
 * Optional ``filter`` mirrors :func:`getProposedQualityChecks`.
 */
export async function getConfirmedQualityChecks(
  companyId: string,
  opts: { limit?: number; filter?: QualityCheckFilter } = {},
): Promise<QualityCheckRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeQualityCheckFilter(opts.filter, 2);

  const sql = `
    SELECT
      check_id,
      table_id,
      "column",
      check_kind,
      config,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_quality_checks
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, check_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<QualityCheckQueryRow>(sql, [
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
 * Fetch rejected quality checks in the last ``days`` (default 30) for
 * strategy-tuning audit. Surfaced collapsed by default.
 */
export async function getRejectedQualityChecks(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: QualityCheckFilter } = {},
): Promise<QualityCheckRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeQualityCheckFilter(opts.filter, 3);

  const sql = `
    SELECT
      check_id,
      table_id,
      "column",
      check_kind,
      config,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_quality_checks
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, check_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<QualityCheckQueryRow>(sql, [
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
 * Return the latest projection row for a single (company_id, check_id).
 * Used by the detail panel + the click-through audit view.
 */
export async function getQualityCheckEvidence(
  companyId: string,
  checkId: string,
): Promise<QualityCheckRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      check_id,
      table_id,
      "column",
      check_kind,
      config,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_quality_checks
    WHERE company_id = $1
      AND check_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<QualityCheckQueryRow>(sql, [companyId, checkId]);
    if (res.rows.length === 0) return null;
    return mapRow(res.rows[0]);
  } catch {
    return null;
  }
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the status
 * banner on ``/lake/quality``. Reads the L7 env knobs + folds in the
 * Sub-wave C handoff truths:
 *
 *   * ``schema_pattern`` — productive when L7 enabled. Fires column-
 *     naming heuristics (e.g. ``created_at`` → freshness, ``*_id`` →
 *     not_null) on catalog column metadata. Note that some kinds
 *     (``not_null`` / ``enum``) need richer per-column metadata that the
 *     Wave 1 mirror does not yet emit — honest note covers that case.
 *
 *   * ``dbt_tests`` — ``configured · empty-upstream`` when L7 enabled.
 *     :class:`LedgerDbtTestReader` returns ``[]`` today because Wave 1's
 *     catalog-manifest mirror does not yet emit dbt tests. The strategy
 *     is wired correctly; its upstream is empty. This is the honest
 *     posture per Sub-wave C handoff concern #4.
 *
 *   * ``historical_stats`` — ``configured · stubbed`` when its env knob
 *     is on; ``disabled`` otherwise. The stub returns no checks until
 *     column-stats mirroring lands.
 *
 *   * ``semantic_type`` — **L5→L7 cross-axis chain** (4th cross-axis
 *     chain after L4→L3, L6→L5, L8→L5). Reuses L6's
 *     :class:`ConfirmedSemanticTypeReader` Protocol (3rd consumer).
 *     Honest 3-state posture:
 *       - sub-knob off                                          → ``disabled``
 *       - sub-knob on, L5 off OR no L5 confirmed types          → ``configured · awaiting-L5-types``
 *       - sub-knob on, L5 on (and types presumed present)       → ``productive · L5-dependent``
 *     The L5-types-presence check is not performed inline today (env
 *     knobs only); the note is honest about that.
 *
 * Tenant-isolation: this reader is process-env-scoped (env knobs are
 * global to the dashboard process), so ``companyId`` is currently
 * accepted but unused. Kept on the signature for symmetry + future
 * per-tenant overrides.
 */
export async function getQualityStrategyStatus(
  _companyId: string,
): Promise<QualityStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_QUALITY_DISCOVERY_ENABLED,
  );
  const historicalStatsEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED);
  const semanticTypeEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED);
  // L5 is the producer for the cross-axis chain; surfaced honestly so
  // operators see whether the upstream is even on. We do NOT count
  // confirmed types inline today — that's a per-tenant DB read; the
  // banner caveats the dependency in prose.
  const l5Enabled = isTruthy(
    process.env.WORMBASE_FINGERPRINT_DISCOVERY_ENABLED,
  );

  return [
    {
      strategy: "schema_pattern",
      configured: discoveryEnabled,
      productive: discoveryEnabled,
      badge: discoveryEnabled ? "production" : "disabled",
      note: discoveryEnabled
        ? "Productive — column-aware naming heuristics fire on catalog column metadata (freshness on `created_at`, not_null on `*_id`, etc.). Richer kinds (`not_null`/`enum`) need additional column metadata; the strategy yields whatever the catalog mirror can answer today."
        : "Disabled — set WORMBASE_QUALITY_DISCOVERY_ENABLED=true to wire the L7 inference axis.",
    },
    {
      strategy: "dbt_tests",
      configured: discoveryEnabled,
      productive: false,
      badge: discoveryEnabled ? "configured-stubbed" : "disabled",
      badgeLabelOverride: discoveryEnabled
        ? "configured · empty-upstream"
        : undefined,
      note: discoveryEnabled
        ? "Configured but empty upstream — the strategy is wired correctly; Wave 1's catalog-manifest mirror does not yet emit dbt tests, so LedgerDbtTestReader returns []. Once the Wave 1 mirror emits dbt-test rows the strategy graduates to productive automatically."
        : "Disabled — depends on WORMBASE_QUALITY_DISCOVERY_ENABLED + Wave 1 dbt-test mirroring.",
    },
    {
      strategy: "historical_stats",
      configured: historicalStatsEnabled,
      productive: false,
      badge: historicalStatsEnabled ? "configured-stubbed" : "disabled",
      note: historicalStatsEnabled
        ? "Configured but stubbed — column statistics mirroring (distinct counts, range, freshness) is not yet wired. The strategy returns no checks until the upstream stats land."
        : "Disabled — requires WORMBASE_QUALITY_DISCOVERY_ENABLED=true AND WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED=true.",
    },
    {
      strategy: "semantic_type",
      configured: semanticTypeEnabled,
      productive: semanticTypeEnabled && l5Enabled,
      badge: semanticTypeEnabled
        ? l5Enabled
          ? "production"
          : "configured-stubbed"
        : "disabled",
      badgeLabelOverride: semanticTypeEnabled
        ? l5Enabled
          ? "productive · L5-dependent"
          : "configured · awaiting-L5-types"
        : undefined,
      note: semanticTypeEnabled
        ? l5Enabled
          ? "Productive — L5→L7 cross-axis chain (4th cross-axis chain) reading L5 confirmed semantic types via the reused L6 ConfirmedSemanticTypeReader Protocol (3rd consumer of the same Protocol). When L5 confirms a column as `email`/`uuid`/`business_id`, propose `not_null + unique` checks; `phone`/`pii_name`, propose `not_null` only (uniqueness varies). Each proposal carries an `upstream_semantic_type_id` evidence pointer back to the originating L5 type."
          : "Configured but awaiting L5 confirmed types — strategy is wired (sub-knob on) but L5 fingerprint discovery is off (WORMBASE_FINGERPRINT_DISCOVERY_ENABLED unset). Enable L5 AND confirm at least one semantic type on a column for this strategy to start proposing checks."
        : "Disabled — requires WORMBASE_QUALITY_DISCOVERY_ENABLED=true AND WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED=true to wire the L5→L7 cross-axis chain (4th cross-axis chain after L4→L3, L6→L5, L8→L5).",
    },
  ];
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  isTruthy,
  mapRow,
  _composeQualityCheckFilter,
};
