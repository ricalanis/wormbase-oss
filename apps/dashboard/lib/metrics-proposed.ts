/**
 * /lake/metrics-proposed read-side accessor — Semantic Layer Wave 3 Task 5.
 *
 * Reads ``semantic_gap_proposed`` ledger entries directly via aggregation
 * on the raw ``ledger`` table (similar to ``decision-chain.ts``). Each
 * gap is emitted by the ``lake.semantic.gap`` MCP tool when an agent
 * cannot find a metric in the catalog that answers a user's question.
 *
 * Wave 3+ improvement note: a future migration could materialize this
 * into ``projection_semantic_gaps`` for faster queries on tenants with
 * very high gap volume. For now, the raw-ledger query is bounded by
 * ``LIMIT`` and filtered tightly (kind = 'propose' AND a known shape).
 *
 * Resolution semantics:
 *
 *   A gap is "resolved" when a later ``external_metric_imported`` entry
 *   carries a matching ``proposed_metric_name`` (case-insensitive). The
 *   ``{unresolved: true}`` filter excludes those. When no
 *   ``proposed_metric_name`` was attached to the gap (``reason == "ambiguous"``
 *   is the common case), it stays unresolved forever — admins promote
 *   manually via ``/lake/metrics-proposed``.
 *
 * Strategy: try Postgres when ``DATABASE_URL`` / ``WORMBASE_LEDGER_DSN``
 * is set; on any failure return ``[]`` so the page renders an honest
 * empty state. No fixture-fallback.
 */

import { DEFAULT_COMPANY_ID, pgQuery } from "./ledger-client";

// ─── Types ────────────────────────────────────────────────────────────────

/**
 * One row in the /lake/metrics-proposed admin queue.
 *
 * Names are dashboard-side camelCase; the accessor maps the snake_case
 * Postgres payload at the SQL→TS boundary so downstream components
 * never reach for ``r.proposed_metric_name`` style names.
 */
export interface SemanticGapRow {
  /** Ledger entry_id of the ``propose`` row that opened this gap. */
  id: string;
  /** Agent that reported the gap (``agent:<slug>`` form). */
  agentId: string;
  /** NL question the agent failed to answer. */
  nlQuestion: string;
  /** Why the agent bailed: no_match / low_confidence / ambiguous. */
  reason: "no_match" | "low_confidence" | "ambiguous";
  /** Suggested canonical metric name; ``null`` when ambiguous. */
  proposedMetricName: string | null;
  /** ISO-8601 timestamp the gap was proposed. */
  proposedAt: string;
  /** ``unresolved`` until a matching ``external_metric_imported`` lands. */
  status: "unresolved" | "resolved";
}

// ─── Internal row shapes ──────────────────────────────────────────────────

interface GapQueryRow extends Record<string, unknown> {
  entry_id: string;
  ts: string | Date;
  payload: {
    agent_id?: string;
    nl_question?: string;
    reason?: string;
    proposed_metric_name?: string | null;
    audit_trail_id?: string;
  } | null;
}

interface ResolvedMetricRow extends Record<string, unknown> {
  metric_name: string;
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

function coerceReason(
  raw: string | undefined,
): "no_match" | "low_confidence" | "ambiguous" {
  if (raw === "low_confidence") return "low_confidence";
  if (raw === "ambiguous") return "ambiguous";
  return "no_match";
}

// ─── Postgres-bound accessor ──────────────────────────────────────────────

/**
 * Fetch every ``semantic_gap_proposed`` propose-phase entry for a tenant.
 *
 * SQL strategy:
 *
 *   * Query ``ledger`` rows with ``kind = 'propose'`` whose payload
 *     carries the canonical gap shape (``nl_question`` + ``reason``).
 *     The ``mcp_tool != 'lake.semantic.gap'`` exclusion drops denial
 *     traces that get tagged with the tool name on the propose row
 *     (those have a different shape — no nl_question + reason payload
 *     at the propose level; the denial path emits its own agent_query
 *     envelope).
 *
 *   * Pull the latest ``proposed_metric_name`` set from
 *     ``external_metric_imported`` execute rows for the same tenant.
 *     A gap's ``proposedMetricName`` matching (case-insensitive) any
 *     of those names flips the row's status to ``resolved``.
 *
 *   * ``{unresolved: true}`` filters in-memory after the join — keeps
 *     the SQL simple and the resolution-rule colocated with the type.
 *
 * Returns ``[]`` when:
 *   * ``DATABASE_URL`` is not set (test default).
 *   * The query throws (table missing, connection refused, …).
 *   * No gaps have been proposed for this tenant yet.
 */
export async function getSemanticGaps(
  companyId: string = DEFAULT_COMPANY_ID,
  opts: { unresolved?: boolean; limit?: number } = {},
): Promise<SemanticGapRow[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 200, 1000));

  // 1. Pull the propose-phase rows that carry the gap-proposed payload.
  //    The shape check (``nl_question + reason``) keeps us from sweeping
  //    up unrelated propose rows. Tenant scope is enforced via
  //    ``company_id = $1``.
  const gapsSql = `
    SELECT
      entry_id::text     AS entry_id,
      ts                 AS ts,
      payload            AS payload
    FROM ledger
    WHERE company_id = $1
      AND kind = 'propose'
      AND payload ? 'nl_question'
      AND payload ? 'reason'
      AND payload ? 'agent_id'
      AND COALESCE(payload->>'mcp_tool', '') <> 'lake.semantic.gap'
    ORDER BY seq DESC
    LIMIT $2
  `;

  // 2. Pull every ``external_metric_imported`` metric name on this
  //    tenant. Execute-phase rows carry the canonical
  //    ``tool=emit_external_metric_imported`` marker per the
  //    target_kind shape established in Wave 1 / W2 Task 3.
  const resolvedSql = `
    SELECT LOWER(payload->'args'->>'metric_name')::text AS metric_name
    FROM ledger
    WHERE company_id = $1
      AND kind = 'execute'
      AND payload->>'tool' = 'emit_external_metric_imported'
      AND payload->'args' ? 'metric_name'
  `;

  try {
    const gapsRes = await pgQuery<GapQueryRow>(gapsSql, [companyId, limit]);
    const resolvedRes = await pgQuery<ResolvedMetricRow>(resolvedSql, [
      companyId,
    ]);

    const resolvedNames = new Set(
      resolvedRes.rows
        .map((r) => (r.metric_name ?? "").trim())
        .filter((s) => s.length > 0),
    );

    const rows: SemanticGapRow[] = gapsRes.rows.map((r) => {
      const payload = r.payload ?? {};
      const proposedMetricName =
        typeof payload.proposed_metric_name === "string" &&
        payload.proposed_metric_name.length > 0
          ? payload.proposed_metric_name
          : null;
      const resolved =
        proposedMetricName !== null &&
        resolvedNames.has(proposedMetricName.toLowerCase());
      return {
        id: r.entry_id,
        agentId: typeof payload.agent_id === "string" ? payload.agent_id : "",
        nlQuestion:
          typeof payload.nl_question === "string" ? payload.nl_question : "",
        reason: coerceReason(payload.reason),
        proposedMetricName,
        proposedAt: toIso(r.ts),
        status: resolved ? "resolved" : "unresolved",
      };
    });

    if (opts.unresolved) {
      return rows.filter((r) => r.status === "unresolved");
    }
    return rows;
  } catch {
    // Honest empty: table may not exist yet, pool down, etc. The page
    // surfaces the empty state in any of those cases.
    return [];
  }
}
