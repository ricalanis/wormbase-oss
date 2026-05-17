/**
 * Tenant-quota ledger read accessors (post-rest #3, 2026-05-13).
 *
 * Surfaces ``tenant_quota_consumed`` ledger entries — the opt-in
 * ``LedgerQuotaTracker`` (final-wave item #7) emits one entry per tenant
 * at cadence (every ``count_threshold`` requests OR every
 * ``time_threshold_seconds`` per tenant, whichever fires first; immediate
 * on ``quota_exhausted``).
 *
 * Same raw-ledger-scan shape as ``agent-subscriptions.ts``. Two
 * accessors:
 *
 *   * ``getTenantQuotaSummary(companyId)`` — per-tenant 24h aggregation.
 *     Sums ``consumption_count`` over the window; reads ``quota_limit``
 *     and ``quota_remaining`` from the most recent entry in the window;
 *     notes the most recent ``window_end_ts``.
 *   * ``getRecentQuotaEvents(companyId, limit=100)`` — recent flat-stream
 *     ``tenant_quota_consumed`` entries, ordered by ledger seq DESC.
 *     Used for the per-event audit list below the per-tenant summary.
 *
 * Empty-state contract: both accessors return ``[]`` when DB unavailable
 * OR when no tenant-quota entries exist (the default state when
 * ``WORMBASE_TENANT_QUOTA_LEDGER`` is unset). The page renders an
 * honest empty state per CLAUDE.md §9.
 */
import { DEFAULT_COMPANY_ID, pgQuery } from "./ledger-client";

export type QuotaTrigger =
  | "count_threshold"
  | "time_threshold"
  | "quota_exhausted";

export interface TenantQuotaSummary {
  tenantSlug: string;
  /** Sum of ``consumption_count`` across the 24h window. */
  consumed24h: number;
  /** Most-recent ``quota_limit`` observed in the window. */
  quotaLimit: number;
  /** ``quotaLimit`` − ``consumed24h``, never below 0. */
  remaining: number;
  /** ISO8601 of the most-recent entry's ``window_end_ts``. */
  lastEventTs: string;
  /** Trigger on the most-recent entry — used for inline styling hint. */
  lastTriggeredBy: QuotaTrigger;
  /** Count of ``triggered_by=quota_exhausted`` entries in the window. */
  exhaustedCount24h: number;
}

export interface QuotaEvent {
  /** Ledger seq of the entry. */
  seq: number;
  tenantSlug: string;
  consumptionCount: number;
  quotaLimit: number;
  quotaRemaining: number;
  windowStartTs: string;
  windowEndTs: string;
  triggeredBy: QuotaTrigger;
  /** Ledger entry ts (entry write time), distinct from window_end_ts. */
  ts: string;
  hashHex: string;
}

interface SummaryRow {
  tenant_slug: string;
  consumed_24h: string | number | null;
  quota_limit: string | number | null;
  last_event_ts: Date | string | null;
  last_triggered_by: string | null;
  exhausted_count_24h: string | number | null;
  [k: string]: unknown;
}

interface EventRow {
  seq: string | number;
  tenant_slug: string;
  consumption_count: string | number | null;
  quota_limit: string | number | null;
  quota_remaining: string | number | null;
  window_start_ts: Date | string;
  window_end_ts: Date | string;
  triggered_by: string | null;
  ts: Date | string;
  hash_hex: string;
  [k: string]: unknown;
}

function toIso(value: Date | string | null): string {
  if (value === null) return "";
  return value instanceof Date
    ? value.toISOString()
    : new Date(value).toISOString();
}

function toInt(value: string | number | null | undefined): number {
  if (value == null) return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const n = Number.parseInt(String(value), 10);
  return Number.isFinite(n) ? n : 0;
}

function asTrigger(value: string | null | undefined): QuotaTrigger {
  if (value === "time_threshold") return "time_threshold";
  if (value === "quota_exhausted") return "quota_exhausted";
  return "count_threshold";
}

function hasPgEnv(): boolean {
  return Boolean(process.env.DATABASE_URL || process.env.WORMBASE_LEDGER_DSN);
}

/**
 * Per-tenant aggregation over the last 24h of ``tenant_quota_consumed``
 * entries. One row per tenant_slug observed in the window. Sorted by
 * ``consumed_24h`` DESC so the busiest tenants surface first.
 *
 * Returns ``[]`` when DB unavailable OR no entries exist.
 */
