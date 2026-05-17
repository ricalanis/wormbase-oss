/**
 * /lake/source-candidates read-side accessors — L1 Sub-wave D (2026-06-08).
 *
 * Reads the ``projection_source_candidates`` table (v027) populated by
 * the L1 Compounding axis (Sub-wave B's composite source-candidate
 * service built on ``LakeLoopComposite[ProposedSourceCandidate]`` — the
 * 4th day-one consumer of that primitive after L5/L6/L8). One row per
 * ``(company_id, candidate_id)`` with state ∈
 * {proposed, promoted, rejected}.
 *
 * L1 is the 7th lake-side axis. Unlike L4→L3 / L6→L5 / L8→L5, L1 does
 * **not** add a peer-L-axis cross-axis chain — its three strategies
 * read **lightweight platform projections** (``projection_sources``,
 * ``projection_kpi_nodes``, ``projection_conversations``) through
 * scoped Reader Protocols, NOT another L-axis's confirmed projection.
 * Cross-axis chain count stays at 3 per spec §4.6.
 *
 * There IS a sui-generis "downstream link" affordance: when an admin
 * promotes a candidate, the worm-core endpoint dual-writes — emits
 * ``source_candidate_promoted`` AND triggers the existing source-
 * builder to emit a downstream ``source_proposed``. The resulting
 * source-id is threaded back into the promote entry's
 * ``downstream_source_proposed_id`` field. The dashboard renders a
 * "→ source pipeline" link to ``/sources?id=<source_id>`` when set,
 * and a "promote succeeded but downstream pipeline did not fire —
 * investigate" advisory when NULL (per Sub-wave C handoff concern #1
 * on dual-write atomicity).
 *
 * Strategy: Postgres-first when DATABASE_URL is set; honest empty
 * fallback otherwise — the page renders an empty state in both cases.
 * We never substitute fixtures (per CLAUDE.md §9).
 *
 * Strategy posture per spec §4.7 (4-state for kpi_gap, 3-state for
 * channel_mention + complementarity):
 *
 *   * ``kpi_gap``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, ``projection_kpi_nodes`` empty → ``configured · awaiting-kpi-tree-population``
 *     - both ON, ≥1 KPI node → ``productive · KPI-dependent`` (with node count)
 *   * ``channel_mention``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, ``projection_conversations`` empty → ``configured · empty-upstream`` (awaiting silver-conversation messages)
 *     - both ON, ≥1 conversation row → ``productive · silver-dependent`` (with row count + 24h × 1000-cap note)
 *   * ``complementarity``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, 0 connected sources → ``configured · awaiting-first-source``
 *     - both ON, ≥1 connected source → ``productive · portfolio-dependent`` (with count)
 *
 * Sub-wave C handoff concerns honored:
 *
 *   * #1 Dual-write atomicity — ``downstream_source_proposed_id``
 *     surfaced honestly; NULL state renders the inline "investigate"
 *     advisory.
 *   * #2 ``KpiNodeRecord.domain_id = None`` (Wave 1) — surfaced as
 *     ``null`` in evidence; the page does not synthesize.
 *   * #3 ``SilverConversationRecord.domain_id = None`` (Wave 1) —
 *     surfaced as ``null`` in evidence; the page does not synthesize.
 *   * #4 ``_proposed_kind_to_source_kind`` heuristic — connector
 *     resolution is downstream's job. The dashboard renders the
 *     ``proposed_kind`` chip verbatim from the projection (no
 *     normalisation).
 *   * #5 Table name ``projection_conversations`` (NOT
 *     ``projection_silver_conversations``) — wired correctly in the
 *     count probe below.
 *   * #6 Channel-mention window hardcoded at 1000 rows — surfaced in
 *     the strategy banner note.
 *   * #7 No reactivity-ordering integration test — out of scope for
 *     this surface; the page renders the steady-state projection.
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** L1's three inference strategies. Mirrors
 *  :data:`wormbase_agent_gateway.source_candidate.protocol.SourceCandidateStrategy`. */
