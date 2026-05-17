/**
 * /lake/catalog-drift read-side accessors — L2 Sub-wave D (2026-06-09).
 *
 * Reads the ``projection_catalog_drifts`` table (v028) populated by
 * the L2 Compounding axis (Sub-wave B's composite catalog-drift
 * service built on ``LakeLoopComposite[ProposedCatalogDrift]`` — the
 * 5th day-one consumer of that primitive after L5/L6/L8/L1). One row
 * per ``(company_id, drift_id)`` with state ∈
 * {proposed, acknowledged, rejected}.
 *
 * L2 is the **8th and FINAL** lake-side axis in this wave generation.
 * Unlike L4→L3 / L6→L5 / L8→L5, L2 does NOT add a peer-L-axis cross-
 * axis chain — its three strategies (table_set / column_set /
 * column_type) read a lightweight **catalog-mirror substrate** event
 * (``external_catalog_imported``) through the scoped
 * ``CatalogSnapshotReader`` Protocol, NOT another L-axis's confirmed
 * projection. Cross-axis chain count stays at 3 per spec §3.4.
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise — the page renders an empty state in both cases.
 * We never substitute fixtures (per CLAUDE.md §9).
 *
 * Strategy posture per spec §4.7 + Sub-wave C handoff concerns:
 *
 *   * ``table_set`` — shape-productive day-1 (catalog-mirror payload
 *     already carries per-table data via added_table_ids/removed_
 *     table_ids tuples). Today's `LedgerCatalogSnapshotReader` returns
 *     `()` for current.tables because the existing payload only
 *     carries *deltas*, not absolute lists. Banner reflects this
 *     honestly:
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, no usable snapshot pairs landed yet → ``configured · awaiting-richer-catalog-substrate``
 *     - both ON, snapshot pairs present → ``productive · table-diff-dependent``
 *
 *   * ``column_set`` — empty-upstream until catalog-mirror Wave 2
 *     lands per-column ingest (today `list_columns` returns `()`).
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, columns=() everywhere → ``configured · empty-upstream``
 *     - both ON, columns present → ``productive · column-diff-dependent``
 *
 *   * ``column_type`` — same per-column data dependency.
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, types unknown → ``configured · empty-upstream``
 *     - both ON, types present → ``productive · type-diff-dependent``
 *
 * The composite + body keys: Sub-wave C handoff concern #4 ships the
 * body in both `driftId` (camelCase) and `drift_id` (snake_case).
 * Dashboard server actions emit snake_case `drift_id` (matches ledger
 * + endpoint URL); accessor reads only need to map column rows.
 */

import { getCatalogTableImportCount } from "./catalog-mirror";
import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** L2's three inference strategies. Mirrors
 *  :data:`wormbase_agent_gateway.catalog_drift.protocol.CatalogDriftStrategyKind`. */
export type CatalogDriftStrategy =
  | "table_set"
  | "column_set"
  | "column_type";

/** L2's strict 5-value drift kind enum. Mirrors
 *  :data:`wormbase_ledger.entries.CatalogDriftKind`. */
export type CatalogDriftKind =
  | "table_added"
  | "table_removed"
  | "column_added"
  | "column_removed"
  | "column_type_changed";

