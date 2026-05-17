/**
 * Agent subscription + delivery accessors (v2.A Task 7).
 *
 * Reads from the ledger directly, following the same raw-scan pattern as
 * ``getDecisions`` / ``getDataProducts`` / the v2.A backend's
 * ``LedgerSubscriptionReader``. Per the v2.A risk register, a raw scan is
 * acceptable at v2.A scale (the per-tenant active set is small in v1);
 * promotion to ``projection_agent_subscriptions_active`` is deferred until
 * tenants regularly exceed ~100 active subscriptions.
 *
 * Two surfaces:
 *
 *   * ``getAgentSubscriptions(companyId, agentId)`` — active subscriptions
 *     owned by ``agentId``. Active = created MINUS revoked.
 *   * ``getRecentDeliveries(companyId, opts)`` — recent
 *     ``agent_event_delivered`` entries. Filterable by ``agentId``,
 *     ``subscriptionId``, or a ``querySeqRange`` (used by the
 *     /trace/agent_query Related Deliveries panel to scope deliveries to
 *     the entries written during a single PEVR chain).
 *
 * Empty-state contract: every accessor returns ``[]`` on DB unavailable
 * or empty projection — the page renders an honest empty state per
 * ``feedback_onboarding_production_only.md``.
 */
import { DEFAULT_COMPANY_ID, pgQuery } from "./ledger-client";

export type SubscriptionTransport = "mcp_stream" | "webhook";

export interface SubscriptionFilterSummary {
  kinds: string[];
  domains: string[];
  agentIdRef: string | null;
  payloadPathEq: [string, string][];
}

export interface Subscription {
  subscriptionId: string;
  agentId: string;
  filter: SubscriptionFilterSummary;
  transport: SubscriptionTransport;
  webhookUrl: string | null;
  description: string | null;
  createdAt: string;
  createdSeq: number;
  /**
   * Count of ``agent_event_delivered`` entries for this subscription in
   * the last 24h. Computed in the SQL so the page renders without an
   * N+1 round-trip.
   */
  deliveryCount24h: number;
}

export type DeliveryStatus = "delivered" | "failed" | "no_target";

export interface Delivery {
  /** Ledger seq of the ``agent_event_delivered`` execute entry. */
  seq: number;
  subscriptionId: string;
  triggeringEntrySeq: number;
  triggeringEntryKind: string;
  transportUsed: SubscriptionTransport;
  deliveryStatus: DeliveryStatus;
  durationMs: number;
  error: string | null;
  ts: string;
  hashHex: string;
}

interface SubscriptionRow {
  subscription_id: string;
  agent_id: string;
  filter: Record<string, unknown> | null;
  transport: string | null;
  webhook_url: string | null;
  description: string | null;
  created_at: Date | string;
  created_seq: string | number;
  delivery_count_24h: string | number | null;
  [k: string]: unknown;
}

interface DeliveryRow {
  seq: string | number;
  subscription_id: string;
  triggering_entry_seq: string | number | null;
  triggering_entry_kind: string | null;
  transport_used: string | null;
  delivery_status: string | null;
  duration_ms: string | number | null;
  error: string | null;
  ts: Date | string;
  hash_hex: string;
  [k: string]: unknown;
}

