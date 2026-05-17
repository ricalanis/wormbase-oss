/**
 * /lake/column-classification read-side accessors — L6 Sub-wave D (2026-06-06).
 *
 * Reads the ``projection_column_classifications`` table (v025) populated
 * by the L6 Compounding axis (Sub-wave B's composite classifier built on
 * ``LakeLoopComposite[ProposedColumnClassification]`` and reading L5's
 * confirmed semantic types via ``ConfirmedSemanticTypeReader``).
 * One row per ``(company_id, classification_id)`` with state ∈
 * {proposed, confirmed, rejected}.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise — the page renders an empty state in both cases.
 * We never substitute fixtures.
 *
 * L6 is the 5th lake-side axis AND the 2nd cross-axis chain (after
 * L4→L3); the strategy status banner reads BOTH the L6 env knobs AND
 * the count of L5 ``confirmed`` semantic types for the tenant. The
 * ``semantic_type`` strategy is honest about its L5 dependency:
 *
 *   * L6 off                            → ``disabled``
 *   * L6 on, L5 off                     → ``configured · L5-disabled``
 *   * L6 on, L5 on, 0 confirmed types   → ``configured · awaiting-L5-types``
 *   * L6 on, L5 on, ≥1 confirmed type   → ``productive · L5-dependent`` (with count)
 *
 * ``naming_pattern`` is productive whenever L6 is enabled (regex over
 * bare names — no upstream dependency). The banner expands to surface
 * the regex coverage list per Sub-wave C handoff concern #1.
 *
 * ``domain_default`` has 3 postures: disabled / configured ·
 * awaiting-domain-pack / productive · domain-pack-dependent. The
 * productive note carries the LedgerDomainDefaultReader rationale per
 * Sub-wave C handoff concern #3 (alphabetically-first domain wins at
 * 0.60 confidence; admin should override).
 *
 * Sub-wave C handoff concerns honored:
 *
 *   * #1 naming_pattern coverage surfaced verbatim in the banner.
 *   * #2 min_confidence env knob is read but documented as not-yet-wired
 *     as a promotion filter (future enhancement; note in L6 close-out).
 *   * #3 domain_default rationale + 0.60 confidence explained in the
 *     banner so the operator understands the baseline.
 *   * #4 domain_id in evidence is the alphabetical pick, rendered
 *     accurately — not labelled "table-specific".
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** 5-value strict ``ClassificationLevel`` Literal from the ledger
 *  payload. Pinned here so the dashboard stays in lock-step with the
 *  ledger schema — adding a new level requires updating this union (a
 *  load-bearing compile error). Same 5 canonical levels per CLAUDE.md
 *  §"Ledger-native governance". */
export type ClassificationLevel =
  | "public"
  | "internal"
  | "confidential"
  | "pii"
  | "regulated";

/** One of the 3 inference strategies. */
export type ColumnClassificationStrategy =
  | "semantic_type"
  | "naming_pattern"
  | "domain_default";

/** One row in the /lake/column-classification page table. */
export interface ColumnClassificationRow {
  /** Deterministic hash over (table_id, column, classification_level, strategy). */
  classificationId: string;
  /** UUID of the catalog table the column lives in. */
  tableId: string;
  /** Column name. */
  column: string;
  /** Strict 5-value Literal enum from the ledger payload. */
  classificationLevel: ClassificationLevel;
  /**
   * L5 semantic type that drove this classification, when applicable.
   * ``null`` for non-semantic-type strategies (``naming_pattern`` /
   * ``domain_default``). When set, the dashboard renders a
   * "view L5 semantic type →" cross-axis link.
   */
  upstreamSemanticTypeId: string | null;
  /** Confidence float in [0.0, 1.0]. */
  confidence: number;
  /** Strategy that produced (or last-updated) the proposal. */
  strategy: ColumnClassificationStrategy;
  /** Human-readable explanation rendered on the row detail panel. */
  reasoning: string;
  /** Structured evidence dict surfaced verbatim on the detail panel
   *  (e.g. ``{"semantic_type": "pii_ssn", "regex_hit": true}``). */
  evidence: Record<string, unknown>;
  /** Current state — ``"proposed"`` | ``"confirmed"`` | ``"rejected"``. */
  state: "proposed" | "confirmed" | "rejected";
  /** ISO-8601 timestamp the state last changed. */
  stateChangedAt: string;
  /** Person UUID that last changed state; ``null`` while in proposed. */
  stateChangedBy: string | null;
}

