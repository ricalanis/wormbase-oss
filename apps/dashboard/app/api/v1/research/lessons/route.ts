/**
 * GET /api/v1/research/lessons — Demo-day P9.
 *
 * Returns the trailing ``experiment_lesson`` ledger entries for the
 * current tenant, grouped by scope (person / team / company). Reads
 * ``emit_experiment_lesson`` rows via ``getExperimentLessonsByScope``
 * (latest-per-prior_keep_id wins so ``applied_at`` stamps overwrite
 * the original ``None`` extraction).
 *
 * Query params:
 *   ?scope=<person|team|company>   filter to a single scope; flat list
 *   ?limit=<n>                     trailing entries per scope (default 5)
 *
 * Response shapes:
 *   - Without ?scope: { ok, byScope: { person, team, company }, ... }
 *   - With    ?scope: { ok, scope, rows, ... }
 *
 * Empty state: returns ``[]`` (or empty arrays inside ``byScope``) when no
 * lessons exist — never a fixture (CLAUDE.md ¶9). The card renders an
 * honest "the worm has not learnt yet" message.
 */
import { NextResponse } from "next/server";
import { getExperimentLessons, getExperimentLessonsByScope } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import type { LessonScope } from "../../../../../lib/ledger-client.types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const SCOPES: ReadonlyArray<LessonScope> = ["person", "team", "company"];

export async function GET(req: Request) {
  const url = new URL(req.url);
  const limitRaw = url.searchParams.get("limit");
  const limit = limitRaw ? Math.max(1, parseInt(limitRaw, 10) || 5) : 5;
  const scopeRaw = url.searchParams.get("scope");

  const companyId = await getCurrentCompanyId();

  if (scopeRaw) {
    if (!SCOPES.includes(scopeRaw as LessonScope)) {
      return NextResponse.json(
        { ok: false, error: `scope must be one of ${SCOPES.join(", ")}` },
        { status: 400 },
      );
    }
    const rows = await getExperimentLessons(
      companyId,
      scopeRaw as LessonScope,
      limit,
    );
    return NextResponse.json({
      ok: true,
      scope: scopeRaw,
      rows,
      limit,
      fetchedAt: Date.now(),
    });
  }

  const byScope = await getExperimentLessonsByScope(companyId, limit);
  return NextResponse.json({
    ok: true,
    byScope,
    limit,
    fetchedAt: Date.now(),
  });
}
