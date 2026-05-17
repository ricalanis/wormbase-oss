import { NextResponse } from "next/server";
import {
  applyPolicyClassification,
  getPolicies,
} from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

const VALID_CLASSIFICATIONS = new Set([
  "public",
  "internal",
  "confidential",
  "pii",
  "regulated",
  "restricted",
]);

/**
 * Governance · policy mutation route.
 *
 * Re-emits `emit_policy_applied` with a new classification. The read-side
 * (`getPolicies`) picks the latest entry per `policy_id`, so the next poll
 * (10s on /policies) renders the new classification with a live receipt.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as {
    policy_id: string;
    classification?: string;
  };
  if (!body?.policy_id) {
    return NextResponse.json(
      { ok: false, error: "policy_id required" },
      { status: 400 },
    );
  }
  if (
    !body.classification ||
    !VALID_CLASSIFICATIONS.has(body.classification)
  ) {
    return NextResponse.json(
      { ok: false, error: "classification required (one of public/internal/confidential/pii/regulated)" },
      { status: 400 },
    );
  }
  const companyId = await getCurrentCompanyId();
  const receipt = await applyPolicyClassification(
    companyId,
    body.policy_id,
    body.classification,
  );
  return NextResponse.json({ ok: true, receipt });
}

export async function GET() {
  const companyId = await getCurrentCompanyId();
  const policies = await getPolicies(companyId);
  return NextResponse.json({ ok: true, policies });
}
