/**
 * Server actions for /people/agents/new (Wave 3.2 Hole #1).
 *
 * The registration form on `/people/agents/new` calls ``registerAgent`` to
 * create a new Agent (Person sub-type) for an external provider plus an
 * initial set of grants (domain.read, optional model.access budget).
 *
 * Architectural contract (mirrors `/lake/metrics-proposed/actions.ts`):
 *
 *   * Dashboard reads ledger truth — it does NOT direct-write the ledger.
 *     The registration path goes through the worm-core HTTP write API
 *     (`POST ${apiUrl}/write_actions/register_agent`). If the endpoint
 *     is not wired yet, the action returns a stub error so the surface
 *     degrades honestly ("register_agent endpoint v1.1; register via the
 *     admin CLI for now") rather than silently faking the write.
 *
 *   * Admin role check is enforced inline. Defense in depth: the page
 *     short-circuits to a 403-ish "admin required" panel before rendering
 *     the form; the action re-checks before forwarding to worm-core. A
 *     misconfigured route or a directly-POSTed form payload cannot bypass
 *     the gate.
 *
 * Production graduation criterion: when worm-core exposes
 * `POST /api/v1/write_actions/register_agent`, the stub-error branch
 * never fires; the action returns `{ok: true, agentId}` and the form
 * redirects to `/people/agents/[id]`.
 */
"use server";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../../lib/ledger-client";

export type AgentExternalProvider =
  | "claude"
  | "openai"
  | "kimi"
  | "internal_worm"
  | "other";

export interface RegisterAgentFormData {
  externalProvider: AgentExternalProvider;
  displayName: string;
  domainReadIds: string[];
  /** Decimal-as-string for NUMERIC(18,4) round-trip; empty/undefined means no
   *  model.access grant. */
  modelAccessBudgetUsd?: string;
}

export interface RegisterAgentResult {
  ok: boolean;
  agentId?: string;
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
 * Admin-only: register a new Agent (Person sub-type) for an external
 * provider plus an initial set of grants.
 *
 * Wave 3.2 surface:
 *
 *   * Verifies the caller holds an unrevoked ``tenancy.admin`` (or
 *     ``tenancy.installer``) grant.
 *   * Forwards to ``${worm-core}/api/v1/write_actions/register_agent``
 *     when ``WORM_CORE_API_URL`` / ``WORMBASE_LEDGER_API_BASE`` is set.
 *   * Returns ``{ok: false, error: ...}`` honestly when the endpoint is
 *     not yet wired; the form surfaces the error inline so the admin
 *     knows the action is v1.1.
 *
 * The dashboard NEVER calls the ledger directly — every registration
 * lands on worm-core's write surface (PEVR-cycled, hash-chained,
 * audit-grade). The `agent_registered` entry (+ companion `agent_grant`
 * entries for each requested grant) flow back through the projection
 * builder, which the `/people/agents` listing picks up automatically.
 */
export async function registerAgent(
  formData: RegisterAgentFormData,
): Promise<RegisterAgentResult> {
  // 1. Argument sanity.
  const provider = (formData.externalProvider ?? "").trim() as AgentExternalProvider;
  const displayName = (formData.displayName ?? "").trim();
  const domainReadIds = Array.isArray(formData.domainReadIds)
    ? formData.domainReadIds.map((d) => (d ?? "").trim()).filter(Boolean)
    : [];
  const budgetRaw = (formData.modelAccessBudgetUsd ?? "").trim();

  const ALLOWED_PROVIDERS: AgentExternalProvider[] = [
    "claude",
    "openai",
    "kimi",
    "internal_worm",
    "other",
  ];
  if (!ALLOWED_PROVIDERS.includes(provider)) {
    return { ok: false, error: "invalid external_provider" };
  }
  if (!displayName) {
    return { ok: false, error: "missing display_name" };
  }
  if (displayName.length > 80) {
    return { ok: false, error: "display_name exceeds 80 chars" };
  }
  if (budgetRaw && Number.isNaN(Number.parseFloat(budgetRaw))) {
    return { ok: false, error: "model_access_budget_usd not a number" };
  }

  // 2. Admin role check (tenancy.admin OR tenancy.installer). Mirror
  //    `promoteSemanticGap` — installer is super-admin per CLAUDE.md §5.
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
        "register_agent endpoint v1.1 (no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/write_actions/register_agent`;
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
        external_provider: provider,
        display_name: displayName,
        domain_read_ids: domainReadIds,
        model_access_budget_usd: budgetRaw || null,
        registered_by: person.personId,
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
        "register_agent endpoint v1.1 (worm-core has not exposed " +
        "POST /api/v1/write_actions/register_agent yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }

  let body: { agent_id?: string; agentId?: string } = {};
  try {
    body = (await res.json()) as { agent_id?: string; agentId?: string };
  } catch {
    return { ok: false, error: "worm-core API returned non-JSON body" };
  }
  const agentId = body.agentId ?? body.agent_id;
  if (!agentId) {
    return { ok: false, error: "worm-core API did not return agent_id" };
  }
  return { ok: true, agentId };
}

// Re-export for tests so they can stub the base/token reading.
export const __test__ = {
  readBase,
  readToken,
};
