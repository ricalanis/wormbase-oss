/**
 * /lake/query-improvement read-side accessors — Wave 3 Task 4.
 *
 * Compounding-loop dashboard surface. Three accessors back the page:
 *
 *   * ``getQueryOutcomes`` — reads ``projection_query_outcomes`` (v016).
 *     One row per ``query_outcome_recorded`` ledger entry; ordered by
 *     ``recorded_at`` DESC so the most recent outcomes surface first.
 *   * ``getQueryTemplates`` — reads ``projection_query_templates`` (v017).
 *     One row per ``query_template_promoted`` Reactivity firing;
 *     ordered by ``promoted_at`` DESC. Optionally filtered by
 *     ``domain_id``.
 *   * ``getSemanticGaps`` — reads ``semantic_gap_proposed`` ledger
 *     entries directly because there's no projection table for them at
 *     v016/v017 (and sibling Task 5 has not added one). Falls back to
 *     scanning the ledger's ``propose`` envelope for
 *     ``reason ∈ {no_match, low_confidence, ambiguous}`` shape,
 *     scoped by tenant and ordered by entry ts DESC.
 *
 * All three accessors follow the standard contract:
 *   - Return ``[]`` when DATABASE_URL is unset (hermetic test default).
 *   - Return ``[]`` when the projection table is missing (no migration
 *     applied yet) or the query throws — honest empty rather than crash.
 *   - SQL is tenant-scoped on ``company_id``.
 *
 * The ``embedding`` column on v016/v017 is intentionally NOT exposed
 * — embeddings are an internal artifact of OutcomeToTemplatePromotion
 * clustering; the dashboard surfaces the human-readable
 * compounding-loop story, not the vector store.
 */

import { pgQuery } from "./ledger-client";

// ─── Public row types ─────────────────────────────────────────────────────

export interface QueryOutcomeRow {
  /** Projection row id (deterministic over (company_id, execute_entry_id)). */
  id: string;
  /** Audit-trail id of the agent_query PEVR cycle that produced the outcome. */
  agentQueryId: string;
  /** Natural-language question the agent submitted. */
  nlQuestion: string;
  /** The QuerySpec that ultimately resolved the question. */
  finalQuerySpec: Record<string, unknown>;
  /** Summary of the result set (row_count + preview). */
  resultSummary: Record<string, unknown>;
  /** Did the agent use the result? */
  used: boolean;
  /** Did the user find it useful? */
  useful: boolean;
  /** Free-text correction the user provided, when ``useful=false``. */
  userCorrection: string | null;
  /** Decimal-as-string in [0.0, 1.0]; sortable lexicographically because
   *  the writer always quantizes to NUMERIC(6,4). */
  qualityScore: string;
  /** ISO-8601 timestamp the outcome was recorded. */
  recordedAt: string;
}

export interface QueryTemplateRow {
  /** Projection row id (deterministic over (company_id, propose_entry_id)). */
  id: string;
  /** Domain the template applies to. */
  domainId: string;
  /** Canonical NL intent (cluster key). */
  nlIntent: string;
  /** The cached QuerySpec — the cluster's best outcome's spec. */
  querySpec: Record<string, unknown>;
  /** Outcome audit-trail ids that drove the promotion — full provenance. */
  promotedFromOutcomeIds: string[];
  /** Mean cluster quality_score as a Decimal-shaped string. */
  qualityScore: string;
  /** Number of times the template has been served from cache. */
  hitCount: number;
  /** ISO-8601 timestamp the promotion landed. */
  promotedAt: string;
}

export interface SemanticGapRow {
  /** Stable correlation key (entry_id of the ``semantic_gap_proposed`` propose phase). */
  id: string;
  /** Agent that surfaced the gap. */
  agentId: string;
  /** The NL question the agent couldn't answer with the existing catalog. */
  nlQuestion: string;
  /** Why the agent bailed: ``no_match`` | ``low_confidence`` | ``ambiguous``. */
  reason: "no_match" | "low_confidence" | "ambiguous";
  /** Agent's suggested metric name (may be null when ``reason='ambiguous'``). */
  proposedMetricName: string | null;
  /** ISO-8601 timestamp the gap was proposed. */
  proposedAt: string;
}

// ─── Row shapes coming back from pg ───────────────────────────────────────

interface QueryOutcomeQueryRow extends Record<string, unknown> {
  id: string;
  agent_query_id: string;
  nl_question: string;
  final_query_spec: Record<string, unknown> | string | null;
  result_summary: Record<string, unknown> | string | null;
  used: boolean | string | number;
  useful: boolean | string | number;
  user_correction: string | null;
  quality_score: string;
  recorded_at: Date | string;
}