export type SourceCandidateStrategy =
  | "kpi_gap"
  | "channel_mention"
  | "complementarity";

/** One row in the /lake/source-candidates page table. */
export interface SourceCandidateRow {
  /** Deterministic SHA-256(:32 hex) hash over the canonical
   *  ``(proposed_kind, proposed_identifier, strategy)`` triple. */
  candidateId: string;
  /** Connector-registry kind string (e.g. ``csv_local`` /
   *  ``postgres`` / ``stripe`` / ``mcp:notion``). Verbatim from the
   *  projection — no normalisation (Sub-wave C handoff concern #4 —
   *  connector resolution is downstream's job). */
  proposedKind: string;
  /** Free-form identifier carrying enough hint for the admin to
   *  recognise the source (e.g. database name, file path, vendor
   *  account hint). */
  proposedIdentifier: string;
  /** Inferred WormBase domain when upstream signal supports it
   *  (e.g. kpi_gap threads gap's owning domain through); ``null``
   *  otherwise. Wave 1 limitation: today's KpiNodeRecord and
   *  SilverConversationRecord both surface NULL; handoff concerns
   *  #2 + #3 — the page surfaces NULL honestly. */
  domainIdHint: string | null;
  /** Strategy that proposed (or last-updated) this candidate. */
  strategy: SourceCandidateStrategy;
  /** Human-readable explanation surfaced on the row detail panel. */
  reasoning: string;
  /** Confidence float in [0.0, 1.0]. */
  confidence: number;
  /** Strategy-specific structured evidence dict (preserved verbatim
   *  through the fold). kpi_gap carries ``{kpi_node_id, ...}``;
   *  channel_mention carries ``{message_refs: [...]}``;
   *  complementarity carries ``{portfolio_snapshot: [...]}``. */
  evidence: Record<string, unknown>;
  /** Promote dual-write: when set, the downstream
   *  ``source_proposed`` entry id (or source-id) threaded back by the
   *  worm-core endpoint. NULL when the promote did not (yet) fire the
   *  downstream side, per Sub-wave C handoff concern #1. The page
   *  renders an honest "investigate" advisory in the NULL state. */
  downstreamSourceProposedId: string | null;
  /** Current state — ``"proposed"`` | ``"promoted"`` | ``"rejected"``.
   *  Note: L1 uses ``"promoted"`` where L3/L7/L4/L5/L6/L8 use
   *  ``"confirmed"`` — see spec §1 for rationale on the prequel-
   *  triage naming. */
  state: "proposed" | "promoted" | "rejected";
  /** ISO-8601 timestamp the state last changed. */
  stateChangedAt: string;
  /** Person UUID that last changed state; ``null`` while in proposed. */
  stateChangedBy: string | null;
}

/**
 * Per-page filter for /lake/source-candidates (2026-05-16 producer-side
 * deep-link bundle). Surfaces the ``?candidate_id=<id>`` URL param
 * landed by the Lake-Side Overview activity stream's drill-in for L1
 * rows. When set, narrows the rendered tables to the single candidate
 * identified by primary-key ``candidateId``. Honest empty when no row
 * matches.
 *
 * Symmetric pair: consumer pages filter by ``upstream_*_id``
 * (potentially many rows); producer pages filter by primary-key
 * ``candidateId`` (at most one row).
 */
export interface SourceCandidateFilter {
  candidateId?: string;
}

/** Per-strategy productivity signal surfaced by the status banner. */
export interface SourceCandidateStrategyStatus {
  strategy: SourceCandidateStrategy;
  /** True when the strategy is wired by the boot path (master + sub-knob on). */
  configured: boolean;
  /** True when the strategy can produce proposals today against this tenant. */
  productive: boolean;
  /** Short doc-string surfaced in the banner. */
  note: string;
  /** Honest status badge keyword. */
  badge: "production" | "configured-stubbed" | "disabled";
  /** Optional override label for the badge, e.g.
   *  ``productive · KPI-dependent`` or
   *  ``configured · awaiting-kpi-tree-population``. */
  badgeLabelOverride?: string;
}

