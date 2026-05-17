import { NextResponse } from "next/server";
import { getPeople } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

/**
 * People list — used by the inline owner dropdown on /domains. Returns the
 * tenant's people so the client can populate the change-owner UI without
 * shipping the full ledger client to the browser bundle.
 */
export async function GET() {
  const companyId = await getCurrentCompanyId();
  const people = await getPeople(companyId);
  return NextResponse.json({ ok: true, people });
}
