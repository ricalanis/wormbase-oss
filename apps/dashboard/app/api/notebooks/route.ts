/**
 * /api/notebooks — GET list, POST propose.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { listNotebooks } from "../../../lib/server/notebooks";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  filterByDomainAccess,
  getDomainAccessSet,
} from "../../../lib/server/role-filter";
import { proposeNotebook } from "../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  const access = await getDomainAccessSet(tenant.companyId, me);
  const url = new URL(req.url);
  const all = await listNotebooks(tenant.companyId, {
    ownerPersonId: url.searchParams.get("owner_person_id") ?? undefined,
    domainId: url.searchParams.get("domain_id") ?? undefined,
    status: url.searchParams.get("status") ?? undefined,
  });
  const visible = filterByDomainAccess(all, me, access);
  return NextResponse.json({ notebooks: visible });
}

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const name = typeof obj.name === "string" ? obj.name.trim() : "";
  const kernel = typeof obj.kernel === "string" ? obj.kernel : "";
  const proposedByPersonId =
    typeof obj.proposed_by_person_id === "string"
      ? obj.proposed_by_person_id
      : "";
  if (!name || !kernel || !proposedByPersonId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: name, kernel, proposed_by_person_id",
      },
      { status: 400 },
    );
  }
  try {
    const result = await proposeNotebook({
      tenantSlug: tenant.slug,
      name,
      cells: Array.isArray(obj.cells)
        ? (obj.cells as Array<{ kind: string; source: string; language?: string }>)
        : [],
      kernel: kernel as "python_local" | "python_pandas" | "sql_postgres",
      proposedByPersonId,
      domainId: typeof obj.domain_id === "string" ? obj.domain_id : null,
    });
    return NextResponse.json(result, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
