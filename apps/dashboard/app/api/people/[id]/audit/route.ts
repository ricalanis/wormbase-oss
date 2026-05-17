/**
 * GET /api/people/[id]/audit — chronological per-Person audit log.
 *
 * A5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Reads the last N ledger entries (any kind, any tool) tagged with
 * `payload->args->>person_id == :id`. Used by the PersonDetailDrawer to
 * surface the propose / confirm / archive / link / unlink / grant / revoke
 * trail for one Person.
 *
 * Returns 404 when the Person has no entries in this tenant — that's the
 * "Person not in tenant" case (A3 contract).
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  getAuditLogForPerson,
  getPersonById,
} from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const companyId = await getCurrentCompanyId();

  // A Person without any ledger entries in this tenant gets 404 to match
  // /api/people/[id]'s contract — the dashboard surfaces should not silently
  // present an empty audit log for a non-existent Person.
  const person = await getPersonById(companyId, id);
  if (!person) {
    return NextResponse.json(
      { error: "not_found", message: `no Person with id ${id} in this tenant` },
      { status: 404 },
    );
  }

  const url = new URL(req.url);
  const rawLimit = url.searchParams.get("limit");
  let limit = DEFAULT_LIMIT;
  if (rawLimit !== null) {
    const parsed = Number.parseInt(rawLimit, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
      limit = Math.min(parsed, MAX_LIMIT);
    }
  }

  const entries = await getAuditLogForPerson(companyId, id, limit);
  return NextResponse.json({ entries });
}
