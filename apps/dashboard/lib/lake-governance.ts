/**
 * /lake/governance read-side accessors — Semantic Layer Wave 3 Task 6.
 *
 * Reads two projection surfaces side-by-side:
 *
 *   * Upstream (catalog-mirror) — ``projection_external_policy``,
 *     populated by the CatalogImportReactivity from
 *     ``external_policy_imported`` ledger entries. One row per upstream
 *     masking / row-access policy.
 *   * WormBase-side — the existing /policies surface backed by
 *     ``emit_policy_applied`` entries (warmup pack, PII gates, etc.).
 *
 * The page renders both lists in two columns so an operator can
 * compare what governance the upstream catalog enforces vs what
 * WormBase enforces on its own. Body diff comparison is out of
 * scope for v1 — the lists are presented honestly, the side-by-side
 * layout is the affordance.
 *
 * S2 spike contract: ``ExternalPolicyRow.body`` is intentionally
 * nullable. Read-only Snowflake catalog roles typically lack APPLY
 * privilege and cannot fetch the policy SQL — the projection
 * preserves ``NULL`` verbatim and the dashboard surfaces a
 * "Body unavailable (insufficient APPLY privilege)" placeholder.
 *
 * Strategy: try Postgres first (when ``DATABASE_URL`` is set); on
 * any failure — connection refused, table missing on a fresh
 * tenant, empty result — return ``[]``. The page's empty state then
 * surfaces an honest "no policies imported yet" affordance rather
 * than lying about the tenant's governance state.
 */

import { pgQuery } from "./ledger-client";

/**
 * One row in the upstream-policy column of the side-by-side view.
 *
 * Names are dashboard-side camelCase. The accessor maps the
 * snake_case Postgres columns to this shape at the SQL→TS boundary
 * so downstream components never reach for ``r.policy_fqn`` style
 * Postgres column names.
 */
export interface ExternalPolicyRow {
  /** UUID of the projection row (deterministic on (source, fqn)). */
  id: string;
  /** UUID of the connected source the policy was mirrored from. */
  sourceId: string;
  /** Human-readable source name when joinable (otherwise the kind). */
  sourceName: string;
  /** Fully-qualified policy name from the upstream catalog. */
  policyFqn: string;
  /** "masking" (column-level) or "row_access" (row-level). */
  policyKind: "masking" | "row_access";
  /**
   * Policy body — the SQL/DSL that implements the policy. NULL
   * when the catalog credential lacked APPLY privilege; the
   * dashboard renders the placeholder copy in that case.
   */
  body: string | null;
  /** Column / table references the policy is attached to upstream. */
  appliedTo: string[];
  /** ISO-8601 timestamp the policy was imported. */
  importedAt: string;
}

/**
 * One row in the WormBase-policy column of the side-by-side view.
 *
 * Sourced from the existing /policies page accessor
 * (``getPolicies`` in ``ledger-client.ts``) but flattened to a
 * comparable side-by-side shape so the two columns share the same
 * presentational scaffolding.
 */
export interface WormbasePolicyRow {
  /** Stable id — the underlying policy_id from emit_policy_applied. */
  id: string;
  /** Display name; falls back to policy_id when name is missing. */
  policyName: string;
  /**
   * Plain-language description of the policy (warmup PII redact,
   * channel talkativeness, interjection budget, …). Always present
   * because the existing accessor synthesizes one when the
   * policy-pack is missing it.
   */
  plainLanguage: string;
  /** ``"global"`` | ``"per-domain"`` | ``"per-channel"``. */
  scope: string;
  /** Gate implementation id (``policy.warmup_pii_redact_v1`` etc.). */
  gateImpl: string;
  /** Body / DSL — currently the gate_impl string; null when missing. */
  body: string | null;
}

interface ExternalPolicyQueryRow extends Record<string, unknown> {
  id: string;
  source_id: string;
  source_name: string | null;
  policy_fqn: string;
  policy_kind: "masking" | "row_access";
  body: string | null;
  applied_to: unknown;
  imported_at: string | Date;
}

/** True when the runtime is configured to talk to Postgres. */
function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

function toIso(v: string | Date): string {
  if (v instanceof Date) return v.toISOString();
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toISOString();
}

function toStringArray(v: unknown): string[] {
  if (Array.isArray(v)) {
    return v.filter((x): x is string => typeof x === "string");
  }
  // Postgres' JSON column may return a string when the JSON is stored
  // as text; defensively try to parse.
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return Array.isArray(parsed)
        ? parsed.filter((x): x is string => typeof x === "string")
        : [];
    } catch {
      return [];
    }
  }
  return [];
}

function mapExternalRow(r: ExternalPolicyQueryRow): ExternalPolicyRow {
  return {
    id: r.id,
    sourceId: r.source_id,
    sourceName: r.source_name ?? "(unknown source)",
    policyFqn: r.policy_fqn,
    policyKind: r.policy_kind,
    body: r.body,
    appliedTo: toStringArray(r.applied_to),
    importedAt: toIso(r.imported_at),
  };
}