export async function getTenantQuotaSummary(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<TenantQuotaSummary[]> {
  if (!hasPgEnv()) return [];

  const sql = `
    WITH window_entries AS (
      SELECT l.seq                                                AS seq,
             l.ts                                                  AS ts,
             l.payload->'args'->>'tenant_slug'                    AS tenant_slug,
             (l.payload->'args'->>'consumption_count')::bigint    AS consumption_count,
             (l.payload->'args'->>'quota_limit')::bigint          AS quota_limit,
             l.payload->'args'->>'window_end_ts'                  AS window_end_ts,
             l.payload->'args'->>'triggered_by'                   AS triggered_by
        FROM ledger l
       WHERE l.company_id = $1
         AND l.kind = 'execute'
         AND l.payload->>'tool' = 'emit_tenant_quota_consumed'
         AND l.ts > (NOW() - INTERVAL '24 hours')
    ),
    latest AS (
      SELECT DISTINCT ON (tenant_slug)
             tenant_slug,
             quota_limit                AS last_quota_limit,
             window_end_ts              AS last_window_end_ts,
             triggered_by               AS last_triggered_by
        FROM window_entries
       ORDER BY tenant_slug, seq DESC
    ),
    aggregated AS (
      SELECT tenant_slug,
             COALESCE(SUM(consumption_count), 0)::bigint AS consumed_24h,
             COUNT(*) FILTER (WHERE triggered_by = 'quota_exhausted')::bigint
               AS exhausted_count_24h
        FROM window_entries
       GROUP BY tenant_slug
    )
    SELECT a.tenant_slug                                   AS tenant_slug,
           a.consumed_24h                                  AS consumed_24h,
           l.last_quota_limit                              AS quota_limit,
           l.last_window_end_ts                            AS last_event_ts,
           l.last_triggered_by                             AS last_triggered_by,
           a.exhausted_count_24h                           AS exhausted_count_24h
      FROM aggregated a
      JOIN latest l ON l.tenant_slug = a.tenant_slug
     ORDER BY a.consumed_24h DESC, a.tenant_slug ASC
  `;

  try {
    const res = await pgQuery<SummaryRow>(sql, [companyId]);
    return res.rows.map((row) => {
      const consumed = toInt(row.consumed_24h);
      const limit = toInt(row.quota_limit);
      const remaining = limit > consumed ? limit - consumed : 0;
      return {
        tenantSlug: row.tenant_slug,
        consumed24h: consumed,
        quotaLimit: limit,
        remaining,
        lastEventTs: toIso(row.last_event_ts),
        lastTriggeredBy: asTrigger(row.last_triggered_by),
        exhaustedCount24h: toInt(row.exhausted_count_24h),
      };
    });
  } catch {
    return [];
  }
}

export interface QuotaEventQueryOpts {
  limit?: number;
  /** Optional filter — restrict to a single trigger discriminator. */
  triggeredBy?: QuotaTrigger;
}

/**
 * Flat-stream recent ``tenant_quota_consumed`` entries, ordered by ledger
 * ``seq`` DESC. Default limit 100, capped at 500. The page surfaces this
 * as a chronological audit list under the per-tenant summary.
 *
 * Not restricted to the 24h window — operators may want to look back
 * further when investigating a specific deny moment.
 */
export async function getRecentQuotaEvents(
  companyId: string = DEFAULT_COMPANY_ID,
  opts: QuotaEventQueryOpts = {},
): Promise<QuotaEvent[]> {
  if (!hasPgEnv()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 100, 500));
  const clauses: string[] = [
    "l.company_id = $1",
    "l.kind = 'execute'",
    "l.payload->>'tool' = 'emit_tenant_quota_consumed'",
  ];
  const params: unknown[] = [companyId];
  let p = 2;

  if (opts.triggeredBy) {
    clauses.push(`l.payload->'args'->>'triggered_by' = $${p}`);
    params.push(opts.triggeredBy);
    p += 1;
  }

  const sql = `
    SELECT l.seq                                                  AS seq,
           l.payload->'args'->>'tenant_slug'                      AS tenant_slug,
           (l.payload->'args'->>'consumption_count')::bigint      AS consumption_count,
           (l.payload->'args'->>'quota_limit')::bigint            AS quota_limit,
           (l.payload->'args'->>'quota_remaining')::bigint        AS quota_remaining,
           l.payload->'args'->>'window_start_ts'                  AS window_start_ts,
           l.payload->'args'->>'window_end_ts'                    AS window_end_ts,
           l.payload->'args'->>'triggered_by'                     AS triggered_by,
           l.ts                                                    AS ts,
           encode(l.hash, 'hex')                                   AS hash_hex
      FROM ledger l
     WHERE ${clauses.join(" AND ")}
     ORDER BY l.seq DESC
     LIMIT ${limit}
  `;

  try {
    const res = await pgQuery<EventRow>(sql, params);
    return res.rows.map((row) => ({
      seq: toInt(row.seq),
      tenantSlug: row.tenant_slug,
      consumptionCount: toInt(row.consumption_count),
      quotaLimit: toInt(row.quota_limit),
      quotaRemaining: toInt(row.quota_remaining),
      windowStartTs: toIso(row.window_start_ts),
      windowEndTs: toIso(row.window_end_ts),
      triggeredBy: asTrigger(row.triggered_by),
      ts: toIso(row.ts),
      hashHex: row.hash_hex,
    }));
  } catch {
    return [];
  }
}

/**
 * Consumption-band classifier — used for inline styling badges on the
 * per-tenant summary table. Mirrors the visual hints in the post-rest #3
 * spec:
 *
 *   * ``>= 0.9`` of the quota consumed → ``critical`` (red badge).
 *   * ``>= 0.7`` → ``warn`` (yellow badge).
 *   * otherwise → ``healthy`` (no badge).
 *
 * Pure function — exposed for the page + its unit tests.
 */
export type ConsumptionBand = "critical" | "warn" | "healthy";

export function consumptionBand(
  consumed: number,
  limit: number,
): ConsumptionBand {
  if (limit <= 0) return "healthy";
  const ratio = consumed / limit;
  if (ratio >= 0.9) return "critical";
  if (ratio >= 0.7) return "warn";
  return "healthy";
}

// Re-exports for unit tests
export const __test__ = {
  asTrigger,
  consumptionBand,
  DEFAULT_COMPANY_ID,
};
