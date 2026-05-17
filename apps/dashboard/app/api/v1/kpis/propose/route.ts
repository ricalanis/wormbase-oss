/**
 * POST /api/v1/kpis/propose — dashboard wrapper for the worm-core
 * KPI propose endpoint (W2.A7).
 *
 * The /kpis tab's ``ProposeKpiModal`` posts here. The handler resolves
 * the tenant from the cookie, validates the body, and forwards through
 * ``proposeKpi`` (server-side bearer-token client) to worm-core which
 * runs the canonical PEVR cycle and lands ``emit_kpi_proposed``.
 *
 * Errors:
 *   - 400 invalid JSON / missing fields (``label`` is the only required
 *     field; ``formula`` defaults to "" and ``unit`` to "count").
 *   - 502 if worm-core returns 4xx/5xx — preserves the canonical message.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proposeKpi } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

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
  const label = typeof obj.label === "string" ? obj.label.trim() : "";
  if (!label) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: label (non-empty string)",
      },
      { status: 400 },
    );
  }
  const formula =
    typeof obj.formula === "string" ? obj.formula : "";
  const unit = typeof obj.unit === "string" && obj.unit ? obj.unit : "count";
  const sourceIds =
    Array.isArray(obj.source_ids)
      ? obj.source_ids.filter((s): s is string => typeof s === "string")
      : [];
  const ownerPosition =
    typeof obj.owner_position === "string" && obj.owner_position
      ? obj.owner_position
      : null;
  const proposedBy =
    typeof obj.proposed_by === "string" && obj.proposed_by
      ? obj.proposed_by
      : "dashboard-admin";

  try {
    const result = await proposeKpi({
      tenantSlug: tenant.slug,
      label,
      formula,
      unit,
      sourceIds,
      ownerPosition,
      proposedBy,
    });
    return NextResponse.json(result, { status: 201 });
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
