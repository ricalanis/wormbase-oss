/**
 * POST /api/v1/people/bulk-confirm — confirm a batch of pending Person proposals.
 *
 * W2.A6 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * The body is `{ person_ids: string[] }`. The current admin Person —
 * resolved server-side from the tenant cookie — becomes the
 * `confirmed_by` UUID on every confirmation. The route is a thin proxy
 * over worm-core's `POST /api/v1/people/bulk-confirm`, which writes one
 * independent PEVR cycle per id (4 ledger entries each).
 *
 * Atomicity contract: all-or-nothing on the wire. If worm-core's
 * orchestrator fails mid-batch, the upstream error surfaces as 502 and
 * the dashboard re-fetches the roster to show the partial state honestly.
 *
 * Returns the worm-core envelope `{confirmed_count, person_ids,
 * entry_ids}` on success.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { bulkConfirmPersons } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_json", message: "request body must be valid JSON" },
      { status: 400 },
    );
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const rawIds = Array.isArray(obj.person_ids) ? obj.person_ids : null;
  if (!rawIds || rawIds.length === 0) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: person_ids (non-empty array of UUID strings)",
      },
      { status: 400 },
    );
  }

  const personIds: string[] = [];
  for (const raw of rawIds) {
    if (typeof raw !== "string" || !UUID_RE.test(raw.trim())) {
      return NextResponse.json(
        {
          error: "validation_failed",
          message: `every entry of person_ids must be a UUID string; got ${JSON.stringify(raw)}`,
        },
        { status: 400 },
      );
    }
    personIds.push(raw.trim());
  }

  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    return NextResponse.json(
      {
        error: "not_authenticated",
        message:
          "no current admin Person resolved for tenant; finish onboarding first",
      },
      { status: 401 },
    );
  }

  try {
    const result = await bulkConfirmPersons({
      tenantSlug: tenant.slug,
      personIds,
      confirmedBy: me.personId,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_error",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }
}
