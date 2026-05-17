/**
 * POST /onboarding/connect/{connector}/connect — Tier 1 connect handler.
 *
 * G3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Single endpoint that handles connector-first install for credential-paste
 * connectors. Body shape:
 *
 *   {
 *     identity: { name, email, position, orgSize },
 *     credentials: { ...connector-schema-fields }
 *   }
 *
 * Flow:
 *   1. proposeInstaller_FromForm → worm-core POST /api/v1/installs (writes
 *      Person + tenancy.installer + tenancy.admin + emit_install_completed).
 *   2. proposeSource → ledger-client (writes emit_source_proposed). The
 *      medallion cascade (bronze + silver + gold + KPI propose) fires
 *      asynchronously inside worm-core's medallion loop on the source_id.
 *   3. Returns { redirect: '/onboarding/whats-next' }.
 *
 * Capability honesty: a connector with status="coming_soon" rejects with
 * 400. The connector-first grid already prevents the click, but this guard
 * is defense in depth.
 *
 * Credentials never persist as plaintext: the rawCredential reaches
 * lib/server/install.ts → wrapBotToken which KMS-wraps before the worm-core
 * call. Ledger entries carry only the kms:// or vault:// reference.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { getConnectorByKind } from "../../../../../lib/lake-surfaces-catalog";
import { proposeInstaller_FromForm } from "../../../../../lib/server/install";
import { proposeSource } from "../../../../../lib/ledger-client";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

interface IdentityBody {
  name: string;
  email: string;
  position: string;
  orgSize: string;
}

interface ConnectBody {
  identity: IdentityBody;
  credentials: Record<string, string>;
}

function isString(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}

function deriveCredentialBlob(
  kind: string,
  creds: Record<string, string>,
): string {
  // Pack the schema fields into a single JSON blob; the wrapping
  // backend treats this opaquely. For OAuth-style connectors a single
  // ``api_key`` field is the whole credential; for DSN-style we serialize
  // the dict so a future un-wrap can reconstruct the parts.
  if (Object.keys(creds).length === 1) {
    const v = Object.values(creds)[0];
    if (isString(v)) return v;
  }
  return JSON.stringify(creds);
}

function deriveSourceUri(
  kind: string,
  creds: Record<string, string>,
): string {
  // Kind-specific URI synthesis from the credential schema. Mirrors the
  // shapes worm-core's connector classes expect.
  switch (kind) {
    case "postgres": {
      const dsn = (creds.dsn ?? "").trim();
      // Strip credentials from the URI we record in the ledger; the wrapped
      // token holds them. This is the public source URI.
      try {
        const u = new URL(dsn);
        u.username = "";
        u.password = "";
        return u.toString();
      } catch {
        return `postgres://(opaque)`;
      }
    }
    case "snowflake": {
      const account = (creds.account ?? "").trim() || "(account)";
      const database = (creds.database ?? "").trim() || "(database)";
      return `snowflake://${account}/${database}`;
    }
    case "http_csv":
      return (creds.url ?? "").trim() || "https://(url)";
    case "s3_csv": {
      const bucket = (creds.bucket ?? "").trim() || "(bucket)";
      const prefix = (creds.prefix ?? "").trim();
      return prefix ? `s3://${bucket}/${prefix}` : `s3://${bucket}`;
    }
    case "stripe":
      return "stripe://account";
    case "hubspot":
      return "hubspot://account";
    case "linear":
      return "linear://workspace";
    case "notion":
      return "notion://workspace";
    case "bigquery": {
      const project = (creds.project_id ?? "").trim() || "(project)";
      return `bigquery://${project}`;
    }
    case "gsheets": {
      const id = (creds.spreadsheet_id ?? "").trim() || "(sheet)";
      return `gsheets://${id}`;
    }
    case "salesforce":
      return (creds.instance_url ?? "").trim() || "https://(salesforce)";
    case "csv_local":
      return `file://${(creds.path ?? "").trim() || "(path)"}`;
    default:
      return `${kind}://(default)`;
  }
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ connector: string }> },
): Promise<NextResponse> {
  const { connector } = await ctx.params;
  const entry = getConnectorByKind(connector);
  if (!entry) {
    return NextResponse.json(
      { error: "unknown_connector", kind: connector },
      { status: 400 },
    );
  }
  if (entry.status === "coming_soon") {
    return NextResponse.json(
      {
        error: "connector_coming_soon",
        kind: connector,
        hint: entry.statusNote,
      },
      { status: 400 },
    );
  }

  let body: ConnectBody;
  try {
    body = (await req.json()) as ConnectBody;
  } catch (err) {
    return NextResponse.json(
      { error: "invalid_json", message: String(err) },
      { status: 400 },
    );
  }

  const id = body.identity ?? ({} as IdentityBody);
  if (!isString(id.name) || !isString(id.email) || !isString(id.position)) {
    return NextResponse.json(
      { error: "missing_identity", required: ["name", "email", "position"] },
      { status: 422 },
    );
  }

  const creds = body.credentials ?? {};
  for (const f of entry.fields) {
    if (f.required && !isString(creds[f.name])) {
      return NextResponse.json(
        { error: "missing_credential", field: f.name },
        { status: 422 },
      );
    }
  }

  const tenant = await getTenantFromCookies();
  const tenantSlug = tenant.slug;
  const blob = deriveCredentialBlob(entry.kind, creds);
  const uri = deriveSourceUri(entry.kind, creds);

  // Step 1: install orchestrator (Person + roles + install_completed).
  try {
    await proposeInstaller_FromForm({
      tenantSlug,
      connectorKind: entry.kind,
      installerName: id.name,
      installerEmail: id.email,
      installerPosition: id.position,
      installerOrgSize: id.orgSize ?? "",
      rawCredential: blob,
      scopes: entry.capabilities,
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: "install_failed",
        message: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  // Step 2: propose the source. The medallion loop in worm-core
  // observes emit_source_proposed and fires the bronze → silver → gold
  // cascade asynchronously.
  try {
    await proposeSource(
      tenantSlug,
      uri,
      id.email,
      "internal",
    );
  } catch (err) {
    return NextResponse.json(
      {
        error: "source_propose_failed",
        message: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  return NextResponse.json(
    {
      redirect: "/onboarding/whats-next",
      connector: entry.kind,
      uri,
    },
    { status: 200 },
  );
}