function toIso(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function toInt(value: string | number | null | undefined): number {
  if (value == null) return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const n = Number.parseInt(String(value), 10);
  return Number.isFinite(n) ? n : 0;
}

function asTransport(value: string | null | undefined): SubscriptionTransport {
  return value === "webhook" ? "webhook" : "mcp_stream";
}

function asDeliveryStatus(value: string | null | undefined): DeliveryStatus {
  if (value === "failed") return "failed";
  if (value === "no_target") return "no_target";
  return "delivered";
}

function normalizeFilter(
  raw: Record<string, unknown> | null,
): SubscriptionFilterSummary {
  const r = raw ?? {};
  const kinds = Array.isArray(r.kinds)
    ? (r.kinds as unknown[]).filter((v): v is string => typeof v === "string")
    : [];
  const domains = Array.isArray(r.domains)
    ? (r.domains as unknown[]).filter((v): v is string => typeof v === "string")
    : [];
  const agentIdRef = typeof r.agent_id_ref === "string" ? r.agent_id_ref : null;
  const payloadPathEq = Array.isArray(r.payload_path_eq)
    ? (r.payload_path_eq as unknown[])
        .map((pair) =>
          Array.isArray(pair) &&
          pair.length === 2 &&
          typeof pair[0] === "string" &&
          typeof pair[1] === "string"
            ? ([pair[0], pair[1]] as [string, string])
            : null,
        )
        .filter((v): v is [string, string] => v !== null)
    : [];
  return { kinds, domains, agentIdRef, payloadPathEq };
}

/**
 * Active subscriptions for an agent. Active = ``emit_agent_subscription_created``
 * minus subsequent ``emit_agent_subscription_revoked`` writes (matched by
 * ``subscription_id``). Joined to a 24h-window ``agent_event_delivered``
 * count so the list page renders deliveries-per-sub inline.
 */
export async function getAgentSubscriptions(
  companyId: string,
  agentId: string,
): Promise<Subscription[]> {
  if (!agentId) return [];
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) return [];

  const sql = `
    WITH created AS (
      SELECT DISTINCT ON (l.payload->'args'->>'subscription_id')
             l.payload->'args'->>'subscription_id'     AS subscription_id,
             l.payload->'args'->>'agent_id'            AS agent_id,
             l.payload->'args'->'filter'               AS filter,
             l.payload->'args'->>'transport'           AS transport,
             l.payload->'args'->>'webhook_url'         AS webhook_url,
             l.payload->'args'->>'description'         AS description,
             l.ts                                       AS created_at,
             l.seq                                      AS created_seq
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_agent_subscription_created'
         AND l.payload->'args'->>'agent_id' = $2
       ORDER BY l.payload->'args'->>'subscription_id', l.seq DESC
    ),
    revoked AS (
      SELECT DISTINCT l.payload->'args'->>'subscription_id' AS subscription_id
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_agent_subscription_revoked'
    ),
    deliveries_24h AS (
      SELECT l.payload->'args'->>'subscription_id'    AS subscription_id,
             COUNT(*)                                  AS count_24h
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_agent_event_delivered'
         AND l.ts > (NOW() - INTERVAL '24 hours')
       GROUP BY l.payload->'args'->>'subscription_id'
    )
    SELECT c.subscription_id,
           c.agent_id,
           c.filter,
           c.transport,
           c.webhook_url,
           c.description,
           c.created_at,
           c.created_seq,
           COALESCE(d.count_24h, 0)                    AS delivery_count_24h
      FROM created c
      LEFT JOIN revoked r ON r.subscription_id = c.subscription_id
      LEFT JOIN deliveries_24h d ON d.subscription_id = c.subscription_id
     WHERE r.subscription_id IS NULL
     ORDER BY c.created_seq DESC
  `;

  try {
    const res = await pgQuery<SubscriptionRow>(sql, [companyId, agentId]);
    return res.rows.map((row) => ({
      subscriptionId: row.subscription_id,
      agentId: row.agent_id,
      filter: normalizeFilter(row.filter),
      transport: asTransport(row.transport),
      webhookUrl: row.webhook_url,
      description: row.description,
      createdAt: toIso(row.created_at),
      createdSeq: toInt(row.created_seq),
      deliveryCount24h: toInt(row.delivery_count_24h),
    }));
  } catch {
    return [];
  }
}

export interface DeliveryQueryOpts {
  agentId?: string;
  subscriptionId?: string;
  /** Inclusive [low, high] range on the ``triggering_entry_seq`` field. */
  querySeqRange?: [number, number];
  limit?: number;
}

/**
 * Recent ``agent_event_delivered`` entries, ordered by
 * ``triggering_entry_seq`` DESC. Returns up to ``opts.limit`` rows
 * (default 50). The optional filters compose with AND.
 */
