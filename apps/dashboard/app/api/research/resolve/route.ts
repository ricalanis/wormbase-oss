import { NextResponse } from "next/server";
import { resolveExperimentManually } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import type { ExperimentOutcome } from "../../../../lib/ledger-client.types";

/**
 * POST /api/research/resolve — operator override for an experiment outcome.
 *
 * Body: { experimentId: string, outcome: "keep" | "discard", rationale?: string }
 * Writes a fresh emit_experiment_resolved entry; the read-side picks up
 * the latest one (DISTINCT ON in getExperimentsForUser).
 */
export async function POST(req: Request) {
  const companyId = await getCurrentCompanyId();
  const body = (await req.json().catch(() => null)) as
    | { experimentId?: unknown; outcome?: unknown; rationale?: unknown }
    | null;
  const experimentId =
    typeof body?.experimentId === "string" ? body.experimentId : "";
  const outcomeRaw =
    typeof body?.outcome === "string" ? body.outcome : "";
  const rationale =
    typeof body?.rationale === "string" ? body.rationale : undefined;

  if (!experimentId || !outcomeRaw) {
    return NextResponse.json(
      { ok: false, error: "experimentId + outcome required" },
      { status: 400 },
    );
  }
  if (outcomeRaw !== "keep" && outcomeRaw !== "discard") {
    return NextResponse.json(
      { ok: false, error: "outcome must be 'keep' or 'discard'" },
      { status: 400 },
    );
  }
  const outcome = outcomeRaw as ExperimentOutcome;
  const receipt = await resolveExperimentManually(
    companyId,
    experimentId,
    outcome,
    rationale,
  );
  return NextResponse.json({ ok: true, receipt });
}
