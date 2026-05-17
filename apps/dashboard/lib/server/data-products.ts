/**
 * Server-side helpers for the /data-products surface (F3).
 *
 * Reads via the SQL-fold helpers in `ledger-client.ts`; writes go through
 * the worm-core HTTP API via `worm-core-write.ts`. Mirrors the install /
 * identity helper pattern (Block A).
 */
import {
  getDataProducts,
  getDataProductById,
  getDataProductRuns,
  getDataProductConsumption,
  type DataProductFilters,
} from "../ledger-client";
import type {
  DataProductRow,
  DataProductRunRow,
  DataProductConsumptionRow,
} from "../ledger-client.types";

export type {
  DataProductRow,
  DataProductRunRow,
  DataProductConsumptionRow,
  DataProductFilters,
};

export async function listDataProducts(
  companyId: string,
  filters: DataProductFilters = {},
): Promise<DataProductRow[]> {
  return getDataProducts(companyId, filters);
}

export async function getDataProduct(
  companyId: string,
  dataProductId: string,
): Promise<DataProductRow | null> {
  return getDataProductById(companyId, dataProductId);
}

export async function listDataProductRuns(
  companyId: string,
  dataProductId: string,
): Promise<DataProductRunRow[]> {
  return getDataProductRuns(companyId, dataProductId);
}

export async function listDataProductConsumption(
  companyId: string,
  filters: { dataProductId?: string; personId?: string } = {},
): Promise<DataProductConsumptionRow[]> {
  return getDataProductConsumption(companyId, filters);
}
