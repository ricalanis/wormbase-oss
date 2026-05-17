/**
 * /api/data-products — GET list with role-aware filtering, POST propose.
 *
 * F3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { listDataProducts } from "../../../lib/server/data-products";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  filterByDomainAccess,
  getDomainAccessSet,
} from "../../../lib/server/role-filter";
import { proposeDataProduct } from "../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  const access = await getDomainAccessSet(tenant.companyId, me);
  const url = new URL(req.url);
  const filters = {
    requestedBy: url.searchParams.get("requested_by") ?? undefined,
    domainId: url.searchParams.get("domain_id") ?? undefined,
    kind: url.searchParams.get("kind") ?? undefined,
    status: url.searchParams.get("status") ?? undefined,
  };
  const all = await listDataProducts(tenant.companyId, filters);
  const visible = filterByDomainAccess(all, me, access);
  return NextResponse.json({ dataProducts: visible });
}

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_json" },
      { status: 400 },
    );
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const name = typeof obj.name === "string" ? obj.name.trim() : "";
  const kind = typeof obj.kind === "string" ? obj.kind.trim() : "";
  const requestedByPersonId =
    typeof obj.requested_by_person_id === "string"
      ? obj.requested_by_person_id
      : "";
  if (!name || !kind || !requestedByPersonId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: name, kind, requested_by_person_id",
      },
      { status: 400 },
    );
  }
  try {
    const result = await proposeDataProduct({
      tenantSlug: tenant.slug,
      name,
      kind,
      requestedByPersonId,
      sourcesRequired: Array.isArray(obj.sources_required)
        ? (obj.sources_required as string[])
        : [],
      domainId:
        typeof obj.domain_id === "string" ? obj.domain_id : null,
      parameters:
        typeof obj.parameters === "object" && obj.parameters !== null
          ? (obj.parameters as Record<string, unknown>)
          : {},
      promptedByMessageId:
        typeof obj.prompted_by_message_id === "string"
          ? obj.prompted_by_message_id
          : null,
      contentsBytesB64:
        typeof obj.contents_bytes_b64 === "string"
          ? obj.contents_bytes_b64
          : null,
    });
    return NextResponse.json(result, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
