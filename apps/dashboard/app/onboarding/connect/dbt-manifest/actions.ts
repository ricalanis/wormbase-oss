/**
 * Server actions for /onboarding/connect/dbt-manifest (Wave 3.2 Hole #2).
 *
 * "Import existing catalog" onboarding branch — ASML-shaped customers
 * (existing dbt project) can self-serve through onboarding without
 * falling back to the admin CLI. Submission routes through
 * `importDbtManifest` which forwards to worm-core's HTTP write API
 * (`POST ${apiUrl}/api/v1/write_actions/import_dbt_catalog`).
 *
 * Architectural contract (mirrors `/people/agents/new/actions.ts`):
 *
 *   * Dashboard reads ledger truth — it does NOT direct-write the ledger.
 *     The import path goes through the worm-core HTTP write API. If the
 *     endpoint is not wired yet, the action returns a stub error so the
 *     surface degrades honestly ("import_dbt_catalog endpoint v1.1") rather
 *     than silently faking the write.
 *
 *   * Admin role check is enforced inline. Defense in depth: the page
 *     short-circuits to a 403-ish "admin required" panel before rendering
 *     the form; the action re-checks before forwarding to worm-core.
 *
 * Production graduation criterion: when worm-core exposes
 * `POST /api/v1/write_actions/import_dbt_catalog`, the stub-error branch
 * never fires; the action returns `{ok: true, sourceId}` and the form
 * redirects to `/sources`.
 */
"use server";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../lib/ledger-client";

export interface ImportDbtManifestFormData {
  manifestUri: string;
  domainId: string;
}

export interface ImportDbtManifestResult {
  ok: boolean;
  sourceId?: string;
  error?: string;
}

function readBase(): string {
  const raw = (
    process.env.WORM_CORE_API_URL ?? process.env.WORMBASE_LEDGER_API_BASE ?? ""
  ).trim();
  return raw.replace(/\/+$/, "");
}

function readToken(): string {
  return (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
}

/**
 * Admin-only: import an existing dbt project manifest as a CatalogMirror
 * source. The manifest URI may be a local path, an https URL, or a
 * `dbt-cloud://` reference resolved by worm-core. The domain id binds the
 * imported tables to a governance domain at ingest time.
 */
export async function importDbtManifest(
  formData: ImportDbtManifestFormData,
): Promise<ImportDbtManifestResult> {
  // 1. Argument sanity.
  const manifestUri = (formData.manifestUri ?? "").trim();
  const domainId = (formData.domainId ?? "").trim();
  if (!manifestUri) {
    return { ok: false, error: "missing manifest_uri" };
  }
  if (manifestUri.length > 1024) {
    return { ok: false, error: "manifest_uri exceeds 1024 chars" };
  }
  if (!domainId) {
    return { ok: false, error: "missing domain_id" };
  }

  // 2. Admin role check (tenancy.admin OR tenancy.installer).
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);
  if (!person) {
    return { ok: false, error: "no authenticated person" };
  }
  if (person.tenancyRole !== "admin" && person.tenancyRole !== "installer") {
    let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
    try {
      grants = await getRolesForPerson(companyId, person.personId);
    } catch {
      grants = [];
    }
    const live = grants
      .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
      .map((g) => g.role);
    if (!live.includes("admin") && !live.includes("installer")) {
      return { ok: false, error: "admin role required" };
    }
  }

  // 3. Forward to worm-core write API (the only ledger-write path).
  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "import_dbt_catalog endpoint v1.1 (no WORM_CORE_API_URL configured)",
    };
  }
  const token = readToken();
  if (!token) {
    return {
      ok: false,
      error:
        "WORMBASE_LEDGER_API_TOKEN not set — refusing to call worm-core write API",
    };
  }

  const tenant = await getTenantFromCookies();
  const url = `${base}/api/v1/write_actions/import_dbt_catalog`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify({
        manifest_uri: manifestUri,
        domain_id: domainId,
        imported_by: person.personId,
        company_id: companyId,
      }),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error:
        "import_dbt_catalog endpoint v1.1 (worm-core has not exposed " +
        "POST /api/v1/write_actions/import_dbt_catalog yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }

  let body: { source_id?: string; sourceId?: string } = {};
  try {
    body = (await res.json()) as {
      source_id?: string;
      sourceId?: string;
    };
  } catch {
    return { ok: false, error: "worm-core API returned non-JSON body" };
  }
  const sourceId = body.sourceId ?? body.source_id;
  if (!sourceId) {
    return { ok: false, error: "worm-core API did not return source_id" };
  }
  return { ok: true, sourceId };
}

// Re-export for tests so they can stub the base/token reading.
export const __test__ = {
  readBase,
  readToken,
};
