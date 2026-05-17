/**
 * Server actions for /onboarding/connect/snowflake-catalog (Wave 3.2 Hole #2).
 *
 * "Import existing catalog" onboarding branch — ASML-shaped customers
 * with an existing Snowflake account can mirror their INFORMATION_SCHEMA /
 * tag references / policy graph through worm-core's CatalogMirror surface.
 * Submission routes through `importSnowflakeCatalog` which forwards to
 * worm-core's HTTP write API
 * (`POST ${apiUrl}/api/v1/write_actions/import_snowflake_catalog`).
 *
 * Required fields mirror `SnowflakeNativeCatalogSource.required_secrets`:
 *   * account (e.g. "abc12345.us-east-1.aws")
 *   * user
 *   * database
 *   * schema
 *   * warehouse
 *
 * Optional:
 *   * role — defaults to the user's default role when omitted
 *
 * The dashboard never holds the password / private key. Credential capture
 * happens server-side via the CredentialBroker; this action only passes
 * the *shape* of the connection (account + user + scope + warehouse +
 * role) plus the binding domain.
 */
"use server";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../lib/ledger-client";

export interface ImportSnowflakeCatalogFormData {
  account: string;
  user: string;
  database: string;
  schema: string;
  warehouse: string;
  /** Optional Snowflake role; falls back to the user's default role. */
  role?: string;
  domainId: string;
}

export interface ImportSnowflakeCatalogResult {
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

const REQUIRED_FIELDS: Array<keyof ImportSnowflakeCatalogFormData> = [
  "account",
  "user",
  "database",
  "schema",
  "warehouse",
];

/**
 * Admin-only: import an existing Snowflake INFORMATION_SCHEMA + tag /
 * policy graph as a CatalogMirror source. Credentials are captured by the
 * worm-core CredentialBroker out-of-band; the dashboard form only carries
 * the connection shape and the binding domain id.
 */
export async function importSnowflakeCatalog(
  formData: ImportSnowflakeCatalogFormData,
): Promise<ImportSnowflakeCatalogResult> {
  // 1. Argument sanity.
  const normalized: Record<string, string> = {};
  for (const k of REQUIRED_FIELDS) {
    const v = (formData[k] ?? "").trim();
    if (!v) {
      return { ok: false, error: `missing ${k}` };
    }
    if (v.length > 256) {
      return { ok: false, error: `${k} exceeds 256 chars` };
    }
    normalized[k] = v;
  }
  const role = (formData.role ?? "").trim();
  if (role && role.length > 256) {
    return { ok: false, error: "role exceeds 256 chars" };
  }
  const domainId = (formData.domainId ?? "").trim();
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

  // 3. Forward to worm-core write API.
  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "import_snowflake_catalog endpoint v1.1 (no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/write_actions/import_snowflake_catalog`;
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
        account: normalized.account,
        user: normalized.user,
        database: normalized.database,
        schema: normalized.schema,
        warehouse: normalized.warehouse,
        role: role || null,
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
        "import_snowflake_catalog endpoint v1.1 (worm-core has not exposed " +
        "POST /api/v1/write_actions/import_snowflake_catalog yet)",
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
