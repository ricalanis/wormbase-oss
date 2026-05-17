/**
 * Agent identity + grants accessors (Wave 3 Task 2).
 *
 * The /people/agents surface reads two ledger projections:
 *
 *   * `projection_agents` — Person sub-type for external (Claude / OpenAI /
 *     Kimi / etc.) and internal (worm-issued) agents. One row per agent.
 *   * `projection_agent_grants` — per-agent grants for data + model access.
 *     One row per (agent_id, grant_kind, grant_target) triple; the
 *     status field consolidates assign + revoke (Addendum 3).
 *
 * The page-level fold derives two summary metrics per agent:
 *
 *   * `activeGrantCount` — count of grants with `status = 'active'`.
 *   * `budgetRemainingUsdSum` — sum of `budget_remaining_usd` across
 *     active `model.access` grants. Null when the agent has no model
 *     grants (the column is only populated for model.access).
 *
 * Empty state contract: every accessor returns `[]` rather than a
 * fixture when DATABASE_URL is unset or the projection table is empty —
 * the page renders an honest first-day state ("no agents registered yet")
 * per `feedback_onboarding_production_only.md`.
 */
import { pgQuery } from "./ledger-client";

export type AgentExternalProvider =
  | "claude"
  | "openai"
  | "kimi"
  | "internal_worm"
  | "other";

export type AgentStatus = "active" | "inactive";

export type AgentGrantKind =
  | "domain.read"
  | "resource.read"
  | "resource.maintainer"
  | "model.access";

export type AgentGrantStatus = "active" | "revoked";

export interface Agent {
  id: string;
  personId: string;
  externalProvider: AgentExternalProvider;
  displayName: string;
  registeredAt: string;
  registeredByPersonId: string;
  status: AgentStatus;
  activeGrantCount: number;
  /**
   * Sum of `budget_remaining_usd` across the agent's active `model.access`
   * grants. Stored as a decimal string (the Postgres `NUMERIC(18,4)`
   * round-trips losslessly as text). Null when the agent has no
   * model.access grants.
   */
  budgetRemainingUsdSum: string | null;
}

export interface AgentGrant {
  id: string;
  agentId: string;
  grantKind: AgentGrantKind;
  grantTarget: string;
  status: AgentGrantStatus;
  grantedBy: string;
  grantedAt: string;
  budgetRemainingUsd: string | null;
}

interface AgentRow {
  id: string;
  person_id: string;
  external_provider: string;
  display_name: string;
  registered_at: Date | string;
  registered_by: string;
  status: string;
  active_grant_count: string | number | null;
  budget_remaining_usd_sum: string | null;
  [k: string]: unknown;
}

interface AgentGrantRow {
  id: string;
  agent_id: string;
  grant_kind: string;
  grant_target: string;
  status: string;
  granted_by: string;
  granted_at: Date | string;
  budget_remaining_usd: string | null;
  [k: string]: unknown;
}

function toIsoString(value: Date | string): string {
  return typeof value === "string" ? value : value.toISOString();
}

/**
 * SQL note: registered_by is not stored as a column on `projection_agents`
 * (the v012 schema captures id, company_id, person_id, external_provider,
 * display_name, registered_at, status). The dashboard surfaces it via the
 * `agent_registered` execute-row payload — but for v1 we mirror the v012
 * shape: `registered_by` defaults to the person_id when the projection
 * doesn't carry it. The /people/agents detail page can resolve the
 * authoritative `registered_by` from the ledger trace if needed.
 */
const AGENTS_SQL = `
  SELECT
    a.id,
    a.person_id,
    a.external_provider,
    a.display_name,
    a.registered_at,
    a.person_id AS registered_by,
    a.status,
    COALESCE(g.active_grant_count, 0) AS active_grant_count,
    g.budget_remaining_usd_sum
  FROM projection_agents a
  LEFT JOIN (
    SELECT
      agent_id,
      COUNT(*) FILTER (WHERE status = 'active') AS active_grant_count,
      SUM(budget_remaining_usd)
        FILTER (WHERE status = 'active' AND grant_kind = 'model.access')
        AS budget_remaining_usd_sum
    FROM projection_agent_grants
    WHERE company_id = $1
    GROUP BY agent_id
  ) g ON g.agent_id = a.id
  WHERE a.company_id = $1
  ORDER BY a.registered_at DESC, a.id ASC
`;