interface QueryTemplateQueryRow extends Record<string, unknown> {
  id: string;
  domain_id: string;
  nl_intent: string;
  query_spec: Record<string, unknown> | string | null;
  promoted_from_outcome_ids: string[] | string | null;
  quality_score: string;
  hit_count: number | string;
  promoted_at: Date | string;
}

interface SemanticGapQueryRow extends Record<string, unknown> {
  entry_id: string;
  ts: Date | string;
  payload: Record<string, unknown> | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

function toIso(v: string | Date): string {
  if (v instanceof Date) return v.toISOString();
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toISOString();
}

function toBool(v: boolean | string | number | null | undefined): boolean {
  if (v === true) return true;
  if (v === false) return false;
  if (typeof v === "number") return v !== 0;
  if (typeof v === "string") {
    const lc = v.toLowerCase();
    return lc === "t" || lc === "true" || lc === "1";
  }
  return false;
}

function parseJsonField(
  v: Record<string, unknown> | string | null | undefined,
): Record<string, unknown> {
  if (v === null || v === undefined) return {};
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return v;
}

function parseStringArrayField(
  v: string[] | string | null | undefined,
): string[] {
  if (!v) return [];
  if (Array.isArray(v)) return v.map((x) => String(x));
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return Array.isArray(parsed) ? parsed.map((x) => String(x)) : [];
    } catch {
      return [];
    }
  }
  return [];
}

function toNumber(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v;
  const parsed = Number.parseInt(v, 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function mapOutcome(r: QueryOutcomeQueryRow): QueryOutcomeRow {
  return {
    id: r.id,
    agentQueryId: r.agent_query_id,
    nlQuestion: r.nl_question,
    finalQuerySpec: parseJsonField(r.final_query_spec),
    resultSummary: parseJsonField(r.result_summary),
    used: toBool(r.used),
    useful: toBool(r.useful),
    userCorrection: r.user_correction,
    qualityScore: String(r.quality_score),
    recordedAt: toIso(r.recorded_at),
  };
}

function mapTemplate(r: QueryTemplateQueryRow): QueryTemplateRow {
  return {
    id: r.id,
    domainId: r.domain_id,
    nlIntent: r.nl_intent,
    querySpec: parseJsonField(r.query_spec),
    promotedFromOutcomeIds: parseStringArrayField(r.promoted_from_outcome_ids),
    qualityScore: String(r.quality_score),
    hitCount: toNumber(r.hit_count),
    promotedAt: toIso(r.promoted_at),
  };
}

function mapGap(r: SemanticGapQueryRow): SemanticGapRow | null {
  const payload = r.payload ?? {};
  // ``reason`` co-occurs with ``nl_question`` only on
  // semantic_gap_proposed envelopes. Defensive: skip rows that don't
  // match the shape rather than crash the page.
  const rawReason = payload.reason;
  if (
    rawReason !== "no_match" &&
    rawReason !== "low_confidence" &&
    rawReason !== "ambiguous"
  ) {
    return null;
  }
  const nlQuestion =
    typeof payload.nl_question === "string" ? payload.nl_question : "";
  const agentId =
    typeof payload.agent_id === "string" ? payload.agent_id : "";
  if (!nlQuestion || !agentId) return null;
  const proposedMetricName =
    typeof payload.proposed_metric_name === "string"
      ? payload.proposed_metric_name
      : null;
  return {
    id: typeof payload.audit_trail_id === "string"
      ? payload.audit_trail_id
      : r.entry_id,
    agentId,
    nlQuestion,
    reason: rawReason,
    proposedMetricName,
    proposedAt: toIso(r.ts),
  };
}

// ─── Public accessors ─────────────────────────────────────────────────────

/**
 * Fetch recent query outcomes for a tenant, ordered by ``recorded_at`` DESC.
 *
 * Returns ``[]`` honestly when:
 *   - DATABASE_URL is not set (test default).
 *   - The ``projection_query_outcomes`` table doesn't exist yet (no v016
 *     migration applied).
 *   - The tenant has no recorded outcomes (the compounding loop hasn't
 *     spun up — empty state is the first-day reality).
 *   - Any SQL error.
 */
export async function getQueryOutcomes(
  companyId: string,
  opts: { limit?: number } = {},
): Promise<QueryOutcomeRow[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 50, 500));

  const sql = `
    SELECT
      id,
      agent_query_id,
      nl_question,
      final_query_spec,
      result_summary,
      used,
      useful,
      user_correction,
      quality_score,
      recorded_at
    FROM projection_query_outcomes
    WHERE company_id = $1
    ORDER BY recorded_at DESC, id ASC
    LIMIT $2
  `;

  try {
    const res = await pgQuery<QueryOutcomeQueryRow>(sql, [companyId, limit]);
    return res.rows.map(mapOutcome);
  } catch {
    return [];
  }
}

