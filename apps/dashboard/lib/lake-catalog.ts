/**
 * /lake/catalog read-side accessors — Semantic Layer Wave 3 Task 1.
 *
 * Reads the projection tables populated by the catalog-mirror Wave 1
 * worm:
 *
 *   * ``projection_external_catalog`` — one row per (source_id,
 *     snapshot_hash) snapshot import. Latest snapshot per source_id
 *     wins for the catalog tab; historical rows back the drift
 *     timeline (out of scope for v1).
 *   * ``projection_external_lineage`` — one row per upstream→downstream
 *     edge per snapshot import.
 *
 * Strategy: try Postgres first (when DATABASE_URL is set); on any
 * failure — connection refused, table missing because no catalog has
 * been imported yet, empty result — return ``[]`` (or ``null`` for the
 * single-object getter). The page's empty state then surfaces an
 * honest "connect a dbt / Snowflake source" affordance rather than
 * lying about the tenant's catalog state.
 *
 * This module does NOT re-implement the pg pool; it leans on
 * ``pgQuery`` exported by ``ledger-client.ts`` for the singleton-pool
 * + tenancy-cookie-safe access pattern shared by every dashboard
 * accessor.
 */

import { pgQuery } from "./ledger-client";

/**
 * One row in the /lake/catalog browse table.
 *
 * Names are dashboard-side camelCase. The accessor maps the
 * snake_case Postgres columns to this shape at the SQL→TS boundary so
 * downstream components never reach for ``r.source_kind`` style
 * Postgres column names.
 */
export interface CatalogTable {
  /** UUID of the source that produced this catalog snapshot. */
  sourceId: string;
  /** Domain UUID the source is scoped to. */
  domainId: string;
  /** "dbt" | "snowflake_native" | "cube" | … (CatalogSource.kind). */
  sourceKind: string;
  /** Catalog-mirror snapshot hash — the drift baseline. */
  snapshotHash: string;
  /** Tables in the snapshot (raw from the catalog). */
  tableCount: number;
  /** Edges in the snapshot's lineage graph. */
  edgeCount: number;
  /** Semantic metrics in the snapshot (dbt metrics, Cube measures, …). */
  metricCount: number;
  /** "initial" (first mirror) | "refresh" (re-discover pass). */
  importMode: "initial" | "refresh";
  /** Upstream edges feeding this source's nodes (folded from lineage). */
  upstreamLineageCount: number;
  /** Downstream edges fed by this source's nodes. */
  downstreamLineageCount: number;
  /** ISO-8601 timestamp the snapshot was imported. */
  importedAt: string;
}

/**
 * Detail view shape for the per-source drill-down — currently a thin
 * extension of ``CatalogTable`` that also surfaces the raw edge list.
 * The detail page is out of scope for Wave 3 Task 1 (v1 just emits
 * row-shape so click-through navigates to a placeholder); kept here
 * so future iterations don't have to re-think the contract.
 */
export interface CatalogTableDetail extends CatalogTable {
  /** All upstream lineage edges where ``downstream`` lives in this source. */
  upstreamEdges: Array<{ upstream: string; downstream: string }>;
  /** All downstream lineage edges where ``upstream`` lives in this source. */
  downstreamEdges: Array<{ upstream: string; downstream: string }>;
}

interface CatalogQueryRow extends Record<string, unknown> {
  source_id: string;
  domain_id: string;
  source_kind: string;
  snapshot_hash: string;
  table_count: number | string;
  edge_count: number | string;
  metric_count: number | string;
  import_mode: "initial" | "refresh";
  upstream_lineage_count: number | string;
  downstream_lineage_count: number | string;
  imported_at: string | Date;
}

interface LineageEdgeRow extends Record<string, unknown> {
  upstream: string;
  downstream: string;
}

/** True when the runtime is configured to talk to Postgres. */
function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