const AGENT_GRANTS_SQL = `
  SELECT
    id,
    agent_id,
    grant_kind,
    grant_target,
    status,
    granted_by,
    granted_at,
    budget_remaining_usd
  FROM projection_agent_grants
  WHERE company_id = $1 AND agent_id = $2
  ORDER BY granted_at DESC, id ASC
`;

export async function getAgents(companyId: string): Promise<Agent[]> {
  if (!process.env.DATABASE_URL) return [];
  try {
    const res = await pgQuery<AgentRow>(AGENTS_SQL, [companyId]);
    return res.rows.map((row) => ({
      id: row.id,
      personId: row.person_id,
      externalProvider: row.external_provider as AgentExternalProvider,
      displayName: row.display_name,
      registeredAt: toIsoString(row.registered_at),
      registeredByPersonId: row.registered_by,
      status: row.status as AgentStatus,
      activeGrantCount:
        row.active_grant_count == null
          ? 0
          : typeof row.active_grant_count === "number"
            ? row.active_grant_count
            : Number.parseInt(String(row.active_grant_count), 10) || 0,
      budgetRemainingUsdSum:
        row.budget_remaining_usd_sum == null
          ? null
          : String(row.budget_remaining_usd_sum),
    }));
  } catch {
    // Honest empty state when projection table is missing (pre-migration)
    // or DB is unreachable. The page renders the empty-state copy.
    return [];
  }
}

export interface AgentActivitySummary {
  /** Number of agent_query PEVR cycles initiated by this agent. */
  queriesRun: number;
  /** Number of query_template_promoted entries traceable to this agent. */
  templatesPromoted: number;
  /** Number of bad_pattern_proposed entries traceable to this agent. */
  badPatternsTriggered: number;
  /** Number of data_product_consumed entries by this agent. */
  dataProductsConsumed: number;
  /** Most recent agent_query ts observed for this agent. */
  lastSeenAt: string | null;
  /** Lookback window in days, mirrored back for the UI label. */
  windowDays: number;
}

const AGENT_ACTIVITY_SQL = `
  WITH window_filter AS (
    SELECT NOW() - ($3 || ' days')::interval AS cutoff
  ),
  queries AS (
    SELECT COUNT(*) AS n, MAX(l.ts) AS last_seen
      FROM ledger l, window_filter w
     WHERE l.company_id = $1
       AND l.kind = 'propose'
       AND l.payload->>'target_kind' = 'agent_query'
       AND l.payload->'args'->>'agent_id' = $2
       AND l.ts >= w.cutoff
  ),
  templates AS (
    SELECT COUNT(*) AS n
      FROM ledger l, window_filter w
     WHERE l.company_id = $1
       AND l.kind = 'execute'
       AND l.payload->>'tool' = 'emit_query_template_promoted'
       AND l.payload->'args'->>'agent_id' = $2
       AND l.ts >= w.cutoff
  ),
  bad_patterns AS (
    SELECT COUNT(*) AS n
      FROM ledger l, window_filter w
     WHERE l.company_id = $1
       AND l.kind = 'execute'
       AND l.payload->>'tool' = 'emit_bad_pattern_proposed'
       AND l.payload->'args'->>'agent_id' = $2
       AND l.ts >= w.cutoff
  ),
  dp_consumed AS (
    SELECT COUNT(*) AS n
      FROM ledger l, window_filter w
     WHERE l.company_id = $1
       AND l.kind = 'execute'
       AND l.payload->>'tool' = 'emit_data_product_consumed'
       AND l.payload->'args'->>'consumer_id' = $2
       AND l.ts >= w.cutoff
  )
  SELECT
    queries.n      AS queries_run,
    templates.n    AS templates_promoted,
    bad_patterns.n AS bad_patterns_triggered,
    dp_consumed.n  AS data_products_consumed,
    queries.last_seen AS last_seen_at
  FROM queries, templates, bad_patterns, dp_consumed
`;

interface ActivityRow {
  queries_run: string | number | null;
  templates_promoted: string | number | null;
  bad_patterns_triggered: string | number | null;
  data_products_consumed: string | number | null;
  last_seen_at: Date | string | null;
  [k: string]: unknown;
}

