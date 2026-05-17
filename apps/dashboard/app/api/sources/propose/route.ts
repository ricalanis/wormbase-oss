import { NextResponse } from "next/server";
import { proposeSource } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  OPAQUE_SECRET_CONNECTOR_KINDS,
  isOpaqueSecretKind,
} from "../../../../lib/opaque-secret-connectors";

/**
 * POST /api/sources/propose — dashboard onboarding propose-source action.
 *
 * Accepts an optional ``credential_ref`` (additive 2026-06-10): the
 * operator-provisioned broker slot key for opaque-secret connector
 * kinds (stripe / salesforce / hubspot / gsheets). When the connector
 * kind is opaque-secret AND no credential_ref is supplied, the route
 * still accepts the propose (the source can be progressed manually
 * later) but tags the receipt with ``credential_ref_missing: true``
 * so the operator-facing UI can surface a follow-up prompt.
 *
 * URI-shaped kinds (csv_local / postgres / snowflake / bigquery /
 * s3_csv / http_csv) ignore the field — the URI carries enough to
 * reconstruct the auth handle at sampling time.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as {
    uri: string;
    owner: string;
    classification: string;
    kind: string;
    credential_ref?: string | null;
  };
  const companyId = await getCurrentCompanyId();
  const credentialRef = body.credential_ref
    ? body.credential_ref.trim() || null
    : null;
  const opaque = isOpaqueSecretKind(body.kind);
  const credentialRefMissing = opaque && !credentialRef;
  const receipt = await proposeSource(
    companyId,
    body.uri,
    body.owner,
    body.classification,
    credentialRef
  );
  return NextResponse.json({
    ok: true,
    receipt,
    connector_kind: body.kind,
    opaque_secret_kind: opaque,
    credential_ref: credentialRef,
    credential_ref_missing: credentialRefMissing,
    opaque_secret_kinds: OPAQUE_SECRET_CONNECTOR_KINDS,
  });
}
