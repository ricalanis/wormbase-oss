/**
 * POST /api/v1/processes — dashboard wrapper for the worm-core
 * propose-process-map endpoint (W2.A7).
 *
 * The /processes tab's ``ProcessMapEditor`` posts here. Forwards through
 * ``proposeProcessMap`` (server-side bearer-token client) to worm-core
 * which runs the canonical PEVR cycle and lands ``emit_process_map_proposed``.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  proposeProcessMap,
  type ProcessMapStepArg,
} from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

interface IncomingStep {
  order?: unknown;
  actor?: unknown;
  action?: unknown;
  source_message_id?: unknown;
}

function normalizeSteps(
  raw: unknown,
): { ok: true; steps: ProcessMapStepArg[] } | { ok: false; message: string } {
  if (!Array.isArray(raw) || raw.length === 0) {
    return {
      ok: false,
      message: "steps must be a non-empty array",
    };
  }
  const out: ProcessMapStepArg[] = [];
  for (let i = 0; i < raw.length; i++) {
    const s = raw[i] as IncomingStep;
    const orderRaw = s?.order;
    const actor = typeof s?.actor === "string" ? s.actor.trim() : "";
    const action = typeof s?.action === "string" ? s.action.trim() : "";
    const sourceMessageId =
      typeof s?.source_message_id === "string" ? s.source_message_id : "";
    if (!actor || !action) {
      return {
        ok: false,
        message: `step ${i + 1}: actor and action are required`,
      };
    }
    let order: number;
    if (typeof orderRaw === "number" && Number.isFinite(orderRaw)) {
      order = Math.max(1, Math.trunc(orderRaw));
    } else {
      order = i + 1;
    }
    out.push({ order, actor, action, sourceMessageId });
  }
  return { ok: true, steps: out };
}

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
  const processName =
    typeof obj.process_name === "string" ? obj.process_name.trim() : "";
  if (!processName) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: process_name (non-empty string)",
      },
      { status: 400 },
    );
  }
  const stepsResult = normalizeSteps(obj.steps);
  if (!stepsResult.ok) {
    return NextResponse.json(
      { error: "validation_failed", message: stepsResult.message },
      { status: 400 },
    );
  }
  const domain =
    typeof obj.domain === "string" && obj.domain ? obj.domain : "general";
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
    const result = await proposeProcessMap({
      tenantSlug: tenant.slug,
      processName,
      steps: stepsResult.steps,
      domain,
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
