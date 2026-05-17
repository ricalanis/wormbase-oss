/**
 * /api/people/[id]/roles — read + grant (across all three facets).
 *
 * A3 / A3.5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * GET returns `{roles: PersonRoleGrant[]}` — only unrevoked grants.
 *
 * POST grants a role on one of three facets:
 *   - tenancy: role ∈ {installer, admin, member, observer}
 *   - domain:  role ∈ {owner, contributor}, requires scope_id (domain_id)
 *   - resource: role ∈ {maintainer, contributor}, requires scope_id and scope_type
 *
 * Calls worm-core's `POST /api/v1/people/{id}/roles`, which writes a full
 * PEVR cycle for the matching emit_*_role_assigned payload.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getRolesForPerson } from "../../../../../lib/ledger-client";
import {
  grantRole,
  type RoleFacet,
} from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

const VALID_FACETS: ReadonlySet<RoleFacet> = new Set([
  "tenancy",
  "domain",
  "resource",
]);

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const roles = await getRolesForPerson(tenant.companyId, id);
  return NextResponse.json({ roles });
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
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
  const facet = typeof obj.facet === "string" ? obj.facet : "";
  const role = typeof obj.role === "string" ? obj.role : "";
  const grantedBy = typeof obj.granted_by === "string" ? obj.granted_by : "";
  const scopeId =
    typeof obj.scope_id === "string" && obj.scope_id ? obj.scope_id : null;
  const scopeType =
    typeof obj.scope_type === "string" && obj.scope_type
      ? obj.scope_type
      : null;
  if (!VALID_FACETS.has(facet as RoleFacet) || !role || !grantedBy) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: facet ∈ {tenancy,domain,resource}, role, granted_by (uuid)",
      },
      { status: 400 },
    );
  }
  if ((facet === "domain" || facet === "resource") && !scopeId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: `${facet} grants require scope_id`,
      },
      { status: 400 },
    );
  }
  if (facet === "resource" && !scopeType) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "resource grants require scope_type",
      },
      { status: 400 },
    );
  }
  try {
    const result = await grantRole(id, {
      tenantSlug: tenant.slug,
      facet: facet as RoleFacet,
      role,
      scopeId,
      scopeType,
      grantedBy,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
