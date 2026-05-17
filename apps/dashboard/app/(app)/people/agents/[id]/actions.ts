/**
 * Server actions for /people/agents/[id] (v1.4 follow-up — Path 5 +
 * final wave item #5).
 *
 * Wires the agent detail page's Revoke and Edit buttons to two
 * worm-core write endpoints:
 *
 *   * ``DELETE /api/v1/write_actions/agents_revoke/{agent_id}`` (Path 5)
 *     cascades a revoke over every active grant the agent holds.
 *   * ``PATCH /api/v1/write_actions/agents_metadata/{agent_id}``
 *     (final wave item #5, 2026-05-13) writes one
 *     ``agent_metadata_updated`` PEVR cycle. Preserves agent_id
 *     continuity so audit trails, grants, and subscriptions stay
 *     attached to the same agent — see the kind's docstring in
 *     ``packages/ledger/src/wormbase_ledger/entries.py``.
 *
 * Architectural contract (mirrors `/people/agents/[id]/subscriptions/actions.ts`):
 *
 *   * The dashboard NEVER direct-writes the ledger. The revoke path
 *     routes through worm-core's HTTP write API.
 *
 *   * Admin role check is enforced inline. tenancy.admin or
 *     tenancy.installer required — defense in depth.
 *
 *   * Confirmation friction lives client-side in the page (the user
 *     types the agent's display_name to confirm); this server action
 *     trusts the page boundary's check and re-validates only that the
 *     agent_id is well-formed.
 *
 * The worm-core endpoint is idempotent: revoking an agent with no
 * active grants returns 200 with revoked_grant_count=0 and writes
 * nothing. The dashboard surface treats both cases as success and
 * redirects back to the agents list.
 */
"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../../lib/ledger-client";

