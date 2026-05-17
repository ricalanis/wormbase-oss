/**
 * GET /api/v1/research/first-knowings — Demo-day P12.
 *
 * Returns un-confirmed worm-detected phenomena for the current tenant.
 * Altman Q1 made readable: "What does the worm know that the org's CDO
 * doesn't, with the ledger entry where it knew it first?"
 *
 * Query params (filter chips, all optional):
 *   ?kind=<phenomenon-kind[,phenomenon-kind...]>    csv-of phenomenon kinds
 *   ?scope=<mine|team|company>                       single scope
 *   ?recency=<1h|24h|7d|all>                         trailing window
 *   ?limit=<n>                                       cap result rows (default 50)
 *
 * Response:
 *   { ok, rows, fetchedAt }
 *
 * Empty state: returns ``[]`` when no first-knowings exist (CLAUDE.md ¶9 —
 * dashboard tab renders an honest "no first-knowings" message).
 */
import { NextResponse } from "next/server";
import { getFirstKnowings } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import type {
  FirstKnowingPhenomenonKind,
  FirstKnowingRecency,
  FirstKnowingScope,
} from "../../../../../lib/ledger-client.types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const KINDS: ReadonlyArray<FirstKnowingPhenomenonKind> = [
  "kpi_gap",
  "domain_gap",
  "process_gap",
  "reactivity_gap",
  "person_gap",
];

const SCOPES: ReadonlyArray<FirstKnowingScope> = ["mine", "team", "company"];
const RECENCIES: ReadonlyArray<FirstKnowingRecency> = ["1h", "24h", "7d", "all"];

export async function GET(req: Request) {
  const url = new URL(req.url);

  const kindRaw = url.searchParams.get("kind");
  const kinds: FirstKnowingPhenomenonKind[] | undefined = kindRaw
    ? kindRaw
        .split(",")
        .map((s) => s.trim())
        .filter((s): s is FirstKnowingPhenomenonKind =>
          KINDS.includes(s as FirstKnowingPhenomenonKind),
        )
    : undefined;

  const scopeRaw = url.searchParams.get("scope");
  let scope: FirstKnowingScope | undefined;
  if (scopeRaw) {
    if (!SCOPES.includes(scopeRaw as FirstKnowingScope)) {
      return NextResponse.json(
        { ok: false, error: `scope must be one of ${SCOPES.join(", ")}` },
        { status: 400 },
      );
    }
    scope = scopeRaw as FirstKnowingScope;
  }

  const recencyRaw = url.searchParams.get("recency");
  let recency: FirstKnowingRecency = "all";
  if (recencyRaw) {
    if (!RECENCIES.includes(recencyRaw as FirstKnowingRecency)) {
      return NextResponse.json(
        { ok: false, error: `recency must be one of ${RECENCIES.join(", ")}` },
        { status: 400 },
      );
    }
    recency = recencyRaw as FirstKnowingRecency;
  }

  const limitRaw = url.searchParams.get("limit");
  const limit = limitRaw ? Math.max(1, parseInt(limitRaw, 10) || 50) : 50;

  const companyId = await getCurrentCompanyId();
  const rows = await getFirstKnowings(companyId, {
    kinds,
    scope,
    recency,
    limit,
  });

  return NextResponse.json({
    ok: true,
    rows,
    fetchedAt: Date.now(),
  });
}