function toNumber(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v;
  const parsed = Number.parseInt(v, 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toIso(v: string | Date): string {
  if (v instanceof Date) return v.toISOString();
  // Postgres returns strings already in ISO-8601; pass through but
  // normalize via Date round-trip so the dashboard never sees a
  // Postgres-flavored "YYYY-MM-DD HH:MM:SS+00" form.
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toISOString();
}

function mapRow(r: CatalogQueryRow): CatalogTable {
  return {
    sourceId: r.source_id,
    domainId: r.domain_id,
    sourceKind: r.source_kind,
    snapshotHash: r.snapshot_hash,
    tableCount: toNumber(r.table_count),
    edgeCount: toNumber(r.edge_count),
    metricCount: toNumber(r.metric_count),
    importMode: r.import_mode,
    upstreamLineageCount: toNumber(r.upstream_lineage_count),
    downstreamLineageCount: toNumber(r.downstream_lineage_count),
    importedAt: toIso(r.imported_at),
  };
}

/**
 * Fetch every most-recent catalog snapshot for a tenant, optionally
 * filtered by ``domainId`` or a case-insensitive substring on
 * ``source_kind``.
 *
 * Returns ``[]`` when:
 *
 *   * ``DATABASE_URL`` is not set (test default — keeps unit tests
 *     hermetic without a Postgres dependency).
 *   * The query throws (table missing, connection refused, …).
 *   * No catalogs have been imported for this tenant yet.
 *
 * The dashboard's /lake/catalog page renders the empty state honestly
 * in all three cases; we never substitute a fixture.
 */
export async function getCatalogTables(
  companyId: string,
  opts: { domainId?: string; search?: string; limit?: number } = {},
): Promise<CatalogTable[]> {
  if (!postgresEnabled()) return [];

  const limit = Math.max(1, Math.min(opts.limit ?? 100, 500));
  const params: unknown[] = [companyId];
  const filters: string[] = ["c.company_id = $1"];

  if (opts.domainId) {
    params.push(opts.domainId);
    filters.push(`c.domain_id = $${params.length}`);
  }
  if (opts.search) {
    params.push(`%${opts.search}%`);
    filters.push(`c.source_kind ILIKE $${params.length}`);
  }

  const whereClause = filters.join(" AND ");
  params.push(limit);
  const limitParam = `$${params.length}`;

  // Inner DISTINCT ON picks the most-recent snapshot per source_id;
  // lineage subqueries count upstream/downstream edges from the
  // companion ``projection_external_lineage`` rows scoped to the same
  // (company_id, source_id). We aggregate over the full lineage table
  // — Wave 1's tenant-scoped delete+insert persist semantics means
  // stale edges are wiped before the new snapshot lands, so the count
  // already reflects the latest snapshot.
  const sql = `
    WITH latest AS (
      SELECT DISTINCT ON (source_id)
        id,
        company_id,
        source_id,
        domain_id,
        source_kind,
        snapshot_hash,
        table_count,
        edge_count,
        metric_count,
        import_mode,
        imported_at
      FROM projection_external_catalog
      WHERE company_id = $1
      ORDER BY source_id, imported_at DESC
    ),
    upstream_counts AS (
      SELECT source_id, COUNT(*)::bigint AS upstream_count
      FROM projection_external_lineage
      WHERE company_id = $1
      GROUP BY source_id
    ),
    downstream_counts AS (
      SELECT source_id, COUNT(*)::bigint AS downstream_count
      FROM projection_external_lineage
      WHERE company_id = $1
      GROUP BY source_id
    )
    SELECT
      c.source_id::text     AS source_id,
      c.domain_id::text     AS domain_id,
      c.source_kind         AS source_kind,
      c.snapshot_hash       AS snapshot_hash,
      c.table_count         AS table_count,
      c.edge_count          AS edge_count,
      c.metric_count        AS metric_count,
      c.import_mode         AS import_mode,
      COALESCE(u.upstream_count, 0)   AS upstream_lineage_count,
      COALESCE(d.downstream_count, 0) AS downstream_lineage_count,
      c.imported_at         AS imported_at
    FROM latest c
    LEFT JOIN upstream_counts u    ON u.source_id = c.source_id
    LEFT JOIN downstream_counts d  ON d.source_id = c.source_id
    WHERE ${whereClause}
    ORDER BY c.imported_at DESC
    LIMIT ${limitParam}
  `;

  try {
    const res = await pgQuery<CatalogQueryRow>(sql, params);
    return res.rows.map(mapRow);
  } catch {
    // Honest empty: the table may not exist yet (no migrations run
    // on a fresh tenant), or the pool may be down. The page surfaces
    // the empty state in either case; we don't crash the request.
    return [];
  }
}

/**
 * Fetch the most-recent snapshot for a single source plus its upstream
 * and downstream lineage edges. Returns ``null`` when the source has
 * no catalog snapshot yet.
 */
export async function getCatalogTable(
  companyId: string,
  sourceId: string,
): Promise<CatalogTableDetail | null> {
  if (!postgresEnabled()) return null;

  const headerSql = `
    SELECT DISTINCT ON (source_id)
      source_id::text       AS source_id,
      domain_id::text       AS domain_id,
      source_kind           AS source_kind,
      snapshot_hash         AS snapshot_hash,
      table_count           AS table_count,
      edge_count            AS edge_count,
      metric_count          AS metric_count,
      import_mode           AS import_mode,
      imported_at           AS imported_at
    FROM projection_external_catalog
    WHERE company_id = $1
      AND source_id  = $2
    ORDER BY source_id, imported_at DESC
    LIMIT 1
  `;

  const lineageSql = `
    SELECT upstream, downstream
    FROM projection_external_lineage
    WHERE company_id = $1
      AND source_id  = $2
    ORDER BY upstream, downstream
  `;

  try {
    const headerRes = await pgQuery<
      Omit<CatalogQueryRow, "upstream_lineage_count" | "downstream_lineage_count">
    >(headerSql, [companyId, sourceId]);
    if (headerRes.rows.length === 0) return null;

    const lineageRes = await pgQuery<LineageEdgeRow>(lineageSql, [
      companyId,
      sourceId,
    ]);
    const edges = lineageRes.rows;

    const header = headerRes.rows[0];
    const reassembled: CatalogQueryRow = {
      ...header,
      upstream_lineage_count: edges.length,
      downstream_lineage_count: edges.length,
    } as CatalogQueryRow;
    const base = mapRow(reassembled);

    // For the detail view, "upstream" + "downstream" arrays are the
    // full edge set scoped to this source. v1 doesn't split by
    // node-resides-in-this-source because lineage edges reference
    // node fqns, not source UUIDs; the future detail page can layer
    // a column-level breakdown on top.
    return {
      ...base,
      upstreamEdges: edges,
      downstreamEdges: edges,
    };
  } catch {
    return null;
  }
}
