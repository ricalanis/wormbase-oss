/**
 * Server actions for /people/agents/[id]/subscriptions (v2.A Task 7).
 *
 * Architectural contract (mirrors `/people/agents/new/actions.ts`):
 *
 *   * The dashboard NEVER direct-writes the ledger. Every create / revoke
 *     routes through worm-core's HTTP write API
 *     (``POST /api/v1/write_actions/agent_subscriptions_create`` and
 *     ``DELETE /api/v1/write_actions/agent_subscriptions_revoke/{id}``).
 *
 *   * Role check is enforced inline. Mirroring the agent-register flow:
 *     admins (tenancy.admin / tenancy.installer) may create/revoke for
 *     any agent on their tenant. Members may create/revoke ONLY for
 *     agents they themselves registered (registered_by_person_id check —
 *     v1 deferred; for now we require admin/installer). Observers are
 *     read-only.
 *
 *   * Validation: at least one of (kinds, domains, agent_id_ref,
 *     payload_path_eq) must be non-empty so the subscription doesn't
 *     match every entry by accident. The MCP-side dispatcher would
 *     happily fire on a wildcard subscription, but the dashboard form
 *     surface is the boundary where we reject overly-broad filters
 *     before they hit the ledger.
 *
 * Production graduation: worm-core's ``POST /api/v1/write_actions/
 * agent_subscriptions_create`` is the production-path endpoint added in
 * the same Batch C commit. When ``WORM_CORE_API_URL`` /
 * ``WORMBASE_LEDGER_API_BASE`` is set, the action forwards; otherwise it
 * surfaces a "no API base configured" error so the surface degrades
 * honestly.
 */
"use server";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../../../lib/ledger-client";

export type SubscriptionTransport = "mcp_stream" | "webhook";

export interface CreateSubscriptionFormData {
  kinds: string[];
  domains: string[];
  agentIdRef?: string;
  payloadPathEq: [string, string][];
  transport: SubscriptionTransport;
  webhookUrl?: string;
  webhookSecretRef?: string;
  description?: string;
}

export interface CreateSubscriptionResult {
  ok: boolean;
  subscriptionId?: string;
  error?: string;
}

export interface RevokeSubscriptionResult {
  ok: boolean;
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

async function requireAdminOrSelf(
  companyId: string,
  agentId: string,
): Promise<{ ok: true; personId: string } | { ok: false; error: string }> {
  const person = await getCurrentPerson(companyId);
  if (!person) {
    return { ok: false, error: "no authenticated person" };
  }
  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return { ok: true, personId: person.personId };
  }
  // Role roster may lag — probe the grants table directly.
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  if (live.includes("admin") || live.includes("installer")) {
    return { ok: true, personId: person.personId };
  }
  // Note: per the Task 7 spec, members can VIEW their own agents'
  // subscriptions but only admins can create/revoke from the dashboard.
  // The agent itself can self-manage via the MCP path; the dashboard
  // is the admin override surface.
  void agentId;
  return { ok: false, error: "admin role required" };
}

function validateFilterAxes(data: CreateSubscriptionFormData): string | null {
  const haveKinds = data.kinds.some((k) => k.trim().length > 0);
  const haveDomains = data.domains.some((d) => d.trim().length > 0);
  const haveAgentRef = (data.agentIdRef ?? "").trim().length > 0;
  const havePayload = data.payloadPathEq.some(
    ([k, v]) => k.trim().length > 0 && v.trim().length > 0,
  );
  if (!haveKinds && !haveDomains && !haveAgentRef && !havePayload) {
    return (
      "subscription filter must constrain at least one of (kinds, " +
      "domains, agent_id_ref, payload_path_eq) — a wildcard filter " +
      "would match every ledger entry"
    );
  }
  return null;
}

/**
 * Admin-only: create a new agent subscription. Forwards to worm-core.
 */