/** One row in the /lake/catalog-drift page table. */
export interface CatalogDriftRow {
  /** Deterministic SHA-256(:32 hex) hash over the canonical
   *  ``(source_id, table_id, column, drift_kind, before, after)``
   *  tuple. */
  driftId: string;
  /** Source UUID/identifier that the drift was observed on. */
  sourceId: string;
  /** Table identifier (e.g. fully-qualified table name) inside
   *  ``sourceId``. Non-empty. */
  tableId: string;
  /** Column name when the drift_kind targets a column; ``null`` for
   *  table_added/table_removed. */
  column: string | null;
  /** One of the strict 5-value Literal from
   *  :data:`wormbase_ledger.entries.CatalogDriftKind`. */
  driftKind: CatalogDriftKind;
  /** Prior value — ``null`` for *_added; carries prior descriptor
   *  for *_removed; carries prior type dict for column_type_changed. */
  before: Record<string, unknown> | null;
  /** New value — ``null`` for *_removed; carries new descriptor for
   *  *_added; carries new type dict for column_type_changed. */
  after: Record<string, unknown> | null;
  /** Strategy that proposed this drift. */
  strategy: CatalogDriftStrategy;
  /** Human-readable explanation. */
  reasoning: string;
  /** Confidence float in [0.0, 1.0]. */
  confidence: number;
  /** Strategy-specific structured evidence dict (preserved verbatim
   *  through the fold). */
  evidence: Record<string, unknown>;
  /** Current state — ``"proposed"`` | ``"acknowledged"`` |
   *  ``"rejected"``. Note: L2 uses ``"acknowledged"`` where
   *  L3/L4/L5/L6/L7/L8 use ``"confirmed"`` and L1 uses ``"promoted"``
   *  — see spec §1 for rationale on the read-only-disposition naming. */
  state: "proposed" | "acknowledged" | "rejected";
  /** ISO-8601 timestamp the state last changed. */
  stateChangedAt: string;
  /** Person UUID that last changed state; ``null`` while in proposed. */
  stateChangedBy: string | null;
}

/**
 * Per-page filter for /lake/catalog-drift (2026-05-16).
 *
 * Producer-side deep-link filter — narrows the rendered tables to a
 * single L2 drift identified by its primary-key ``driftId``. Honored
 * by every projection accessor below. Surfaces the
 * ``?drift_id=<id>`` URL param landed on producer pages, closing the
 * L4↦L2 evidence-link asymmetry (the L4 row gains a "view L2 drift"
 * link in the producer-side bundle).
 */
export interface CatalogDriftFilter {
  driftId?: string;
}

/** Per-strategy productivity signal surfaced by the status banner. */
export interface CatalogDriftStrategyStatus {
  strategy: CatalogDriftStrategy;
  /** True when the strategy is wired by the boot path (master + sub-knob on). */
  configured: boolean;
  /** True when the strategy can produce proposals today against this tenant. */
  productive: boolean;
  /** Short doc-string surfaced in the banner. */
  note: string;
  /** Honest status badge keyword. */
  badge: "production" | "configured-stubbed" | "disabled";
  /** Optional override label for the badge, e.g.
   *  ``productive · table-diff-dependent`` or
   *  ``configured · awaiting-richer-catalog-substrate``. */
  badgeLabelOverride?: string;
}

/**
 * Upstream gauges for the strategy banner. Reads count of distinct
 * sources with snapshot pairs (i.e. >=2 external_catalog_imported
 * entries) scoped by ``company_id`` so the banner reflects the live
 * tenant state, not a process-global env-knob snapshot.
 *
 * Today (Wave 1) per-column ingest is not landed, so the column_set
 * and column_type strategies are honest empty-upstream regardless of
 * the snapshot-pair count.
 */