/**
 * Fetch promoted query templates for a tenant, ordered by ``promoted_at``
 * DESC. Optionally filtered by ``domain_id``.
 *
 * Returns ``[]`` honestly under the same contract as ``getQueryOutcomes``.
 */
export async function getQueryTemplates(
  companyId: string,
  opts: { domainId?: string; limit?: number } = {},
): Promise<QueryTemplateRow[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 50, 500));
  const params: unknown[] = [companyId];
  let domainFilter = "";
  if (opts.domainId) {
    params.push(opts.domainId);
    domainFilter = ` AND domain_id = $${params.length}`;
  }
  params.push(limit);
  const limitParam = `$${params.length}`;

  const sql = `
    SELECT
      id,
      domain_id,
      nl_intent,
      query_spec,
      promoted_from_outcome_ids,
      quality_score,
      hit_count,
      promoted_at
    FROM projection_query_templates
    WHERE company_id = $1${domainFilter}
    ORDER BY promoted_at DESC, id ASC
    LIMIT ${limitParam}
  `;

  try {
    const res = await pgQuery<QueryTemplateQueryRow>(sql, params);
    return res.rows.map(mapTemplate);
  } catch {
    return [];
  }
}

/**
 * Fetch semantic gaps (agent-reported "no matching metric" events) for a
 * tenant.
 *
 * No projection table exists at v016/v017 for ``semantic_gap_proposed``
 * — and sibling Task 5 (``/lake/metrics-proposed`` admin queue) has not
 * yet added one. We read directly from the ``ledger`` table by matching
 * the propose-phase payload shape (``reason`` ∈ {no_match,
 * low_confidence, ambiguous} co-occurring with ``nl_question`` +
 * ``agent_id``). If sibling Task 5 lands a ``projection_semantic_gaps``
 * mirror, this accessor can be re-pointed at that table without
 * changing the page contract.
 *
 * ``opts.unresolved`` is currently a no-op (the gap-resolution flow is
 * scope for sibling Task 5; if it adds a status column to the
 * projection we can filter here). v1 returns ALL gaps; the admin
 * queue handles its own state.
 */
export async function getSemanticGaps(
  companyId: string,
  opts: { unresolved?: boolean; limit?: number } = {},
): Promise<SemanticGapRow[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 50, 500));
  // ``unresolved`` is reserved for sibling Task 5's projection-backed
  // implementation; the raw-ledger path returns all gaps. Reference it
  // so eslint doesn't flag the unused option — the contract is
  // forward-compatible.
  void opts.unresolved;

  // Tenant-scoped ledger scan. We match on the propose-phase envelope
  // because that's where ``lake.semantic.gap`` emits the typed-payload
  // body (the execute / verify / resolve carry the same body but
  // anchoring on propose yields one row per gap proposal).
  //
  // The ``payload->>'reason' IN (...)`` filter does the bulk of the
  // shape narrowing; the per-row ``mapGap`` defensively re-validates
  // ``nl_question`` + ``agent_id`` co-occurrence before emitting a
  // row, so payloads that happen to carry a ``reason`` field for an
  // unrelated kind get dropped without crashing the page.
  //
  // The ``->>`` operator works on both JSON and JSONB Postgres column
  // types (SQLAlchemy's generic ``JSON`` compiles to ``JSON`` on PG
  // by default).
  const sql = `
    SELECT
      entry_id::text AS entry_id,
      ts,
      payload
    FROM ledger
    WHERE company_id = $1
      AND kind = 'propose'
      AND payload->>'reason' IN ('no_match', 'low_confidence', 'ambiguous')
    ORDER BY ts DESC, seq DESC
    LIMIT $2
  `;

  try {
    const res = await pgQuery<SemanticGapQueryRow>(sql, [companyId, limit]);
    const rows: SemanticGapRow[] = [];
    const seen = new Set<string>();
    for (const r of res.rows) {
      const mapped = mapGap(r);
      if (mapped === null) continue;
      // Dedup on audit_trail_id: a single gap proposal writes a PEVR
      // cycle whose propose entry should be the only one matched
      // (execute/verify/resolve carry the SAME body but have non-
      // null ``propose_entry_id`` / ``execute_entry_id`` / etc. that
      // wouldn't pass the strict propose-kind filter — defensive
      // dedup anyway).
      if (seen.has(mapped.id)) continue;
      seen.add(mapped.id);
      rows.push(mapped);
    }
    return rows;
  } catch {
    return [];
  }
}
