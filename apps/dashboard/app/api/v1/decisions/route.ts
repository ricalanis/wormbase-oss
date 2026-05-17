/**
 * POST /api/v1/decisions — dashboard wrapper for the worm-core
 * record-decision endpoint (W2.A7).
 *
 * The /decisions tab's ``DecisionDetailDrawer`` (in "Record decision"
 * mode) posts here. Forwards through ``recordDecision`` (server-side
 * bearer-token client) to worm-core which runs the canonical PEVR cycle
 * and lands ``emit_decision_recorded``.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { recordDecision } from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

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
  const decisionText =
    typeof obj.decision_text === "string" ? obj.decision_text.trim() : "";
  const channelId =
    typeof obj.channel_id === "string" ? obj.channel_id.trim() : "";
  if (!decisionText || !channelId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: decision_text, channel_id (non-empty strings)",
      },
      { status: 400 },
    );
  }
  const decidedByPersons = Array.isArray(obj.decided_by_persons)
    ? obj.decided_by_persons.filter((s): s is string => typeof s === "string")
    : [];
  const evidenceMessageIds = Array.isArray(obj.evidence_message_ids)
    ? obj.evidence_message_ids.filter(
        (s): s is string => typeof s === "string",
      )
    : [];
  const confidence =
    typeof obj.confidence === "number" &&
    obj.confidence >= 0 &&
    obj.confidence <= 1
      ? obj.confidence
      : 0.95;
  const proposedBy =
    typeof obj.proposed_by === "string" && obj.proposed_by
      ? obj.proposed_by
      : "dashboard-admin";

  try {
    const result = await recordDecision({
      tenantSlug: tenant.slug,
      decisionText,
      channelId,
      decidedByPersons,
      evidenceMessageIds,
      confidence,
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