function toInt(value: string | number | null | undefined): number {
  if (value == null) return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const n = Number.parseInt(String(value), 10);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Per-agent activity summary aggregated over a rolling window.
 *
 * Reads four ledger projections in one round-trip:
 *
 *   * ``queriesRun`` — count of ``propose`` rows with
 *     ``target_kind='agent_query'`` and ``args.agent_id = agentId``
 *   * ``templatesPromoted`` — count of ``execute`` rows whose tool is
 *     ``emit_query_template_promoted`` and whose ``args.agent_id``
 *     matches the source agent
 *   * ``badPatternsTriggered`` — same shape, tool=
 *     ``emit_bad_pattern_proposed``
 *   * ``dataProductsConsumed`` — ``execute`` rows with tool
 *     ``emit_data_product_consumed`` and ``args.consumer_id = agentId``
 *
 * Returns zero counts and ``lastSeenAt=null`` when DB is unreachable.
 * Empty state is honest per CLAUDE.md §9.
 */
export async function getAgentActivitySummary(
  companyId: string,
  agentId: string,
  windowDays = 30,
): Promise<AgentActivitySummary> {
  const empty: AgentActivitySummary = {
    queriesRun: 0,
    templatesPromoted: 0,
    badPatternsTriggered: 0,
    dataProductsConsumed: 0,
    lastSeenAt: null,
    windowDays,
  };
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) {
    return empty;
  }
  if (!agentId) return empty;
  try {
    const res = await pgQuery<ActivityRow>(AGENT_ACTIVITY_SQL, [
      companyId,
      agentId,
      String(windowDays),
    ]);
    const row = res.rows[0];
    if (!row) return empty;
    return {
      queriesRun: toInt(row.queries_run),
      templatesPromoted: toInt(row.templates_promoted),
      badPatternsTriggered: toInt(row.bad_patterns_triggered),
      dataProductsConsumed: toInt(row.data_products_consumed),
      lastSeenAt:
        row.last_seen_at == null ? null : toIsoString(row.last_seen_at),
      windowDays,
    };
  } catch {
    return empty;
  }
}

export interface AgentAuditEntry {
  seq: number;
  ts: string;
  kind: string;
  tool: string | null;
  /** Pretty one-line summary derived from the payload. */
  summary: string;
}

const AGENT_AUDIT_SQL = `
  SELECT
    l.seq      AS seq,
    l.ts       AS ts,
    l.kind     AS kind,
    l.payload->>'tool' AS tool,
    l.payload  AS payload
  FROM ledger l
  WHERE l.company_id = $1
    AND l.kind = 'execute'
    AND (
      l.payload->>'tool' IN (
        'emit_agent_registered',
        'emit_agent_grant',
        'emit_agent_grant_revoked',
        'emit_agent_metadata_updated',
        'emit_agent_query',
        'emit_agent_subscription_created',
        'emit_agent_subscription_revoked',
        'emit_agent_event_delivered'
      )
      AND (
        l.payload->'args'->>'agent_id' = $2
        OR l.payload->'args'->>'consumer_id' = $2
      )
    )
  ORDER BY l.seq DESC
  LIMIT 20
`;

interface AuditRow {
  seq: string | number;
  ts: Date | string;
  kind: string;
  tool: string | null;
  payload: Record<string, unknown> | null;
  [k: string]: unknown;
}

function summarizeEntry(row: AuditRow): string {
  const args = (row.payload?.args ?? {}) as Record<string, unknown>;
  switch (row.tool) {
    case "emit_agent_registered":
      return `registered (provider=${String(args.external_provider ?? "?")})`;
    case "emit_agent_grant":
      return `grant assigned: ${String(args.grant_kind ?? "?")} → ${String(args.grant_target ?? "?")}`;
    case "emit_agent_grant_revoked":
      return `grant revoked: ${String(args.grant_kind ?? "?")} → ${String(args.grant_target ?? "?")}`;
    case "emit_agent_metadata_updated": {
      const changed: string[] = [];
      if (args.display_name != null) changed.push("display_name");
      if (args.description != null) changed.push("description");
      const fields = changed.length > 0 ? changed.join("+") : "metadata";
      const reason = args.reason ? ` — ${String(args.reason)}` : "";
      return `metadata updated (${fields})${reason}`;
    }
    case "emit_agent_query":
      return `query: ${String(args.mcp_tool ?? args.tool ?? "?")}`;
    case "emit_agent_subscription_created":
      return `subscription created (transport=${String(args.transport ?? "?")})`;
    case "emit_agent_subscription_revoked":
      return `subscription revoked: ${String(args.subscription_id ?? "?").slice(0, 12)}…`;
    case "emit_agent_event_delivered":
      return `event delivered: kind=${String(args.triggering_entry_kind ?? "?")} status=${String(args.delivery_status ?? "?")}`;
    default:
      return row.tool ?? row.kind;
  }
}