export async function createSubscription(
  agentId: string,
  formData: CreateSubscriptionFormData,
): Promise<CreateSubscriptionResult> {
  if (!agentId || typeof agentId !== "string") {
    return { ok: false, error: "missing agent_id" };
  }
  if (formData.transport !== "mcp_stream" && formData.transport !== "webhook") {
    return { ok: false, error: "transport must be mcp_stream or webhook" };
  }
  if (formData.transport === "webhook") {
    if (!formData.webhookUrl?.trim()) {
      return { ok: false, error: "webhook_url required for webhook transport" };
    }
    if (!formData.webhookSecretRef?.trim()) {
      return {
        ok: false,
        error: "webhook_secret_ref required for webhook transport",
      };
    }
    try {
      const u = new URL(formData.webhookUrl);
      if (u.protocol !== "https:" && u.protocol !== "http:") {
        return { ok: false, error: "webhook_url must be http(s)" };
      }
    } catch {
      return { ok: false, error: "webhook_url must be a valid URL" };
    }
  }

  const validation = validateFilterAxes(formData);
  if (validation) return { ok: false, error: validation };

  const companyId = await getCurrentCompanyId();
  const auth = await requireAdminOrSelf(companyId, agentId);
  if (!auth.ok) return { ok: false, error: auth.error };

  // Build the wire filter payload — translates to the canonical
  // serialized AgentEventFilter shape the dispatcher consumes.
  const filterPayload = {
    kinds: formData.kinds.filter((k) => k.trim().length > 0),
    domains: formData.domains.filter((d) => d.trim().length > 0),
    agent_id_ref: formData.agentIdRef?.trim() || null,
    payload_path_eq: formData.payloadPathEq
      .filter(([k, v]) => k.trim().length > 0 && v.trim().length > 0)
      .map(([k, v]) => [k.trim(), v.trim()] as [string, string]),
  };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "agent_subscriptions_create endpoint v2.A " +
        "(no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/write_actions/agent_subscriptions_create`;
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
        company_id: companyId,
        agent_id: agentId,
        filter: filterPayload,
        transport: formData.transport,
        webhook_url: formData.webhookUrl?.trim() || null,
        webhook_secret_ref: formData.webhookSecretRef?.trim() || null,
        description: formData.description?.trim() || null,
        granted_by: auth.personId,
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
        "agent_subscriptions_create endpoint v2.A (worm-core has not " +
        "exposed POST /api/v1/write_actions/agent_subscriptions_create yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }

  let body: { subscription_id?: string; subscriptionId?: string } = {};
  try {
    body = (await res.json()) as {
      subscription_id?: string;
      subscriptionId?: string;
    };
  } catch {
    return { ok: false, error: "worm-core API returned non-JSON body" };
  }
  const subscriptionId = body.subscriptionId ?? body.subscription_id;
  if (!subscriptionId) {
    return {
      ok: false,
      error: "worm-core API did not return subscription_id",
    };
  }
  return { ok: true, subscriptionId };
}

/**
 * Admin-only: revoke an existing agent subscription. Forwards to
 * worm-core's DELETE endpoint, which writes the
 * ``emit_agent_subscription_revoked`` ledger entry.
 */
export async function revokeSubscription(
  agentId: string,
  subscriptionId: string,
): Promise<RevokeSubscriptionResult> {
  if (!agentId) return { ok: false, error: "missing agent_id" };
  if (!subscriptionId) return { ok: false, error: "missing subscription_id" };

  const companyId = await getCurrentCompanyId();
  const auth = await requireAdminOrSelf(companyId, agentId);
  if (!auth.ok) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "agent_subscriptions_revoke endpoint v2.A " +
        "(no WORM_CORE_API_URL configured)",
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
  const url =
    `${base}/api/v1/write_actions/agent_subscriptions_revoke/` +
    encodeURIComponent(subscriptionId);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify({
        company_id: companyId,
        reason: "admin_revoked",
        revoked_by: auth.personId,
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
        "agent_subscriptions_revoke endpoint v2.A (worm-core has not " +
        "exposed DELETE /api/v1/write_actions/agent_subscriptions_revoke yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }
  return { ok: true };
}

export const __test__ = {
  readBase,
  readToken,
  validateFilterAxes,
};
