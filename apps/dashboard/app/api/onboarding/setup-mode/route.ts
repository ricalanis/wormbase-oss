/**
 * POST /api/onboarding/setup-mode — proxy the wizard|bot choice.
 *
 * Block G4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Body: { mode: "wizard" | "bot" }. The handler resolves the current
 * Person (via getCurrentPerson) and proxies to worm-core's
 * POST /api/v1/setup-mode endpoint, which writes
 * emit_setup_mode_chosen via the canonical PEVR cycle.
 *
 * The (app)/layout redirect guard reads the resulting projection_installs
 * setup_mode column and routes onboarding traffic accordingly.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { getCurrentPerson } from "../../../../lib/server/identity";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

const DEFAULT_BASE = "http://worm-core:8910";

interface SetupModeBody {
  mode: "wizard" | "bot";
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: SetupModeBody;
  try {
    body = (await req.json()) as SetupModeBody;
  } catch (err) {
    return NextResponse.json(
      { error: "invalid_json", message: String(err) },
      { status: 400 },
    );
  }
  if (body.mode !== "wizard" && body.mode !== "bot") {
    return NextResponse.json(
      { error: "invalid_mode", hint: "mode must be 'wizard' or 'bot'" },
      { status: 422 },
    );
  }

  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    return NextResponse.json(
      { error: "no_current_person", hint: "complete Tier 1 install first" },
      { status: 401 },
    );
  }

  const base = (process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE).replace(
    /\/+$/,
    "",
  );
  const token = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!token) {
    return NextResponse.json(
      { error: "api_token_unset" },
      { status: 500 },
    );
  }

  let res: Response;
  try {
    res = await fetch(`${base}/api/v1/setup-mode`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify({
        mode: body.mode,
        chosen_by_person_id: me.personId,
      }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_unreachable",
        message: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  const text = await res.text();
  if (!res.ok) {
    return NextResponse.json(
      { error: "setup_mode_write_failed", status: res.status, body: text },
      { status: 502 },
    );
  }

  // Wizard path → /onboarding/tier2; bot path → / with banner.
  const redirect =
    body.mode === "wizard" ? "/onboarding/tier2" : "/";
  return NextResponse.json({ redirect, mode: body.mode }, { status: 200 });
}
