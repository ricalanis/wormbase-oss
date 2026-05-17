/**
 * Server-side helpers for the /notebooks surface (F4).
 *
 * Reads via the SQL-fold helpers in `ledger-client.ts`; writes (run + publish)
 * go through the worm-core HTTP API via `worm-core-write.ts`.
 */
import {
  getNotebooks,
  getNotebookById,
  getNotebookRuns,
  type NotebookFilters,
} from "../ledger-client";
import type {
  NotebookRow,
  NotebookRunRow,
} from "../ledger-client.types";

export type { NotebookRow, NotebookRunRow, NotebookFilters };

export async function listNotebooks(
  companyId: string,
  filters: NotebookFilters = {},
): Promise<NotebookRow[]> {
  return getNotebooks(companyId, filters);
}

export async function getNotebook(
  companyId: string,
  notebookId: string,
): Promise<NotebookRow | null> {
  return getNotebookById(companyId, notebookId);
}

export async function listNotebookRuns(
  companyId: string,
  notebookId: string,
): Promise<NotebookRunRow[]> {
  return getNotebookRuns(companyId, notebookId);
}
