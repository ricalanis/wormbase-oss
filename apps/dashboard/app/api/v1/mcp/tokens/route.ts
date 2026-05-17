/**
 * POST /api/v1/mcp/tokens — W2.A9.
 *
 * Issue a Person-scoped compact bearer token the "Connect Claude
 * Desktop" panel surfaces as a copy-paste config snippet. The token
 * authenticates Claude Desktop's MCP client against the worm-core MCP
 * server (same compact format ``mcp_tools.auth.authorize_caller``
 * already accepts).
 *
 * Body (optional):
 *   { ttlSeconds?: number, label?: string, personId?: string }
 *
 * If ``personId`` is omitted, the token is minted for the current admin
 * (resolved via ``getCurrentPerson``). Admins can pass an explicit
 * ``personId`` to mint tokens for service accounts.
 *
 * Returns 200 with { token, person_id, tenant_slug, ttl_seconds,
 * issued_at, expires_at, label } on success.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { issueMcpToken } from "../../../../../lib/server/worm-core-write";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const companyId = await getCurrentCompanyId();

  let body: Record<string, unknown> = {};
  try {
    body = ((await req.json()) as Record<string, unknown>) ?? {};
  } catch {
    body = {};
  }
  const explicitPersonId =
    typeof body.personId === "string" && body.personId.length > 0
      ? body.personId
      : null;
  const ttlSeconds =
    typeof body.ttlSeconds === "number" && body.ttlSeconds > 0
      ? body.ttlSeconds
      : null;
  const label = typeof body.label === "string" ? body.label : "";

  let resolvedPersonId = explicitPersonId;
  if (!resolvedPersonId) {
    const me = await getCurrentPerson(companyId);
    if (!me) {
      return NextResponse.json(
        {
          error: "no_admin_person",
          message:
            "no admin Person on this tenant; complete the install before issuing MCP tokens",
        },
        { status: 401 },
      );
    }
    resolvedPersonId = me.personId;
  }

  try {
    const result = await issueMcpToken({
      tenantSlug: tenant.slug,
      personId: resolvedPersonId,
      ttlSeconds,
      label,
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