/** Per-strategy productivity signal surfaced by the status banner. */
export interface ColumnClassificationStrategyStatus {
  /** Strategy name (matches the ledger ``strategy`` field convention). */
  strategy: ColumnClassificationStrategy;
  /** True when the strategy is wired by the boot path. */
  configured: boolean;
  /** True when the strategy can produce proposals today against this tenant. */
  productive: boolean;
  /**
   * Short doc-string surfaced in the banner. Distinguishes the postures:
   *   * semantic_type:  productive · L5-dependent / configured ·
   *                     awaiting-L5-types / configured · L5-disabled /
   *                     disabled
   *   * naming_pattern: productive (with pattern list) / disabled
   *   * domain_default: productive · domain-pack-dependent (with
   *                     rationale) / configured · awaiting-domain-pack /
   *                     disabled
   */
  note: string;
  /**
   * Honest status banner badge keyword. Mirrors :class:`CapabilityStatus`
   * values so the page can drop straight into the shared
   * ``CapabilityBadges`` component.
   */
  badge: "production" | "configured-stubbed" | "disabled";
  /** Optional override label for the badge, e.g.
   *  ``productive · L5-dependent`` or
   *  ``configured · awaiting-L5-types``. */
  badgeLabelOverride?: string;
}

/**
 * Per-page filter for /lake/column-classification (2026-05-16).
 *
 * Two filter axes, both optional:
 *
 *   * ``upstreamSemanticTypeId`` — consumer-page filter from the L5↦L6
 *     reverse-arc badge (R2) on the producer-side /lake/semantic-types
 *     page. Narrows to many classifications derived from one upstream
 *     L5 semantic type.
 *
 *   * ``classificationId`` — producer-side primary-key deep-link
 *     filter (2026-05-16 producer-side bundle). Surfaces the
 *     ``?classification_id=<id>`` URL param landed on L4 row's
 *     "view L6 classification" link. Narrows to a single L6
 *     classification row.
 *
 * Honest empty when no rows match either predicate.
 */
export interface ColumnClassificationFilter {
  upstreamSemanticTypeId?: string;
  classificationId?: string;
}

/**
 * L5-dependency probe summary surfaced by the dependency banner.
 * Mirrors :class:`L3DependencyState` from L4's surface. Surfaced when
 * L6 is enabled but L5 has zero confirmed types — operators need to
 * understand why the ``semantic_type`` strategy is wired but quiet.
 */