/**
 * Last N ledger entries written about (or by) the agent. Used by the
 * /people/agents/[id] detail page audit panel. Returns ``[]`` on
 * DB unavailable.
 */
export async function getAgentAuditEntries(
  companyId: string,
  agentId: string,
  limit = 20,
): Promise<AgentAuditEntry[]> {
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) {
    return [];
  }
  if (!agentId) return [];
  try {
    const res = await pgQuery<AuditRow>(AGENT_AUDIT_SQL, [
      companyId,
      agentId,
    ]);
    return res.rows.slice(0, limit).map((row) => ({
      seq: toInt(row.seq),
      ts: toIsoString(row.ts),
      kind: row.kind,
      tool: row.tool,
      summary: summarizeEntry(row),
    }));
  } catch {
    return [];
  }
}

export async function getAgentGrants(
  companyId: string,
  agentId: string,
): Promise<AgentGrant[]> {
  if (!process.env.DATABASE_URL) return [];
  try {
    const res = await pgQuery<AgentGrantRow>(AGENT_GRANTS_SQL, [
      companyId,
      agentId,
    ]);
    return res.rows.map((row) => ({
      id: row.id,
      agentId: row.agent_id,
      grantKind: row.grant_kind as AgentGrantKind,
      grantTarget: row.grant_target,
      status: row.status as AgentGrantStatus,
      grantedBy: row.granted_by,
      grantedAt: toIsoString(row.granted_at),
      budgetRemainingUsd:
        row.budget_remaining_usd == null
          ? null
          : String(row.budget_remaining_usd),
    }));
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// getAgentMetadata — final wave item #5 (2026-05-13).
//
// Folds the most-recent ``agent_metadata_updated`` ledger entries to
// produce the agent's current display_name + description. Returns
// (null, null) when no metadata-updated entries exist for the agent
// (the page falls back to ``agent.displayName`` / no description).
//
// Per-field fold: the latest non-null value per field wins. This
// honors the entry's "None = unchanged" semantics — a description-only
// update does not clear a prior display_name change, and vice versa.
//
// SQL approach: scan the ledger for the agent's metadata-updated
// execute rows in reverse-seq order and take the first non-null per
// field. Avoids a dedicated projection table — the volume is bounded
// (admins don't edit agent metadata in tight loops) and the index on
// (company_id, kind, payload->>'tool') already exists.
// ---------------------------------------------------------------------------

export interface AgentMetadata {
  /** Latest display_name override, or null if never overridden. */
  displayName: string | null;
  /** Latest description, or null if never set. */
  description: string | null;
  /** Total agent_metadata_updated entries for this agent.
   *  Used by the page to decide whether to render the Revert button
   *  (post-rest path #4, 2026-05-13). */
  updateCount: number;
}

const AGENT_METADATA_SQL = `
  SELECT
    l.payload->'args'->>'display_name' AS display_name,
    l.payload->'args'->>'description' AS description,
    l.seq AS seq
  FROM ledger l
  WHERE l.company_id = $1
    AND l.kind = 'execute'
    AND l.payload->>'tool' = 'emit_agent_metadata_updated'
    AND l.payload->'args'->>'agent_id' = $2
  ORDER BY l.seq DESC
`;

interface MetadataRow {
  display_name: string | null;
  description: string | null;
  seq: string | number;
  [k: string]: unknown;
}

export async function getAgentMetadata(
  companyId: string,
  agentId: string,
): Promise<AgentMetadata> {
  const empty: AgentMetadata = {
    displayName: null,
    description: null,
    updateCount: 0,
  };
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) {
    return empty;
  }
  if (!agentId) return empty;
  try {
    const res = await pgQuery<MetadataRow>(AGENT_METADATA_SQL, [
      companyId,
      agentId,
    ]);
    let displayName: string | null = null;
    let description: string | null = null;
    // Walk every row to compute the fold AND the update count (don't
    // early-break — we need the full count for the Revert visibility
    // gate).
    for (const row of res.rows) {
      if (displayName === null && row.display_name !== null) {
        displayName = row.display_name;
      }
      if (description === null && row.description !== null) {
        description = row.description;
      }
    }
    return {
      displayName,
      description,
      updateCount: res.rows.length,
    };
  } catch {
    return empty;
  }
}