/**
 * Fetch every upstream-catalog policy for a tenant, optionally
 * filtered by ``sourceId``. Ordered by ``imported_at DESC`` so the
 * most-recent imports surface first in the side-by-side view.
 *
 * Returns ``[]`` when:
 *
 *   * ``DATABASE_URL`` is not set (test default — keeps unit tests
 *     hermetic without a Postgres dependency).
 *   * The query throws (table missing on a fresh tenant, connection
 *     refused, …).
 *   * No policies have been imported for this tenant yet.
 *
 * The dashboard's /lake/governance page renders the empty state
 * honestly in all three cases; we never substitute a fixture.
 */
export async function getExternalPolicies(
  companyId: string,
  opts: { sourceId?: string; limit?: number } = {},
): Promise<ExternalPolicyRow[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 200, 500));
  const params: unknown[] = [companyId];
  const filters: string[] = ["p.company_id = $1"];

  if (opts.sourceId) {
    params.push(opts.sourceId);
    filters.push(`p.source_id = $${params.length}`);
  }

  const whereClause = filters.join(" AND ");
  params.push(limit);
  const limitParam = `$${params.length}`;

  // LEFT JOIN against projection_external_catalog to surface the
  // source_kind as a display label — when the catalog hasn't been
  // imported yet (rare; the policy and catalog cycles fire from the
  // same Reactivity) we fall back to "(unknown source)" in the
  // mapper.
  const sql = `
    SELECT
      p.id::text                 AS id,
      p.source_id::text          AS source_id,
      MAX(c.source_kind)         AS source_name,
      p.policy_fqn               AS policy_fqn,
      p.policy_kind              AS policy_kind,
      p.body                     AS body,
      p.applied_to               AS applied_to,
      p.imported_at              AS imported_at
    FROM projection_external_policy p
    LEFT JOIN projection_external_catalog c
      ON c.company_id = p.company_id
     AND c.source_id  = p.source_id
    WHERE ${whereClause}
    GROUP BY p.id, p.source_id, p.policy_fqn, p.policy_kind,
             p.body, p.applied_to, p.imported_at
    ORDER BY p.imported_at DESC, p.policy_fqn ASC
    LIMIT ${limitParam}
  `;

  try {
    const res = await pgQuery<ExternalPolicyQueryRow>(sql, params);
    return res.rows.map(mapExternalRow);
  } catch {
    return [];
  }
}

/**
 * Fetch WormBase-side policies for a tenant. v1 surfaces the same
 * data set the existing /policies page uses (``emit_policy_applied``
 * entries → projection-less view via ``getPolicies``), flattened
 * into the side-by-side shape.
 *
 * If no WormBase policies exist for the tenant (e.g. warmup hasn't
 * run yet) returns ``[]`` and the page surfaces an honest empty
 * column. This is the same posture the upstream-policy column uses.
 *
 * The ``opts.sourceId`` argument is accepted for API parity with
 * ``getExternalPolicies`` but is unused — WormBase policies are
 * scoped to domains / channels / global, not to upstream sources.
 * Callers wanting to filter the WormBase column by source should
 * filter the result list client-side; v1 of the side-by-side view
 * shows the global WormBase policy list against any selected
 * upstream source.
 */
export async function getWormbasePolicies(
  companyId: string,
  _opts: { sourceId?: string } = {},
): Promise<WormbasePolicyRow[]> {
  if (!postgresEnabled()) return [];

  // Inline the SQL rather than importing getPolicies to avoid a
  // shape coupling against the v1 PolicyRow shape (which carries
  // fire-counts and receipts the side-by-side view doesn't render).
  const sql = `
    WITH applied AS (
      SELECT DISTINCT ON (payload->'args'->>'policy_id')
        payload->'args'->>'policy_id'   AS policy_id,
        payload->'args'->>'policy_name' AS policy_name,
        payload->'args'->>'gate_impl'   AS gate_impl,
        payload->'args'->'applies_to'   AS applies_to
      FROM ledger
      WHERE company_id = $1
        AND kind = 'execute'
        AND payload->>'tool' = 'emit_policy_applied'
        AND payload->'args'->>'policy_id' IS NOT NULL
      ORDER BY payload->'args'->>'policy_id', seq ASC
    )
    SELECT policy_id, policy_name, gate_impl, applies_to
      FROM applied
     ORDER BY COALESCE(policy_name, policy_id) ASC
  `;

  try {
    const res = await pgQuery<{
      policy_id: string;
      policy_name: string | null;
      gate_impl: string | null;
      applies_to: Record<string, unknown> | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): WormbasePolicyRow => {
      const name = r.policy_name ?? r.policy_id;
      const at = r.applies_to ?? {};
      const scope = (() => {
        if (typeof at["channel"] === "string") return "per-channel";
        if (typeof at["domain"] === "string") return "per-domain";
        return "global";
      })();
      return {
        id: r.policy_id,
        policyName: name,
        // The WormBase /policies page synthesizes plain-language
        // copy from a hand-curated table; we keep the body
        // surface minimal here and let the page render a tighter
        // line. The same gate_impl shows up as ``body`` because
        // it's the closest "code that runs" the WormBase side has.
        plainLanguage: `${name} (${r.gate_impl ?? "no gate impl"})`,
        scope,
        gateImpl: r.gate_impl ?? "",
        body: r.gate_impl ?? null,
      };
    });
  } catch {
    return [];
  }
}