export interface L5DependencyState {
  /** True iff ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` is truthy. */
  l5Enabled: boolean;
  /** Number of ``confirmed`` ``projection_semantic_types`` rows for this tenant. */
  confirmedSemanticTypeCount: number;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface ColumnClassificationQueryRow extends Record<string, unknown> {
  classification_id: string;
  table_id: string;
  column: string;
  classification_level: string;
  upstream_semantic_type_id: string | null;
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

function mapRow(r: ColumnClassificationQueryRow): ColumnClassificationRow {
  return {
    classificationId: r.classification_id,
    tableId: r.table_id,
    column: r.column,
    classificationLevel: r.classification_level as ClassificationLevel,
    upstreamSemanticTypeId: r.upstream_semantic_type_id,
    confidence: toFloat(r.confidence),
    strategy: r.strategy as ColumnClassificationStrategy,
    reasoning: r.reasoning,
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`ColumnClassificationFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * Currently a single optional predicate (``upstreamSemanticTypeId``
 * → first-class column). Shaped to mirror
 * :func:`_composeSchemaImpactFilter` for symmetry across the bundle.
 *
 * ``nextParam`` is the 1-based index for the next placeholder. Returns
 * the fragment to append after an existing WHERE-clause (predicate
 * starts with ``AND ``) and the in-order parameter values. Returns
 * ``{ where: "", values: [] }`` when the filter is undefined or empty.
 */
function _composeColumnClassificationFilter(
  filter: ColumnClassificationFilter | undefined,
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

  if (filter.classificationId) {
    predicates.push(`AND classification_id = $${p}`);
    values.push(filter.classificationId);
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
 * Fetch every proposed (i.e. not-yet-confirmed-or-rejected) column-
 * classification proposal for a tenant, newest first. The page's
 * "Pending Proposals" section renders these with Confirm/Reject
 * actions for admins.
 *
 * Optional ``filter`` narrows the result set to rows derived from a
 * specific upstream L5 semantic type. Honest empty when filter
 * predicates match zero rows.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state.
 */
export async function getProposedColumnClassifications(
  companyId: string,
  opts: { limit?: number; filter?: ColumnClassificationFilter } = {},
): Promise<ColumnClassificationRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeColumnClassificationFilter(opts.filter, 2);

  // ``column`` is a Postgres reserved word — always double-quoted on
  // the wire. SQLite preserves the bare identifier but accepts the
  // quoted form too; we use the quoted form universally for
  // portability.
  const sql = `
    SELECT
      classification_id,
      table_id,
      "column" AS column,
      classification_level,
      upstream_semantic_type_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_column_classifications
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, classification_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<ColumnClassificationQueryRow>(sql, [
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
 * Fetch every confirmed column-classification proposal for a tenant.
 * The page's confirmed section renders these as a table; clicking
 * expands the evidence + reasoning panel.
 *
 * Optional ``filter`` mirrors :func:`getProposedColumnClassifications`.
 */
export async function getConfirmedColumnClassifications(
  companyId: string,
  opts: { limit?: number; filter?: ColumnClassificationFilter } = {},
): Promise<ColumnClassificationRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeColumnClassificationFilter(opts.filter, 2);

  const sql = `
    SELECT
      classification_id,
      table_id,
      "column" AS column,
      classification_level,
      upstream_semantic_type_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_column_classifications
    WHERE company_id = $1
      AND state = 'confirmed'${where}
    ORDER BY state_changed_at DESC, classification_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<ColumnClassificationQueryRow>(sql, [
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
 * Fetch rejected column-classification proposals in the last ``days``
 * (default 30) for strategy-tuning audit. Surfaced collapsed by
 * default.
 */
export async function getRejectedColumnClassifications(
  companyId: string,
  opts: {
    days?: number;
    limit?: number;
    filter?: ColumnClassificationFilter;
  } = {},
): Promise<ColumnClassificationRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeColumnClassificationFilter(opts.filter, 3);

  const sql = `
    SELECT
      classification_id,
      table_id,
      "column" AS column,
      classification_level,
      upstream_semantic_type_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_column_classifications
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, classification_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<ColumnClassificationQueryRow>(sql, [
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
 * classification_id). Used by the detail panel + the click-through
 * audit view.
 */
export async function getColumnClassificationEvidence(
  companyId: string,
  classificationId: string,
): Promise<ColumnClassificationRow | null> {
  if (!postgresEnabled()) return null;

  const sql = `
    SELECT
      classification_id,
      table_id,
      "column" AS column,
      classification_level,
      upstream_semantic_type_id,
      confidence,
      strategy,
      reasoning,
      evidence,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_column_classifications
    WHERE company_id = $1
      AND classification_id = $2
    LIMIT 1
  `;

  try {
    const res = await pgQuery<ColumnClassificationQueryRow>(sql, [
      companyId,
      classificationId,
    ]);
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
 * types available" banner per Sub-wave C handoff concern (mirrors L4's
 * L3-dependency banner pattern).
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
 * banner on ``/lake/column-classification``. Reads the L6 env knobs +
 * the L5 confirmed-type count probe (the 2nd cross-axis chain).
 *
 * Strategy posture per L6 design §5:
 *
 *   * ``semantic_type`` — productive when L6 on AND L5 on AND L5 has
 *     ≥1 confirmed type for this tenant. Three honest "almost-but-not-
 *     yet" postures otherwise (L5-disabled / awaiting-L5-types /
 *     disabled). When productive, the strategy reads L5's
 *     ``projection_semantic_types`` via the
 *     ``ConfirmedSemanticTypeReader`` Protocol and maps each type to a
 *     classification level (e.g. ``pii_ssn`` → ``regulated``).
 *
 *   * ``naming_pattern`` — productive whenever L6 is enabled. Regex
 *     coverage list surfaced verbatim in the note per Sub-wave C
 *     handoff concern #1: ``*_secret/password/api_key/token`` →
 *     confidential (0.95); ``*_ssn/_tax_id`` → regulated (0.95);
 *     ``*_internal_*`` → internal (0.80); ``*_public_*`` → public
 *     (0.85).
 *
 *   * ``domain_default`` — productive when L6 on AND a domain pack is
 *     selected. The LedgerDomainDefaultReader baseline is honest:
 *     alphabetically-first registered domain wins at 0.60 confidence;
 *     admins should override with naming_pattern / semantic_type
 *     signals (per Sub-wave C handoff concern #3). ``disabled`` when
 *     L6 master switch is off; ``configured · awaiting-domain-pack``
 *     when L6 on but no domain pack registered yet.
 *
 * Tenant-isolation: this reader composes env-knob state (process-global)
 * with a per-tenant L5 confirmed-type count + domain-pack presence
 * probe. The L6 surface itself is env-gated.
 */
export async function getColumnClassificationStrategyStatus(
  companyId: string,
): Promise<ColumnClassificationStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED,
  );
  const semanticTypeEnabled =
    discoveryEnabled &&
    isTruthy(
      process.env.WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED,
    );
  const domainDefaultEnabled =
    discoveryEnabled &&
    isTruthy(
      process.env.WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED,
    );

  // semantic_type — the cross-axis chain to L5. Mirrors L4's
  // lineage_edge → L3 posture matrix.
  const l5State = await getL5DependencyState(companyId);
  let semanticTypeBadge: ColumnClassificationStrategyStatus["badge"];
  let semanticTypeOverride: string | undefined;
  let semanticTypeNote: string;
  let semanticTypeProductive = false;
  if (!semanticTypeEnabled) {
    semanticTypeBadge = "disabled";
    semanticTypeNote =
      "Disabled — set WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true and WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED=true to wire the cross-axis chain into L5.";
  } else if (!l5State.l5Enabled) {
    // L6 on, L5 off — strategy is wired but its upstream (L5
    // ConfirmedSemanticTypeReader) has nothing to read.
    semanticTypeBadge = "configured-stubbed";
    semanticTypeOverride = "configured · L5-disabled";
    semanticTypeNote =
      "Configured but L5 is disabled — the semantic_type strategy depends on L5's confirmed-semantic-type projection. Set WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true and confirm at least one semantic type in /lake/semantic-types to wake the strategy.";
  } else if (l5State.confirmedSemanticTypeCount === 0) {
    semanticTypeBadge = "configured-stubbed";
    semanticTypeOverride = "configured · awaiting-L5-types";
    semanticTypeNote =
      "Configured but awaiting L5 confirmations — the strategy is wired against L5's projection but no confirmed semantic types exist for this tenant yet. Confirm a type in /lake/semantic-types and the strategy graduates to productive automatically.";
  } else {
    semanticTypeBadge = "production";
    semanticTypeOverride = "productive · L5-dependent";
    semanticTypeProductive = true;
    const n = l5State.confirmedSemanticTypeCount;
    semanticTypeNote = `Productive — reading ${n} confirmed L5 semantic type${n === 1 ? "" : "s"} for this tenant. Maps each confirmed type to a governance classification (e.g. pii_ssn → regulated, email → internal). Cross-axis chain populates upstream_semantic_type_id on every proposal, enabling the "view L5 semantic type →" link on each row.`;
  }

  // naming_pattern — productive whenever L6 is on. Surface the regex
  // coverage list per handoff concern #1.
  const namingPatternNote = discoveryEnabled
    ? "Productive — regex over column names against the 4-pattern coverage list: " +
      "`*_secret` / `*_password` / `*_api_key` / `*_token` → confidential (0.95); " +
      "`*_ssn` / `*_tax_id` → regulated (0.95); " +
      "`*_internal_*` → internal (0.80); " +
      "`*_public_*` → public (0.85). No upstream dependency — operates on bare catalog names."
    : "Disabled — set WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true to wire the L6 inference axis.";

  // domain_default — productive when L6 on AND domain pack present.
  // Surface the LedgerDomainDefaultReader rationale per handoff
  // concern #3.
  const domainPackPresent = await _hasDomainPack(companyId);
  let domainDefaultBadge: ColumnClassificationStrategyStatus["badge"];
  let domainDefaultOverride: string | undefined;
  let domainDefaultNote: string;
  let domainDefaultProductive = false;
  if (!domainDefaultEnabled) {
    domainDefaultBadge = "disabled";
    domainDefaultNote =
      "Disabled — set WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true and WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED=true to wire the domain-pack fallback strategy.";
  } else if (!domainPackPresent) {
    domainDefaultBadge = "configured-stubbed";
    domainDefaultOverride = "configured · awaiting-domain-pack";
    domainDefaultNote =
      "Configured but no domain pack registered — the strategy is wired against the per-domain default classification but no domain has been registered for this tenant yet. Pick a domain pack in /onboard (Tier 2) to wake the strategy.";
  } else {
    domainDefaultBadge = "production";
    domainDefaultOverride = "productive · domain-pack-dependent";
    domainDefaultProductive = true;
    domainDefaultNote =
      "Productive — domain pack default at 0.60 baseline confidence. The LedgerDomainDefaultReader honest baseline picks the alphabetically-first registered domain when multiple compete (no per-table mapping yet); admins should override with naming_pattern or semantic_type signals (higher confidence). Per-row evidence carries the picked domain_id — rendered accurately, not as a table-specific mapping.";
  }

  return [
    {
      strategy: "semantic_type",
      configured: semanticTypeEnabled,
      productive: semanticTypeProductive,
      badge: semanticTypeBadge,
      badgeLabelOverride: semanticTypeOverride,
      note: semanticTypeNote,
    },
    {
      strategy: "naming_pattern",
      configured: discoveryEnabled,
      productive: discoveryEnabled,
      badge: discoveryEnabled ? "production" : "disabled",
      note: namingPatternNote,
    },
    {
      strategy: "domain_default",
      configured: domainDefaultEnabled,
      productive: domainDefaultProductive,
      badge: domainDefaultBadge,
      badgeLabelOverride: domainDefaultOverride,
      note: domainDefaultNote,
    },
  ];
}

/**
 * Probe whether the tenant has any registered domain. Used to drive
 * the domain_default strategy posture. Counts execute entries of
 * ``emit_domain_registered`` directly off the ledger (the same source
 * ``getDomains`` reads from — no separate ``projection_domains``
 * table exists today). Honest: returns false when the query throws.
 */
async function _hasDomainPack(companyId: string): Promise<boolean> {
  if (!postgresEnabled()) return false;
  const sql = `
    SELECT COUNT(DISTINCT payload->'args'->>'id')::int AS n
    FROM ledger
    WHERE company_id = $1
      AND kind = 'execute'
      AND payload->>'tool' = 'emit_domain_registered'
      AND payload->'args'->>'id' IS NOT NULL
  `;
  try {
    const res = await pgQuery<{ n: number | string }>(sql, [companyId]);
    if (res.rows.length === 0) return false;
    const raw = res.rows[0].n;
    const parsed =
      typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(parsed) && parsed > 0;
  } catch {
    return false;
  }
}

// ─── L4↦L6 reverse-arc enrichment (Recipe Addendum #3) ──────────────────

/**
 * Reverse-arc lookup map: ``classificationId → downstream-impact count``.
 */
export type SchemaImpactCountByClassificationMap = Record<string, number>;

/**
 * R5 L4↦L6: count L4 schema-evolution-impact rows per L6
 * ``classification_id`` for a tenant. Reads ``projection_schema_impacts``
 * (v023). The ``upstream_classification_id`` link lives inside the
 * JSON ``evidence`` column (per L6→L4 close-out: GovernanceImpactStrategy
 * writes evidence dict — see agent-gateway/schema_impact/strategies.py
 * line 729), so the SQL uses ``evidence->>'upstream_classification_id'``
 * accessor and filters out NULL paths.
 *
 * State filter: ``state IN ('proposed', 'confirmed')`` — rejected
 * impacts excluded. Matches the L4↦L2 Half B precedent.
 *
 * No env knob: unconditional cross-axis enrichment per Recipe
 * Addendum #3. When the L4 projection is empty or carries no
 * classification-derived impacts, returns ``{}`` and the L6 row
 * renders no badge. Honest by construction.
 *
 * Tenant-scoped via ``companyId``. Multi-tenant safe — no
 * cross-tenant data leaks.
 */
export async function getSchemaImpactCountByClassification(
  companyId: string,
): Promise<SchemaImpactCountByClassificationMap> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      (evidence->>'upstream_classification_id') AS upstream_classification_id,
      COUNT(*)::int AS n
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
      AND evidence ? 'upstream_classification_id'
      AND (evidence->>'upstream_classification_id') IS NOT NULL
    GROUP BY (evidence->>'upstream_classification_id')
  `;

  try {
    const res = await pgQuery<{
      upstream_classification_id: string;
      n: number | string;
    }>(sql, [companyId]);
    const out: SchemaImpactCountByClassificationMap = {};
    for (const row of res.rows) {
      const n =
        typeof row.n === "number"
          ? row.n
          : Number.parseInt(String(row.n), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      out[row.upstream_classification_id] = n;
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
  _composeColumnClassificationFilter,
};