export interface CatalogDriftUpstreamState {
  /** Count of distinct sources with at least 2
   *  ``external_catalog_imported`` snapshots in the tenant (drives
   *  ``table_set`` productivity). When zero, the table_set strategy
   *  surfaces as ``configured · awaiting-richer-catalog-substrate``. */
  sourcesWithSnapshotPair: number;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface CatalogDriftQueryRow extends Record<string, unknown> {
  drift_id: string;
  source_id: string;
  table_id: string;
  column: string | null;
  drift_kind: CatalogDriftKind;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  strategy: string;
  reasoning: string;
  confidence: number | string;
  evidence: Record<string, unknown> | null;
  state: "proposed" | "acknowledged" | "rejected";
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

function mapRow(r: CatalogDriftQueryRow): CatalogDriftRow {
  return {
    driftId: r.drift_id,
    sourceId: r.source_id,
    tableId: r.table_id,
    column: r.column,
    driftKind: r.drift_kind,
    before: r.before,
    after: r.after,
    strategy: r.strategy as CatalogDriftStrategy,
    reasoning: r.reasoning,
    confidence: toFloat(r.confidence),
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`CatalogDriftFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * Currently a single optional predicate (``driftId`` → primary-key
 * column).
 */
function _composeCatalogDriftFilter(
  filter: CatalogDriftFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.driftId) {
    predicates.push(`AND drift_id = $${p}`);
    values.push(filter.driftId);
    p += 1;
  }

  return {
    where:
      predicates.length === 0 ? "" : "\n      " + predicates.join("\n      "),
    values,
  };
}

async function _countSingle(sql: string, params: unknown[]): Promise<number> {
  try {
    const res = await pgQuery<{ n: number | string }>(sql, params);
    if (res.rows.length === 0) return 0;
    const raw = res.rows[0].n;
    const parsed =
      typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(parsed) ? parsed : 0;
  } catch {
    return 0;
  }
}

// ─── Postgres-bound accessors ─────────────────────────────────────────────

/**
 * Common SELECT projection for catalog-drift rows. ``"column"`` is a
 * reserved SQL keyword on most dialects, so it is quoted explicitly.
 */
const _SELECT_COLUMNS = `
  drift_id,
  source_id,
  table_id,
  "column",
  drift_kind,
  before,
  after,
  strategy,
  reasoning,
  confidence,
  evidence,
  state,
  state_changed_at,
  state_changed_by
`;

/**
 * Fetch every proposed (not-yet-acknowledged-or-rejected) catalog
 * drift for a tenant, newest first.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state. No
 * FIXTURE return per CLAUDE.md §9.
 */
export async function getProposedCatalogDrifts(
  companyId: string,
  opts: { limit?: number; filter?: CatalogDriftFilter } = {},
): Promise<CatalogDriftRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeCatalogDriftFilter(opts.filter, 2);

  const sql = `
    SELECT ${_SELECT_COLUMNS}
    FROM projection_catalog_drifts
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, drift_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<CatalogDriftQueryRow>(sql, [
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
 * Fetch every acknowledged catalog drift for a tenant. Surfaced in a
 * separate section so admins can audit what already got through.
 */
export async function getAcknowledgedCatalogDrifts(
  companyId: string,
  opts: { limit?: number; filter?: CatalogDriftFilter } = {},
): Promise<CatalogDriftRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeCatalogDriftFilter(opts.filter, 2);

  const sql = `
    SELECT ${_SELECT_COLUMNS}
    FROM projection_catalog_drifts
    WHERE company_id = $1
      AND state = 'acknowledged'${where}
    ORDER BY state_changed_at DESC, drift_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<CatalogDriftQueryRow>(sql, [
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
 * Fetch rejected catalog drifts in the last ``days`` (default 30)
 * for strategy-tuning audit. Collapsed by default in the surface.
 */
export async function getRejectedCatalogDrifts(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: CatalogDriftFilter } = {},
): Promise<CatalogDriftRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeCatalogDriftFilter(opts.filter, 3);

  const sql = `
    SELECT ${_SELECT_COLUMNS}
    FROM projection_catalog_drifts
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, drift_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<CatalogDriftQueryRow>(sql, [
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
 * Probe the upstream state for the strategy banner. Counts distinct
 * sources with at least 2 ``external_catalog_imported`` entries in
 * the tenant (i.e. enough snapshot history for a drift to be
 * detectable). Today's table_set strategy productivity depends on
 * this; the column_set + column_type strategies depend on per-column
 * ingest landing in catalog-mirror Wave 2.
 *
 * Returns zero counts when DATABASE_URL is unset, the query throws,
 * or the upstream tables are empty — strategies surface as
 * ``configured · awaiting-*`` rather than ``productive``.
 *
 * The probe uses the ``ledger_entries`` table (the canonical write
 * surface for ``external_catalog_imported``) rather than an
 * external-catalog projection, because the catalog-mirror Wave 1
 * substrate is the ledger entry itself — there is no separate
 * projection_external_catalog_imports table today.
 */
export async function getCatalogDriftUpstreamState(
  companyId: string,
): Promise<CatalogDriftUpstreamState> {
  if (!postgresEnabled()) {
    return { sourcesWithSnapshotPair: 0 };
  }
  const sql = `
    SELECT COUNT(*)::int AS n
    FROM (
      SELECT (payload->>'source_id') AS source_id
      FROM ledger_entries
      WHERE company_id = $1
        AND kind = 'external_catalog_imported'
        AND payload ? 'source_id'
      GROUP BY (payload->>'source_id')
      HAVING COUNT(*) >= 2
    ) AS sources_with_pair
  `;
  const n = await _countSingle(sql, [companyId]);
  return { sourcesWithSnapshotPair: n };
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the
 * /lake/catalog-drift strategy banner. Reads the five L2 env knobs +
 * the per-tenant catalog-mirror Wave 2 substrate count.
 *
 * Strategy posture per spec §4.7 — UPDATED 2026-06-10 for Wave 2:
 *
 * All three strategies (``table_set`` / ``column_set`` /
 * ``column_type``) now share the same 3-state matrix keyed on the
 * Wave 2 substrate (``projection_catalog_tables``):
 *
 *   * master OFF or sub-knob OFF → ``disabled``
 *   * both ON, ``projection_catalog_tables`` empty for this tenant →
 *     ``configured · awaiting-per-table-entries`` (Wave 2 substrate
 *     ready; the connector that imported the catalog hasn't landed a
 *     per-table entry yet — usually means the extractor isn't wired
 *     for that connector kind in
 *     ``apps/worm-core/src/wormbase_core/catalog_column_extractors.py``)
 *   * both ON, ≥1 ``catalog_table_imported`` entry exists →
 *     ``productive · per-connector``
 *     (csv_local/dbt/snowflake emit per-table entries today; other
 *     connector kinds land entries with ``columns=()`` per the
 *     honest-empty-upstream doctrine until an extractor is registered)
 *
 * The Sub-wave A/B substrate (``catalog_table_imported`` PEVR +
 * ``projection_catalog_tables``) is the productivity unblock — the
 * banner posture now flips on the presence of folded per-table
 * entries, not on the older ``external_catalog_imported`` snapshot
 * pairs which only carried summary counts. The original
 * ``getCatalogDriftUpstreamState`` accessor is preserved for
 * backwards-compatible callers but is no longer the productivity
 * gate.
 *
 * Master knob = ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED``.
 * Sub-knobs:
 *   - ``WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED``
 *   - ``WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED``
 *   - ``WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED``
 *
 * Tenant-isolation: composes env-knob state (process-global) with
 * the per-tenant ``getCatalogTableImportCount`` probe. The L2 surface
 * itself is env-gated; per-tenant productivity is a function of
 * Wave 2 substrate population.
 */
export async function getCatalogDriftStrategyStatus(
  companyId: string,
): Promise<CatalogDriftStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED,
  );
  const tableSetEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED);
  const columnSetEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED);
  const columnTypeEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED);

  // Short-circuit the substrate probe when ALL three strategy sub-
  // knobs are off — avoids a pointless tenant query when the entire
  // L2 surface is disabled. The probe is cheap (single COUNT(*)),
  // but we only need to issue it when at least one strategy might
  // graduate to productive.
  const anyStrategyEnabled =
    tableSetEnabled || columnSetEnabled || columnTypeEnabled;
  let catalogTableImportCount = 0;
  if (anyStrategyEnabled) {
    catalogTableImportCount = await getCatalogTableImportCount(companyId);
  }
  const substrateReady = catalogTableImportCount > 0;

  // Shared sub-knob → 3-state matrix builder. Same posture across
  // all three strategies — the Wave 2 substrate unblocks them
  // uniformly. Per-connector productivity (which extractor is wired)
  // is surfaced in the note, not in the badge enum.
  const buildPosture = (
    enabled: boolean,
    strategyName: string,
    strategyDesc: string,
    subKnob: string,
    waveTwoSubstrateNote: string,
  ): {
    badge: CatalogDriftStrategyStatus["badge"];
    override?: string;
    note: string;
    productive: boolean;
  } => {
    if (!enabled) {
      return {
        badge: "disabled",
        note: `Disabled — set WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true and ${subKnob}=true to wire ${strategyName}. ${strategyDesc}`,
        productive: false,
      };
    }
    if (!substrateReady) {
      return {
        badge: "configured-stubbed",
        override: "configured · awaiting-per-table-entries",
        note: `Configured — wired to the CatalogSnapshotReader Protocol AND the Wave 2 substrate (\`\`projection_catalog_tables\`\`) is ready, but no \`\`catalog_table_imported\`\` entries have been folded for this tenant yet. ${waveTwoSubstrateNote} Some connectors don't yet have a registered extractor — see \`\`apps/worm-core/src/wormbase_core/catalog_column_extractors.py\`\` for the catalog_column_extractors registry; csv_local is the first wired kind, dbt and snowflake land per-table entries via TableMeta.columns directly. Add an extractor for a new connector kind to graduate it without touching the Connector Protocol.`,
        productive: false,
      };
    }
    const n = catalogTableImportCount;
    return {
      badge: "production",
      override: "productive · per-connector",
      note: `Productive — reading ${n} folded \`\`catalog_table_imported\`\` entr${n === 1 ? "y" : "ies"} from \`\`projection_catalog_tables\`\` for this tenant. ${strategyDesc} csv_local / dbt / snowflake emit per-table entries today; opaque-secret connectors (stripe / salesforce / hubspot / gsheets / mcp:*) land entries with \`\`columns=()\`\` per the honest-empty-upstream doctrine — those rows still count as substrate population for \`\`table_set\`\` but contribute nothing to \`\`column_set\`\` / \`\`column_type\`\`. Add a connector-specific extractor to register the column extraction recipe for a new kind.`,
      productive: true,
    };
  };

  const tableSet = buildPosture(
    tableSetEnabled,
    "TableSetDriftStrategy",
    "The strategy diffs current vs baseline table lists per source_id and emits table_added / table_removed proposals at confidence 0.90.",
    "WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED",
    "The strategy needs at least one per-table `catalog_table_imported` entry to compute a table-set diff.",
  );

  const columnSet = buildPosture(
    columnSetEnabled,
    "ColumnSetDriftStrategy",
    "The strategy diffs current vs baseline column lists per (source_id, table_id) and emits column_added / column_removed proposals at confidence 0.90.",
    "WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED",
    "The strategy needs per-table entries with populated `columns` payloads — opaque-secret connectors land `columns=()` (honest-empty) until an extractor is registered.",
  );

  const columnType = buildPosture(
    columnTypeEnabled,
    "ColumnTypeDriftStrategy",
    "The strategy diffs current vs baseline column types per (source_id, table_id, column) and emits column_type_changed proposals at confidence 0.90.",
    "WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED",
    "The strategy needs per-table entries with populated `columns[].type` — csv_local emits `type=None` today (the L5 inference axis is responsible for type assignment); dbt and snowflake emit real types via TableMeta.columns.",
  );

  return [
    {
      strategy: "table_set",
      configured: tableSetEnabled,
      productive: tableSet.productive,
      badge: tableSet.badge,
      badgeLabelOverride: tableSet.override,
      note: tableSet.note,
    },
    {
      strategy: "column_set",
      configured: columnSetEnabled,
      productive: columnSet.productive,
      badge: columnSet.badge,
      badgeLabelOverride: columnSet.override,
      note: columnSet.note,
    },
    {
      strategy: "column_type",
      configured: columnTypeEnabled,
      productive: columnType.productive,
      badge: columnType.badge,
      badgeLabelOverride: columnType.override,
      note: columnType.note,
    },
  ];
}

// ─── L4↦L2 cross-axis enrichment (Half B — reverse direction) ────────────

/**
 * Map from "downstream-impact source key" → impact count, used by the
 * /lake/catalog-drift page to render a "↪ N downstream impacts" badge
 * per drift row.
 *
 * The L4↦L2 chain is the **7th cross-axis chain** and the **FIRST
 * bidirectional** chain. The forward arc (Half A) lives in the
 * worm-core agent-gateway construction wiring — L4's
 * AcknowledgedDriftImpactStrategy reads L2's acknowledged drifts to
 * elevate impact severity. THIS function powers the reverse arc
 * (Half B): the L2 dashboard reads L4's projection_schema_impacts
 * table to surface roll-up counts on the drift triage surface.
 *
 * Key shape: ``"<source_id>|<table_id>|<column-or-asterisk>"`` —
 * matches the L2 drift's tuple. ``column`` collapses to "*" for
 * table-level drifts (drift.column is null) since the L4 impact
 * surface is column-grain only and table-level drifts have no
 * direct downstream-impact rows.
 *
 * Returns an empty map (not null) when DATABASE_URL is unset, the
 * query throws, or the projection is empty — the caller treats the
 * empty map as "no badge to render on any row" (honest empty state).
 */
export type SchemaImpactCountKey = string;

/**
 * Build the cross-axis lookup key for a drift row's
 * ``(source_id, table_id, column)`` tuple.
 *
 * Column collapses to "*" for table-level drifts (drift.column is
 * null). Production accessors below mirror this collapse so the
 * map's key set is internally consistent.
 */
export function makeImpactCountKey(
  sourceId: string,
  tableId: string,
  column: string | null,
): SchemaImpactCountKey {
  return `${sourceId}|${tableId}|${column ?? "*"}`;
}

/**
 * Count L4 schema-evolution-impact rows per (source_id, src_table,
 * src_column) for a tenant. Reads ``projection_schema_impacts``
 * (v023) directly — same table the /lake/schema-impact surface
 * displays. State filter: state IN ('proposed', 'confirmed') —
 * rejected impacts are excluded from the badge count (they are
 * dispositions, not pending consequences).
 *
 * No env knob: this is unconditional cross-axis enrichment. When
 * the L4 projection is empty (e.g. master env knob OFF or no
 * impacts yet), the function returns an empty map; the dashboard
 * row renders no badge. Honest by construction.
 *
 * Tenant-scoped via ``companyId``. Multi-tenant safe — the SQL
 * filters by company_id; no cross-tenant data leaks.
 */
export async function getImpactCountByDriftSource(
  companyId: string,
): Promise<Record<SchemaImpactCountKey, number>> {
  if (!postgresEnabled()) return {};

  const sql = `
    SELECT
      source_id,
      src_table,
      src_column,
      COUNT(*)::int AS impact_count
    FROM projection_schema_impacts
    WHERE company_id = $1
      AND state IN ('proposed', 'confirmed')
    GROUP BY source_id, src_table, src_column
  `;

  try {
    const res = await pgQuery<{
      source_id: string;
      src_table: string;
      src_column: string;
      impact_count: number | string;
    }>(sql, [companyId]);
    const out: Record<SchemaImpactCountKey, number> = {};
    for (const row of res.rows) {
      const n =
        typeof row.impact_count === "number"
          ? row.impact_count
          : Number.parseInt(String(row.impact_count), 10);
      if (!Number.isFinite(n) || n <= 0) continue;
      // L4 impacts are column-grain only — the src_column is always
      // non-null on a proper impact row. For drift rows targeting
      // a column, this maps 1:1. Table-level drifts (drift.column
      // null) have no direct L4 impact mapping today; the key would
      // never match anyway (it'd be ``<src>|<table>|*`` and the
      // L4 row's column is always a real value).
      const key = makeImpactCountKey(
        row.source_id,
        row.src_table,
        row.src_column,
      );
      out[key] = n;
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
  _composeCatalogDriftFilter,
};
