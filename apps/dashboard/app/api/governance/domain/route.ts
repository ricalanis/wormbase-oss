import { NextResponse } from "next/server";
import {
  assignDomainOwner,
  getDomains,
} from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

/**
 * Governance · domain mutation route.
 *
 * Today we accept owner reassignment (`owner_person_id`); future shapes can
 * add classification default, rename, etc. The handler writes a PEVR cycle
 * to the ledger via `assignDomainOwner` (which falls back to a synthetic
 * receipt when Postgres is unreachable). The dashboard /domains view polls
 * `/api/governance/domain` (GET) every 10s — see usePoll — so the audience
 * sees the worm "ratify" the change live.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as {
    domain_id: string;
    owner_person_id?: string;
  };
  if (!body?.domain_id) {
    return NextResponse.json(
      { ok: false, error: "domain_id required" },
      { status: 400 },
    );
  }
  const companyId = await getCurrentCompanyId();
  if (body.owner_person_id) {
    const receipt = await assignDomainOwner(
      companyId,
      body.domain_id,
      body.owner_person_id,
    );
    return NextResponse.json({ ok: true, receipt });
  }
  return NextResponse.json(
    { ok: false, error: "no mutation provided" },
    { status: 400 },
  );
}

/**
 * Live read for the polling client. Returns the current set of domains
 * (with owners + resource counts) so the /domains card grid can refresh
 * without a full RSC re-render.
 */
export async function GET() {
  const companyId = await getCurrentCompanyId();
  const domains = await getDomains(companyId);
  return NextResponse.json({ ok: true, domains });
}
