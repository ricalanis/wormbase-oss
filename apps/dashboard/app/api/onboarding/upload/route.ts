/**
 * POST /api/onboarding/upload — multipart CSV upload (Block G3 / PRD §17).
 *
 * Body: multipart/form-data with two fields:
 *   - file:     the CSV bytes (≤ 25 MB)
 *   - identity: JSON-stringified IdentitySubmitArgs (name + email + position
 *               + orgSize)
 *
 * Flow:
 *   1. Parse multipart with Next 15's built-in formData() reader.
 *   2. Enforce 25 MB cap.
 *   3. Write the bytes to a tenant-scoped path under WORMBASE_UPLOAD_DIR
 *      (defaults to /tmp/wormbase-uploads/{tenantSlug}/...). In production
 *      with WORMBASE_S3_BUCKET set, this same path resolves into an S3
 *      key — the storage backend abstraction lives in worm-core; here we
 *      write to the equivalent local filesystem path.
 *   4. proposeInstaller_FromForm via the new helper.
 *   5. proposeSource pointing at the file URI.
 *   6. Returns { redirect: "/onboarding/whats-next" }.
 *
 * Uploaded bytes never reach Claude / inference — they live as raw bytes
 * the worm-core medallion loop fetches lazily for profiling.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { proposeInstaller_FromForm } from "../../../../lib/server/install";
import { proposeSource } from "../../../../lib/ledger-client";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
// Next 15 default body-size on app router routes; we additionally guard
// at the handler level.
export const maxDuration = 60;

const MAX_BYTES = 25 * 1024 * 1024;

function uploadDirRoot(): string {
  const env = (process.env.WORMBASE_UPLOAD_DIR ?? "").trim();
  return env || "/tmp/wormbase-uploads";
}

function safeFilename(name: string): string {
  // Strip any path separators / hidden-file dots; keep extension.
  const base = name.split(/[\\/]/).pop() ?? "upload.csv";
  return base.replace(/^\.+/, "_").replace(/[^A-Za-z0-9._-]/g, "_");
}

interface IdentityBody {
  name: string;
  email: string;
  position: string;
  orgSize: string;
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  let form: FormData;
  try {
    form = await req.formData();
  } catch (err) {
    return NextResponse.json(
      { error: "invalid_multipart", message: String(err) },
      { status: 400 },
    );
  }

  const fileEntry = form.get("file");
  if (!(fileEntry instanceof File)) {
    return NextResponse.json(
      { error: "missing_file", hint: "field name must be 'file'" },
      { status: 400 },
    );
  }
  if (fileEntry.size > MAX_BYTES) {
    return NextResponse.json(
      {
        error: "file_too_large",
        hint: `file is ${(fileEntry.size / 1024 / 1024).toFixed(1)} MB; cap is 25 MB`,
      },
      { status: 413 },
    );
  }

  const identityRaw = form.get("identity");
  if (typeof identityRaw !== "string") {
    return NextResponse.json(
      { error: "missing_identity", hint: "field name must be 'identity'" },
      { status: 400 },
    );
  }
  let identity: IdentityBody;
  try {
    identity = JSON.parse(identityRaw) as IdentityBody;
  } catch (err) {
    return NextResponse.json(
      { error: "invalid_identity_json", message: String(err) },
      { status: 400 },
    );
  }
  if (
    !identity.name ||
    !identity.email ||
    !identity.position ||
    !identity.orgSize
  ) {
    return NextResponse.json(
      { error: "incomplete_identity" },
      { status: 422 },
    );
  }

  const tenant = await getTenantFromCookies();
  const tenantSlug = tenant.slug;
  const safeName = safeFilename(fileEntry.name);
  const dir = join(uploadDirRoot(), tenantSlug);
  await mkdir(dir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const fname = `${stamp}-${safeName}`;
  const fpath = join(dir, fname);

  // Write bytes.
  try {
    const buf = Buffer.from(await fileEntry.arrayBuffer());
    await writeFile(fpath, buf);
  } catch (err) {
    return NextResponse.json(
      { error: "write_failed", message: String(err) },
      { status: 502 },
    );
  }

  // Step 1: install orchestrator.
  try {
    await proposeInstaller_FromForm({
      tenantSlug,
      connectorKind: "csv_local",
      installerName: identity.name,
      installerEmail: identity.email,
      installerPosition: identity.position,
      installerOrgSize: identity.orgSize,
      // For CSV upload, the credential-blob is just the file path —
      // there's no API token to wrap. The wrapping path still produces a
      // vault:// reference so the install ledger entry has a valid grant ref.
      rawCredential: fpath,
      scopes: ["profile", "sample"],
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

  // Step 2: propose the source. Medallion loop fires off this entry.
  try {
    await proposeSource(
      tenantSlug,
      `file://${fpath}`,
      identity.email,
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
      filename: fname,
      bytes: fileEntry.size,
    },
    { status: 200 },
  );
}
