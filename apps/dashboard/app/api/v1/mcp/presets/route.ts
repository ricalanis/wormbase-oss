/**
 * POST /api/v1/mcp/presets — W2.A9.
 *
 * Proxies to worm-core's ``POST /api/v1/mcp/presets`` for the
 * /mcp Add MCP server wizard. Records the preset registration as a
 * ledger-tracked ``source_proposed`` entry tagged ``mcp:<kind>``.
 *
 * Body:
 *   {
 *     kind: string,                        // e.g. "notion" or "mcp:notion"
 *     serverUrl: string,                   // streamable-http MCP endpoint
 *     description?: string,
 *     suggestedDomain?: string,
 *     suggestedClassification?: "public" | "internal" | ...
 *   }
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { registerMcpPreset } from "../../../../../lib/server/worm-core-write";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  if (!me) {
    return NextResponse.json(
      {
        error: "no_admin_person",
        message:
          "no admin Person on this tenant; complete the install before registering MCP presets",
      },
      { status: 401 },
    );
  }

  let body: Record<string, unknown> = {};
  try {
    body = ((await req.json()) as Record<string, unknown>) ?? {};
  } catch {
    body = {};
  }
  const kind = typeof body.kind === "string" ? body.kind.trim() : "";
  const serverUrl =
    typeof body.serverUrl === "string" ? body.serverUrl.trim() : "";
  if (!kind || !serverUrl) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "kind and serverUrl are required",
      },
      { status: 400 },
    );
  }

  const description =
    typeof body.description === "string" ? body.description : "";
  const suggestedDomain =
    typeof body.suggestedDomain === "string"
      ? body.suggestedDomain
      : "general";
  const sc =
    typeof body.suggestedClassification === "string"
      ? body.suggestedClassification
      : "internal";
  const validClass = new Set([
    "public",
    "internal",
    "confidential",
    "pii",
    "regulated",
  ]);
  const suggestedClassification = (
    validClass.has(sc) ? sc : "internal"
  ) as
    | "public"
    | "internal"
    | "confidential"
    | "pii"
    | "regulated";

  try {
    const result = await registerMcpPreset({
      tenantSlug: tenant.slug,
      kind,
      serverUrl,
      description,
      suggestedDomain,
      suggestedClassification,
      proposedBy: me.personId,
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