/**
 * Upstream gauges for the strategy banner. Reads per-strategy upstream
 * projections (KPI nodes / silver conversations / connected sources)
 * scoped by ``company_id`` so the banner reflects the live tenant
 * state, not a process-global env-knob snapshot.
 */
export interface SourceCandidateUpstreamState {
  /** Count of rows in ``projection_kpi_nodes`` for this tenant
   *  (drives ``kpi_gap`` productivity). */
  kpiNodeCount: number;
  /** Count of rows in ``projection_conversations`` for this tenant
   *  (drives ``channel_mention`` productivity; Sub-wave C handoff
   *  concern #5 — the table is named ``projection_conversations``,
   *  NOT ``projection_silver_conversations``). */
  conversationCount: number;
  /** Count of rows in ``projection_sources`` for this tenant
   *  (drives ``complementarity`` productivity). */
  connectedSourceCount: number;
}

// ─── Internal row shape ───────────────────────────────────────────────────

interface SourceCandidateQueryRow extends Record<string, unknown> {
  candidate_id: string;
  proposed_kind: string;
  proposed_identifier: string;
  domain_id_hint: string | null;
  strategy: string;
  reasoning: string;
  confidence: number | string;
  evidence: Record<string, unknown> | null;
  downstream_source_proposed_id: string | null;
  state: "proposed" | "promoted" | "rejected";
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

function mapRow(r: SourceCandidateQueryRow): SourceCandidateRow {
  return {
    candidateId: r.candidate_id,
    proposedKind: r.proposed_kind,
    proposedIdentifier: r.proposed_identifier,
    domainIdHint: r.domain_id_hint,
    strategy: r.strategy as SourceCandidateStrategy,
    reasoning: r.reasoning,
    confidence: toFloat(r.confidence),
    evidence: (r.evidence ?? {}) as Record<string, unknown>,
    downstreamSourceProposedId: r.downstream_source_proposed_id,
    state: r.state,
    stateChangedAt: toIso(r.state_changed_at),
    stateChangedBy: r.state_changed_by,
  };
}

/**
 * Compose the WHERE-clause fragment + bind params for a
 * :class:`SourceCandidateFilter`. Always parameterized — never
 * interpolates user-controlled values into SQL.
 *
 * Currently a single optional predicate (``candidateId`` → primary-key
 * column). Returns ``{ where: "", values: [] }`` when the filter is
 * undefined or empty. Shape mirrors the producer-deep-links bundle
 * (``bdee480``) composer helpers for symmetry across the bundle.
 */
function _composeSourceCandidateFilter(
  filter: SourceCandidateFilter | undefined,
  nextParam: number,
): { where: string; values: unknown[] } {
  if (!filter) return { where: "", values: [] };
  const predicates: string[] = [];
  const values: unknown[] = [];
  let p = nextParam;

  if (filter.candidateId) {
    predicates.push(`AND candidate_id = $${p}`);
    values.push(filter.candidateId);
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
 * Fetch every proposed (not-yet-promoted-or-rejected) source-candidate
 * for a tenant, newest first.
 *
 * Returns ``[]`` when DATABASE_URL is unset, the query throws, or no
 * proposals exist yet — the page renders an honest empty state. No
 * FIXTURE return per CLAUDE.md §9.
 */
export async function getProposedSourceCandidates(
  companyId: string,
  opts: { limit?: number; filter?: SourceCandidateFilter } = {},
): Promise<SourceCandidateRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  const { where, values } = _composeSourceCandidateFilter(opts.filter, 2);

  const sql = `
    SELECT
      candidate_id,
      proposed_kind,
      proposed_identifier,
      domain_id_hint,
      strategy,
      reasoning,
      confidence,
      evidence,
      downstream_source_proposed_id,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_source_candidates
    WHERE company_id = $1
      AND state = 'proposed'${where}
    ORDER BY state_changed_at DESC, candidate_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SourceCandidateQueryRow>(sql, [
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
 * Fetch every promoted source-candidate for a tenant. Surfaced in a
 * separate section so admins can audit what already got through.
 */
export async function getPromotedSourceCandidates(
  companyId: string,
  opts: { limit?: number; filter?: SourceCandidateFilter } = {},
): Promise<SourceCandidateRow[]> {
  if (!postgresEnabled()) return [];
  const limit = Math.max(1, Math.min(opts.limit ?? 500, 2000));
  const { where, values } = _composeSourceCandidateFilter(opts.filter, 2);

  const sql = `
    SELECT
      candidate_id,
      proposed_kind,
      proposed_identifier,
      domain_id_hint,
      strategy,
      reasoning,
      confidence,
      evidence,
      downstream_source_proposed_id,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_source_candidates
    WHERE company_id = $1
      AND state = 'promoted'${where}
    ORDER BY state_changed_at DESC, candidate_id ASC
    LIMIT $${2 + values.length}
  `;

  try {
    const res = await pgQuery<SourceCandidateQueryRow>(sql, [
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
 * Fetch rejected source-candidates in the last ``days`` (default 30)
 * for strategy-tuning audit. Collapsed by default in the surface.
 */
export async function getRejectedSourceCandidates(
  companyId: string,
  opts: { days?: number; limit?: number; filter?: SourceCandidateFilter } = {},
): Promise<SourceCandidateRow[]> {
  if (!postgresEnabled()) return [];
  const days = Math.max(1, Math.min(opts.days ?? 30, 365));
  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));
  // $1 = companyId, $2 = days — filter starts at $3.
  const { where, values } = _composeSourceCandidateFilter(opts.filter, 3);

  const sql = `
    SELECT
      candidate_id,
      proposed_kind,
      proposed_identifier,
      domain_id_hint,
      strategy,
      reasoning,
      confidence,
      evidence,
      downstream_source_proposed_id,
      state,
      state_changed_at,
      state_changed_by
    FROM projection_source_candidates
    WHERE company_id = $1
      AND state = 'rejected'
      AND state_changed_at >= NOW() - ($2::int * INTERVAL '1 day')${where}
    ORDER BY state_changed_at DESC, candidate_id ASC
    LIMIT $${3 + values.length}
  `;

  try {
    const res = await pgQuery<SourceCandidateQueryRow>(sql, [
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
 * Probe the upstream state for the strategy banner. Reads three count
 * queries scoped by company_id:
 *
 *   * ``projection_kpi_nodes``      → drives ``kpi_gap`` posture
 *   * ``projection_conversations``  → drives ``channel_mention`` posture
 *                                     (NOT ``projection_silver_conversations``;
 *                                     Sub-wave C handoff concern #5)
 *   * ``projection_sources``        → drives ``complementarity`` posture
 *
 * Returns all-zero counts when DATABASE_URL is unset, the queries
 * throw, or the tables are empty — strategies surface as ``configured
 * · awaiting-*`` rather than ``productive``.
 */
export async function getSourceCandidateUpstreamState(
  companyId: string,
): Promise<SourceCandidateUpstreamState> {
  if (!postgresEnabled()) {
    return {
      kpiNodeCount: 0,
      conversationCount: 0,
      connectedSourceCount: 0,
    };
  }
  const [kpi, conv, src] = await Promise.all([
    _countSingle(
      `SELECT COUNT(*)::int AS n FROM projection_kpi_nodes WHERE company_id = $1`,
      [companyId],
    ),
    _countSingle(
      `SELECT COUNT(*)::int AS n FROM projection_conversations WHERE company_id = $1`,
      [companyId],
    ),
    _countSingle(
      `SELECT COUNT(*)::int AS n FROM projection_sources WHERE company_id = $1`,
      [companyId],
    ),
  ]);
  return {
    kpiNodeCount: kpi,
    conversationCount: conv,
    connectedSourceCount: src,
  };
}

/**
 * Resolve the per-strategy productivity gauges surfaced by the
 * /lake/source-candidates strategy banner. Reads the five L1 env knobs
 * + the three per-tenant upstream count probes (KPI tree size, silver-
 * conversation count, connected-source count).
 *
 * Strategy posture per spec §4.7 + Sub-wave B/C handoff notes:
 *
 *   * ``kpi_gap``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, 0 KPI nodes → ``configured · awaiting-kpi-tree-population``
 *     - both ON, ≥1 KPI node → ``productive · KPI-dependent`` (count)
 *
 *   * ``channel_mention``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, 0 conversations → ``configured · empty-upstream``
 *     - both ON, ≥1 conversation → ``productive · silver-dependent``
 *       (count; 24h × 1000-cap evaluation window per handoff #6)
 *
 *   * ``complementarity``
 *     - master OFF or sub-knob OFF → ``disabled``
 *     - both ON, 0 connected sources → ``configured · awaiting-first-source``
 *     - both ON, ≥1 connected source → ``productive · portfolio-dependent``
 *       (count)
 *
 * Master knob = ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED``.
 * Sub-knobs:
 *   - ``WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED``
 *   - ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED``
 *   - ``WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED``
 *
 * Tenant-isolation: composes env-knob state (process-global) with
 * per-tenant upstream-count probes. The L1 surface itself is env-
 * gated; per-tenant productivity is a function of upstream lake
 * population.
 */
export async function getSourceCandidateStrategyStatus(
  companyId: string,
): Promise<SourceCandidateStrategyStatus[]> {
  const discoveryEnabled = isTruthy(
    process.env.WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED,
  );
  const kpiGapEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED);
  const channelMentionEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED);
  const complementarityEnabled =
    discoveryEnabled &&
    isTruthy(process.env.WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED);

  // Short-circuit the upstream probe when the entire surface is off —
  // avoids pointless tenant queries when there's nothing to display.
  let upstream: SourceCandidateUpstreamState = {
    kpiNodeCount: 0,
    conversationCount: 0,
    connectedSourceCount: 0,
  };
  if (kpiGapEnabled || channelMentionEnabled || complementarityEnabled) {
    upstream = await getSourceCandidateUpstreamState(companyId);
  }

  // ── kpi_gap ──────────────────────────────────────────────────────
  let kpiGapBadge: SourceCandidateStrategyStatus["badge"];
  let kpiGapOverride: string | undefined;
  let kpiGapNote: string;
  let kpiGapProductive = false;
  if (!kpiGapEnabled) {
    kpiGapBadge = "disabled";
    kpiGapNote =
      "Disabled — set WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true and WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED=true to wire KpiGapAcquisitionStrategy. The strategy scans projection_kpi_nodes for nodes without a source_id in their lineage and proposes connector kinds inferred from the KPI name (regex bank: *_revenue → stripe/salesforce; *_signups → postgres/notion; *_pipeline → hubspot/salesforce; fallback csv_local).";
  } else if (upstream.kpiNodeCount === 0) {
    kpiGapBadge = "configured-stubbed";
    kpiGapOverride = "configured · awaiting-kpi-tree-population";
    kpiGapNote =
      "Configured — wired to projection_kpi_nodes but the tenant's KPI tree is empty. Populate the KPI tree (via /kpis or the worm's autoresearch propose loop) and kpi_gap graduates to productive automatically. domain_id_hint propagation from KPI nodes is currently NULL (Sub-wave C handoff concern #2 — KpiNodeRecord does not carry domain_id today).";
  } else {
    kpiGapBadge = "production";
    kpiGapOverride = "productive · KPI-dependent";
    kpiGapProductive = true;
    const n = upstream.kpiNodeCount;
    kpiGapNote = `Productive — reading ${n} KPI node${n === 1 ? "" : "s"} from projection_kpi_nodes. The strategy filters to nodes without an existing source_id in their lineage and proposes connector kinds matched to the KPI name (*_revenue -> stripe/salesforce; *_signups -> postgres/notion; *_pipeline -> hubspot/salesforce; fallback csv_local). domain_id_hint propagation is currently NULL (Sub-wave C handoff concern #2 - KpiNodeRecord does not carry domain_id today; surfaces as null in row evidence).`;
  }

  // ── channel_mention ──────────────────────────────────────────────
  let chanBadge: SourceCandidateStrategyStatus["badge"];
  let chanOverride: string | undefined;
  let chanNote: string;
  let chanProductive = false;
  if (!channelMentionEnabled) {
    chanBadge = "disabled";
    chanNote =
      "Disabled — set WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true and WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED=true to wire ChannelMentionAcquisitionStrategy. The strategy scans the last 1000 silver-conversation rows (24h cap) for a 30-pattern regex bank covering top connectors (e.g. ``our snowflake``, ``export from stripe``).";
  } else if (upstream.conversationCount === 0) {
    chanBadge = "configured-stubbed";
    chanOverride = "configured · empty-upstream";
    chanNote =
      "Configured — wired to projection_conversations (NOT projection_silver_conversations; Sub-wave C handoff concern #5) but the silver-conversation lake is empty. Awaiting silver-conversation messages — channel_mention graduates to productive once any bronze-cascade landing has folded into the conversation projection. domain_id_hint propagation from conversations is currently NULL (Sub-wave C handoff concern #3 — SilverConversationRecord does not carry domain_id today).";
  } else {
    chanBadge = "production";
    chanOverride = "productive · silver-dependent";
    chanProductive = true;
    const n = upstream.conversationCount;
    chanNote = `Productive — reading ${n} silver-conversation row${n === 1 ? "" : "s"} from projection_conversations (NOT projection_silver_conversations; Sub-wave C handoff concern #5). Strategy scans the last 1000 rows within a 24h window (Sub-wave C handoff concern #6 — env knob deferred to Phase 2) against a 30-pattern regex bank covering top connectors. Each emitted candidate carries evidence.message_refs back to the originating threads. domain_id_hint propagation is currently NULL (Sub-wave C handoff concern #3).`;
  }

  // ── complementarity ──────────────────────────────────────────────
  let compBadge: SourceCandidateStrategyStatus["badge"];
  let compOverride: string | undefined;
  let compNote: string;
  let compProductive = false;
  if (!complementarityEnabled) {
    compBadge = "disabled";
    compNote =
      "Disabled — set WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true and WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED=true to wire ComplementaritySourceStrategy. The strategy reads projection_sources and proposes portfolio-gap fillers — sales-heavy → marketing; finance-heavy → product; no file source → csv_local.";
  } else if (upstream.connectedSourceCount === 0) {
    compBadge = "configured-stubbed";
    compOverride = "configured · awaiting-first-source";
    compNote =
      "Configured — wired to projection_sources but no sources are connected yet. ComplementaritySourceStrategy needs at least one connected source to reason about portfolio gaps. Connect a source via /sources/new (or any of the five agentic-source-building flows) and complementarity graduates to productive automatically.";
  } else {
    compBadge = "production";
    compOverride = "productive · portfolio-dependent";
    compProductive = true;
    const n = upstream.connectedSourceCount;
    compNote = `Productive — reading ${n} connected source${n === 1 ? "" : "s"} from projection_sources. Portfolio-gap heuristics propose complementary connector kinds: sales-heavy portfolios → marketing connectors (hubspot/salesforce/gsheets); finance-heavy → product connectors (postgres/notion); no file source landed → csv_local. Connector resolution is downstream's job — proposed_kind chips render verbatim (Sub-wave C handoff concern #4).`;
  }

  return [
    {
      strategy: "kpi_gap",
      configured: kpiGapEnabled,
      productive: kpiGapProductive,
      badge: kpiGapBadge,
      badgeLabelOverride: kpiGapOverride,
      note: kpiGapNote,
    },
    {
      strategy: "channel_mention",
      configured: channelMentionEnabled,
      productive: chanProductive,
      badge: chanBadge,
      badgeLabelOverride: chanOverride,
      note: chanNote,
    },
    {
      strategy: "complementarity",
      configured: complementarityEnabled,
      productive: compProductive,
      badge: compBadge,
      badgeLabelOverride: compOverride,
      note: compNote,
    },
  ];
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  isTruthy,
  mapRow,
  _composeSourceCandidateFilter,
};