export interface RevokeAgentResult {
  ok: boolean;
  revokedGrantCount?: number;
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

async function requireAdmin(
  companyId: string,
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
  return { ok: false, error: "admin role required" };
}

/**
 * Admin-only: revoke every active grant for an agent. Forwards to
 * worm-core which cascades the revoke as one ``agent_grant`` (status=
 * revoked) PEVR cycle per active grant.
 *
 * Returns ``{ok: true, revokedGrantCount}`` on success. Throws via
 * ``redirect`` on success-with-redirect form usage. Returns
 * ``{ok: false, error}`` on validation / network failure so the form
 * can render the error inline.
 */
export async function revokeAgent(
  agentId: string,
): Promise<RevokeAgentResult> {
  if (!agentId || typeof agentId !== "string") {
    return { ok: false, error: "missing agent_id" };
  }

  const companyId = await getCurrentCompanyId();
  const auth = await requireAdmin(companyId);
  if (!auth.ok) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "agents_revoke endpoint v1.4 follow-up " +
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
    `${base}/api/v1/write_actions/agents_revoke/` +
    encodeURIComponent(agentId);
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
        "agents_revoke endpoint v1.4 follow-up (worm-core has not " +
        "exposed DELETE /api/v1/write_actions/agents_revoke yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }

  let body: {
    revoked_grant_count?: number;
    revokedGrantCount?: number;
  } = {};
  try {
    body = (await res.json()) as {
      revoked_grant_count?: number;
      revokedGrantCount?: number;
    };
  } catch {
    return { ok: false, error: "worm-core API returned non-JSON body" };
  }
  const count = body.revokedGrantCount ?? body.revoked_grant_count ?? 0;
  return { ok: true, revokedGrantCount: count };
}

/**
 * Form-bound revoke handler. The detail page's confirm modal posts to
 * this action with the agent_id and a confirmation field (the user
 * types the agent's display_name); both are validated before the
 * forward to worm-core.
 *
 * On success, revalidates the agents list path and redirects back so
 * the page shows the agent without its revoked grants (the projection
 * builder folds the new revoke rows into the active set on next read).
 */
export async function revokeAgentFromForm(formData: FormData): Promise<void> {
  const agentId = String(formData.get("agent_id") ?? "").trim();
  const confirmText = String(formData.get("confirm_text") ?? "").trim();
  const expectedConfirm = String(formData.get("expected_confirm") ?? "").trim();

  if (!agentId) {
    redirect(
      `/people/agents?revoke_error=${encodeURIComponent("missing agent_id")}`,
    );
  }
  if (!expectedConfirm || confirmText !== expectedConfirm) {
    redirect(
      `/people/agents/${encodeURIComponent(agentId)}?revoke_error=${encodeURIComponent(
        "confirmation text did not match — type the agent's display name to confirm",
      )}`,
    );
  }

  const result = await revokeAgent(agentId);
  if (!result.ok) {
    redirect(
      `/people/agents/${encodeURIComponent(agentId)}?revoke_error=${encodeURIComponent(
        result.error ?? "revoke failed",
      )}`,
    );
  }

  revalidatePath("/people/agents");
  revalidatePath(`/people/agents/${agentId}`);
  redirect(
    `/people/agents?revoked=${encodeURIComponent(agentId)}&grants=${
      result.revokedGrantCount ?? 0
    }`,
  );
}

// ===========================================================================
// Final wave item #5 (2026-05-13) — agent metadata edit flow.
//
// Wires the Edit chip on /people/agents/[id]. POSTs to worm-core's
// PATCH /api/v1/write_actions/agents_metadata/{agent_id}, which writes
// one agent_metadata_updated PEVR cycle (KIND_REGISTRY 103 → 104).
// Preserves agent_id continuity so audit trails do not fork.
//
// Form validation lives in the EditAgentButton client component (at least
// one of display_name / description must be non-empty AND different from
// current). The server action re-validates at the boundary; the worm-core
// HTTP layer re-validates again (defense in depth).
// ===========================================================================

export interface UpdateAgentMetadataInput {
  agentId: string;
  /** New display name, or null to leave unchanged. */
  displayName: string | null;
  /** New description, or null to leave unchanged. */
  description: string | null;
  /** Optional free-text audit note. */
  reason: string | null;
}

export interface UpdateAgentMetadataResult {
  ok: boolean;
  error?: string;
}

/**
 * Admin-only: update an agent's display_name / description.
 *
 * At least one of ``displayName`` / ``description`` must be non-null.
 * The server action re-validates this and returns a structured error
 * if the caller violates the contract.
 *
 * Returns ``{ok: true}`` on success. Returns ``{ok: false, error}`` on
 * validation / network failure so the form can render the error inline.
 */
export async function updateAgentMetadata(
  input: UpdateAgentMetadataInput,
): Promise<UpdateAgentMetadataResult> {
  const { agentId, displayName, description, reason } = input;
  if (!agentId || typeof agentId !== "string") {
    return { ok: false, error: "missing agent_id" };
  }
  if (displayName === null && description === null) {
    return {
      ok: false,
      error: "at least one of display_name / description is required",
    };
  }
  if (displayName !== null && !displayName.trim()) {
    return {
      ok: false,
      error: "display_name cannot be empty (omit to leave unchanged)",
    };
  }

  const companyId = await getCurrentCompanyId();
  const auth = await requireAdmin(companyId);
  if (!auth.ok) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "agents_metadata endpoint final-wave #5 " +
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
    `${base}/api/v1/write_actions/agents_metadata/` +
    encodeURIComponent(agentId);
  const body: Record<string, unknown> = {
    company_id: companyId,
    updated_by: auth.personId,
  };
  if (displayName !== null) body.display_name = displayName;
  if (description !== null) body.description = description;
  if (reason !== null && reason.trim()) body.reason = reason;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error:
        "agents_metadata endpoint final-wave #5 (worm-core has not " +
        "exposed PATCH /api/v1/write_actions/agents_metadata yet)",
    };
  }
  if (!res.ok) {
    const responseBody = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${responseBody || res.statusText}`,
    };
  }

  return { ok: true };
}

/**
 * Form-bound metadata-edit handler. The detail page's Edit modal posts
 * to this action with the agent_id, display_name, description, and an
 * optional reason; the server action validates the agent_id and admin
 * role, then forwards to worm-core. On success, the agents list path
 * and the detail page are revalidated; the caller is redirected back to
 * the detail page with a success flash.
 */
export async function updateAgentMetadataFromForm(
  formData: FormData,
): Promise<void> {
  const agentId = String(formData.get("agent_id") ?? "").trim();
  const rawDisplayName = formData.get("display_name");
  const rawDescription = formData.get("description");
  const rawReason = formData.get("reason");

  // Null sentinel: form fields with type="text" never produce null, so
  // the modal posts the literal string "" when the field is absent and
  // the original value when it is present. We translate empty-string
  // (display_name) to null (= unchanged) here since we can't distinguish
  // "user cleared" from "user didn't touch" on the wire. The dashboard
  // form catches the actual no-op case before submit (Submit disabled
  // unless at least one field has changed).
  const displayName =
    typeof rawDisplayName === "string" && rawDisplayName.trim().length > 0
      ? rawDisplayName
      : null;
  const description =
    typeof rawDescription === "string" && rawDescription.length > 0
      ? rawDescription
      : null;
  const reason =
    typeof rawReason === "string" && rawReason.trim().length > 0
      ? rawReason
      : null;

  if (!agentId) {
    redirect(
      `/people/agents?edit_error=${encodeURIComponent("missing agent_id")}`,
    );
  }
  if (displayName === null && description === null) {
    redirect(
      `/people/agents/${encodeURIComponent(agentId)}?edit_error=${encodeURIComponent(
        "at least one of display_name / description must be set",
      )}`,
    );
  }

  const result = await updateAgentMetadata({
    agentId,
    displayName,
    description,
    reason,
  });
  if (!result.ok) {
    redirect(
      `/people/agents/${encodeURIComponent(agentId)}?edit_error=${encodeURIComponent(
        result.error ?? "edit failed",
      )}`,
    );
  }

  revalidatePath("/people/agents");
  revalidatePath(`/people/agents/${agentId}`);
  redirect(
    `/people/agents/${encodeURIComponent(agentId)}?edited=1`,
  );
}

// ===========================================================================
// Post-rest path #4 (2026-05-13) — agent metadata revert flow.
//
// Wires the Revert button on /people/agents/[id]. POSTs to worm-core's
// POST /api/v1/write_actions/agents_metadata_revert/{agent_id}, which
// emits a NEW agent_metadata_updated PEVR cycle whose display_name +
// description carry the prior state (forward-only doctrine; no new
// ledger kind, no mutation of prior entries).
//
// Visibility: the page renders the Revert button only when at least one
// prior agent_metadata_updated exists for this agent. The server action
// still re-validates the agent_id at the boundary; worm-core returns 400
// if the caller invokes it with no prior update.
// ===========================================================================

export interface RevertAgentMetadataInput {
  agentId: string;
  /** Optional free-text audit note. Appended to the auto-generated
   *  "revert from seq {N}" prefix worm-core stamps on the new entry. */
  reason: string | null;
}

export interface RevertAgentMetadataResult {
  ok: boolean;
  error?: string;
}

/**
 * Admin-only: revert an agent's metadata to the prior state.
 *
 * Forwards to worm-core's POST agents_metadata_revert endpoint. The
 * worm-core handler looks up the most-recent agent_metadata_updated,
 * resolves the pre-head display_name + description (or the
 * agent_registered baseline when only one update exists), and emits a
 * new compensating agent_metadata_updated PEVR cycle.
 *
 * Returns ``{ok: true}`` on success. Returns ``{ok: false, error}`` on
 * validation / network failure so the form can render the error inline.
 */
export async function revertAgentMetadata(
  input: RevertAgentMetadataInput,
): Promise<RevertAgentMetadataResult> {
  const { agentId, reason } = input;
  if (!agentId || typeof agentId !== "string") {
    return { ok: false, error: "missing agent_id" };
  }

  const companyId = await getCurrentCompanyId();
  const auth = await requireAdmin(companyId);
  if (!auth.ok) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "agents_metadata_revert endpoint post-rest #4 " +
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
    `${base}/api/v1/write_actions/agents_metadata_revert/` +
    encodeURIComponent(agentId);
  const body: Record<string, unknown> = {
    company_id: companyId,
    updated_by: auth.personId,
  };
  if (reason !== null && reason.trim()) body.reason = reason;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error:
        "agents_metadata_revert endpoint post-rest #4 (worm-core has not " +
        "exposed POST /api/v1/write_actions/agents_metadata_revert yet)",
    };
  }
  if (!res.ok) {
    const responseBody = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${responseBody || res.statusText}`,
    };
  }

  return { ok: true };
}

export const __test__ = {
  readBase,
  readToken,
};
