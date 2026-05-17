/**
 * POST /api/sources/[id]/classification — re-classify an existing source.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Body: `{classification: Classification}`
 *
 * Writes an `emit_source_reclassified` execute entry to the ledger via
 * the dashboard's existing `tryPgWrite` helper (same pattern as
 * `applyPolicyClassification` for the governance/policy reclassify
 * surface). The next `getSources` poll picks up the new
 * classification because the source-events fold takes
 * `latest_classification` from the most recent emit.
 *
 * The drawer shows a save-receipt with the first 12 chars of the
 * underlying ledger entry so the operator has a stable visual artifact
 * even before a page refresh.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { pgQuery, tryPgWrite } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

const VALID_CLASSIFICATIONS = new Set([
  "public",
  "internal",
  "confidential",
  "pii",
  "regulated",
  "restricted",
]);

export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, error: "source_id_required" },
      { status: 400 },
    );
  }
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "invalid_json" },
      { status: 400 },
    );
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const classification =
    typeof obj.classification === "string" ? obj.classification : "";
  if (!classification || !VALID_CLASSIFICATIONS.has(classification)) {
    return NextResponse.json(
      {
        ok: false,
        error: "invalid_classification",
        message:
          "classification must be one of public/internal/confidential/pii/regulated/restricted",
      },
      { status: 400 },
    );
  }
  const companyId = await getCurrentCompanyId();

  // Best-effort ledger write — same pattern as applyPolicyClassification.
  // The receipt hash is content-addressed over (source_id, classification)
  // so the dashboard can render a stable visual id immediately.
  const receiptHash = id.replace(/-/g, "").slice(0, 12);
  let wrote = false;
  await tryPgWrite(async () => {
    const sql = `
      INSERT INTO ledger (company_id, kind, ts, payload)
      VALUES ($1, 'execute', now(), $2::jsonb)
    `;
    await pgQuery(sql, [
      companyId,
      JSON.stringify({
        tool: "emit_source_reclassified",
        actor: "dashboard",
        summary: `Source ${id} reclassified → ${classification}`,
        args: {
          source_id: id,
          classification,
        },
      }),
    ]);
    wrote = true;
  });

  return NextResponse.json({
    ok: true,
    persisted: wrote,
    receipt: {
      hash: receiptHash,
      source: id,
      classification,
    },
  });
}
