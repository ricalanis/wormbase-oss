/**
 * Catalog-mirror Wave 2 shared accessor (2026-06-10).
 *
 * One small helper used by both /lake/catalog-drift and
 * /lake/entity-stitches to probe whether the Wave 2 substrate
 * (``projection_catalog_tables`` from migration v029) has been
 * populated for a tenant.
 *
 * The L2 + L8 strategy banners both rely on the same upstream signal:
 *
 *   * **L2 TableSet / ColumnSet / ColumnType** — graduate from
 *     ``configured · awaiting-per-table-entries`` to
 *     ``productive · per-connector`` once at least one
 *     ``catalog_table_imported`` entry has been folded into
 *     ``projection_catalog_tables`` for the tenant.
 *   * **L8 SchemaShape** — drops the "currently quiet — awaits
 *     per-column catalog imports" qualifier once the same probe trips.
 *
 * Both banners read this single accessor instead of duplicating the
 * SQL. Honest 0 when DATABASE_URL is unset, the projection is empty,
 * or the query throws — banners surface as ``awaiting`` in that case.
 *
 * Per the extractor-registry doctrine, ``columns=()`` is a valid
 * honest-empty-upstream payload — some connectors land per-table
 * entries WITHOUT column data (e.g. opaque-secret connectors that
 * don't have a registered catalog_column_extractor). The probe counts
 * rows in ``projection_catalog_tables``, NOT rows with non-empty
 * columns, because banner posture flips on the presence of per-table
 * entries — the column-level extractor coverage is a per-connector
 * concern surfaced separately.
 */

import { pgQuery } from "./ledger-client";

function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

/**
 * Count the rows in ``projection_catalog_tables`` for a tenant. The
 * projection is populated by the Wave 2 catalog_table_imported fold;
 * one row per (company_id, source_id, table_id, snapshot_hash) tuple.
 *
 * Returns ``0`` when:
 *   * ``DATABASE_URL`` / ``WORMBASE_LEDGER_DSN`` are both unset
 *   * the query throws (e.g. migration v029 hasn't run on this DB)
 *   * the projection genuinely has no entries yet
 *
 * Tenant-scoped via ``companyId``. Multi-tenant safe — the SQL
 * filters by ``company_id``; no cross-tenant data leaks.
 */
export async function getCatalogTableImportCount(
  companyId: string,
): Promise<number> {
  if (!postgresEnabled()) return 0;
  const sql = `
    SELECT COUNT(*)::int AS n
    FROM projection_catalog_tables
    WHERE company_id = $1
  `;
  try {
    const res = await pgQuery<{ n: number | string }>(sql, [companyId]);
    if (res.rows.length === 0) return 0;
    const raw = res.rows[0].n;
    const parsed =
      typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  } catch {
    return 0;
  }
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
};