export async function getRecentDeliveries(
  companyId: string,
  opts: DeliveryQueryOpts = {},
): Promise<Delivery[]> {
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 50, 500));
  const clauses: string[] = [
    "l.company_id = $1",
    "l.kind = 'execute'",
    "l.payload->>'tool' = 'emit_agent_event_delivered'",
  ];
  const params: unknown[] = [companyId];
  let p = 2;

  if (opts.subscriptionId) {
    clauses.push(`l.payload->'args'->>'subscription_id' = $${p}`);
    params.push(opts.subscriptionId);
    p += 1;
  }
  if (opts.querySeqRange) {
    const [lo, hi] = opts.querySeqRange;
    clauses.push(
      `(l.payload->'args'->>'triggering_entry_seq')::bigint BETWEEN $${p} AND $${p + 1}`,
    );
    params.push(String(lo), String(hi));
    p += 2;
  }

  let agentJoin = "";
  if (opts.agentId) {
    // For agent-scoped queries, restrict by subscriptions owned by that
    // agent. We resolve subscription ownership via the created-entry's
    // payload, joining on subscription_id.
    agentJoin = `
      JOIN (
        SELECT DISTINCT ON (payload->'args'->>'subscription_id')
               payload->'args'->>'subscription_id' AS subscription_id,
               payload->'args'->>'agent_id'        AS agent_id
          FROM ledger
         WHERE company_id = $1
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_agent_subscription_created'
         ORDER BY payload->'args'->>'subscription_id', seq DESC
      ) sub
        ON sub.subscription_id = l.payload->'args'->>'subscription_id'
       AND sub.agent_id = $${p}
    `;
    params.push(opts.agentId);
    p += 1;
  }

  const sql = `
    SELECT l.seq                                                 AS seq,
           l.payload->'args'->>'subscription_id'                 AS subscription_id,
           (l.payload->'args'->>'triggering_entry_seq')::bigint  AS triggering_entry_seq,
           l.payload->'args'->>'triggering_entry_kind'           AS triggering_entry_kind,
           l.payload->'args'->>'transport_used'                  AS transport_used,
           l.payload->'args'->>'delivery_status'                 AS delivery_status,
           (l.payload->'args'->>'duration_ms')::int              AS duration_ms,
           l.payload->'args'->>'error'                            AS error,
           l.ts                                                   AS ts,
           encode(l.hash, 'hex')                                  AS hash_hex
      FROM ledger l
      ${agentJoin}
     WHERE ${clauses.join(" AND ")}
     ORDER BY (l.payload->'args'->>'triggering_entry_seq')::bigint DESC NULLS LAST,
              l.seq DESC
     LIMIT ${limit}
  `;

  try {
    const res = await pgQuery<DeliveryRow>(sql, params);
    return res.rows.map((row) => ({
      seq: toInt(row.seq),
      subscriptionId: row.subscription_id,
      triggeringEntrySeq: toInt(row.triggering_entry_seq),
      triggeringEntryKind: row.triggering_entry_kind ?? "",
      transportUsed: asTransport(row.transport_used),
      deliveryStatus: asDeliveryStatus(row.delivery_status),
      durationMs: toInt(row.duration_ms),
      error: row.error,
      ts: toIso(row.ts),
      hashHex: row.hash_hex,
    }));
  } catch {
    return [];
  }
}

/**
 * Per-agent active count — used by the /people/agents page's
 * Subscriptions column. Computed via raw scan + de-dupe on the
 * subscription_id (matches ``LedgerSubscriptionReader``'s semantics).
 */
export async function getAgentSubscriptionCounts(
  companyId: string,
): Promise<Map<string, number>> {
  const out = new Map<string, number>();
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) return out;

  const sql = `
    WITH created AS (
      SELECT DISTINCT ON (l.payload->'args'->>'subscription_id')
             l.payload->'args'->>'subscription_id'     AS subscription_id,
             l.payload->'args'->>'agent_id'            AS agent_id
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_agent_subscription_created'
       ORDER BY l.payload->'args'->>'subscription_id', l.seq DESC
    ),
    revoked AS (
      SELECT DISTINCT l.payload->'args'->>'subscription_id' AS subscription_id
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_agent_subscription_revoked'
    )
    SELECT c.agent_id AS agent_id, COUNT(*) AS count
      FROM created c
      LEFT JOIN revoked r ON r.subscription_id = c.subscription_id
     WHERE r.subscription_id IS NULL
       AND c.agent_id IS NOT NULL
     GROUP BY c.agent_id
  `;

  try {
    const res = await pgQuery<{
      agent_id: string;
      count: string | number;
      [k: string]: unknown;
    }>(sql, [companyId]);
    for (const row of res.rows) {
      out.set(row.agent_id, toInt(row.count));
    }
  } catch {
    // empty state
  }
  return out;
}

// Re-exports for the v2.A close-out tests
export const __test__ = {
  normalizeFilter,
  DEFAULT_COMPANY_ID,
};
