/**
 * GET /api/v1/landing/replay — public hash-stable replay payload (Phase 4B).
 *
 * The landing page's HeroDemo client invokes this on the "Replay again"
 * button to demonstrate determinism: same `until_ts` → same hashes →
 * same on-screen receipts. The endpoint is unauthenticated by design
 * (the landing page is pre-signup) and reads the canonical demo
 * tenant's ledger window through ``getLandingReplay``.
 *
 * Caching is disabled (``Cache-Control: no-store``) so a click on
 * "Replay again" actually re-runs the SSR fold, demonstrating the
 * institutional-AI thesis instead of merely surfacing a cached blob.
 */
import { NextResponse } from "next/server";

import { getLandingReplay } from "../../../../../lib/server/landing-replay";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_req: Request): Promise<Response> {
  const replay = await getLandingReplay();
  return NextResponse.json(replay, {
    status: 200,
    headers: {
      "Cache-Control": "no-store",
      "X-Wormbase-Replay-Tenant": replay.tenantSlug,
      "X-Wormbase-Terminal-Hash": replay.terminalHashHex,
    },
  });
}
