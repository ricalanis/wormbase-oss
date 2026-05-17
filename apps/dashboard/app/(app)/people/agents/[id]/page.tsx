/**
 * /people/agents/[id] — v1.4 #2 agent detail page.
 *
 * Per-agent view covering identity, access, activity, subscriptions,
 * and audit. Reads only ledger projections + ledger raw scans; the
 * dashboard never direct-writes. Empty states are honest per
 * CLAUDE.md §9 — every panel renders a visible empty cell when its
 * read returns zero rows.
 *
 * Sections:
 *   1. Identity — provider, kind, description, registered_at, last_seen_at.
 *   2. Access — active grants table + derived domain summary.
 *   3. Activity (last 30 days) — queries / templates / bad patterns /
 *      data products consumed. Counts link out to the trace filters.
 *   4. Subscriptions — active count + link to ./subscriptions.
 *   5. Audit — last 20 ledger entries written-by or about the agent.
 *
 * Reads:
 *   * ``getAgents(companyId)`` — to find the row, since the list page
 *     already filters and we don't have a per-id reader.
 *   * ``getAgentGrants(companyId, agentId)`` — active grants table.
 *   * ``getAgentActivitySummary(companyId, agentId, 30)`` — counts.
 *   * ``getAgentAuditEntries(companyId, agentId, 20)`` — last 20.
 *   * ``getAgentSubscriptions(companyId, agentId)`` — active subs.
 *
 * Role chrome: the page surfaces regardless of role (visible to
 * member/observer for read-only), but Edit / Revoke affordances are
 * shown only to admins. The actual write protections live behind
 * the server actions the dashboard forwards to worm-core — defense
 * in depth.
 */
import Link from "next/link";

import { EditAgentButton } from "../../../../../components/agents/EditAgentButton";
import { EmptyState } from "../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { RevertMetadataButton } from "../../../../../components/agents/RevertMetadataButton";
import { RevokeAgentButton } from "../../../../../components/agents/RevokeAgentButton";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../../lib/ledger-client";
import {
  getAgents,
  getAgentActivitySummary,
  getAgentAuditEntries,
  getAgentGrants,
  getAgentMetadata,
} from "../../../../../lib/agents";
import { getAgentSubscriptions } from "../../../../../lib/agent-subscriptions";
import {
  revertAgentMetadata,
  revokeAgent,
  updateAgentMetadata,
} from "./actions";

export const metadata = { title: "WormBase · Agent detail" };
export const dynamic = "force-dynamic";

const SECTION_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const SECTION_H2: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 20,
  fontWeight: 500,
};

const SECTION_HINT: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontStyle: "italic",
  fontSize: 13,
  color: "var(--wb-color-hash-gray, #6b6256)",
};

const TABLE_STYLE: React.CSSProperties = {
  borderCollapse: "collapse",
  width: "100%",
};

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  padding: "6px 10px",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray, #6b6256)",
};

const TD_STYLE: React.CSSProperties = {
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.06))",
  padding: "8px 10px",
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
};

const TD_MONO: React.CSSProperties = {
  ...TD_STYLE,
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 12,
};

const EMPTY_CELL: React.CSSProperties = {
  padding: "10px 12px",
  border: "1px dashed var(--wb-color-edge, rgba(0,0,0,0.18))",
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontStyle: "italic",
  fontSize: 13,
  color: "var(--wb-color-hash-gray, #6b6256)",
};

function formatTs(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

async function resolveIsAdmin(
  companyId: string,
  person: Awaited<ReturnType<typeof getCurrentPerson>>,
): Promise<boolean> {
  if (!person) return false;
  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return true;
  }
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  return live.includes("admin") || live.includes("installer");
}

export default async function AgentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{
    revoke_error?: string;
    edit_error?: string;
    edited?: string;
    revert_error?: string;
    reverted?: string;
  }>;
}): Promise<JSX.Element> {
  const { id: agentId } = await params;
  const search = (await searchParams) ?? {};
  const revokeError = search.revoke_error?.trim() || null;
  const editError = search.edit_error?.trim() || null;
  const editedFlash = search.edited === "1";
  const revertError = search.revert_error?.trim() || null;
  const revertedFlash = search.reverted === "1";
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin = await resolveIsAdmin(companyId, me);

  // Find the agent row from the list. ``getAgents`` returns up to all
  // agents for the tenant; the list is small (sub-100 in v1 — see
  // ``agent-subscriptions.ts`` scaling note).
  const agents = await getAgents(companyId);
  const agent = agents.find((a) => a.id === agentId) ?? null;

  if (agent === null) {
    return (
      <PageBoundary
        surface="people agents detail"
        traceQuery={`?surface=people.agents.detail&agent_id=${encodeURIComponent(agentId)}`}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Pl. IV · Governance lens · agent detail
          </span>
        </header>
        <EmptyState
          testId="agent-detail-not-found"
          eyebrow="agent not found"
          title="No agent with that id."
          description={
            "This agent_id is not registered for the current tenant. " +
            "The list below shows the agents that ARE registered; pick " +
            "one to view its detail."
          }
          cta={{ label: "Back to agents", href: "/people/agents" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      </PageBoundary>
    );
  }

  const [grants, activity, audit, subscriptions, metadata] = await Promise.all([
    getAgentGrants(companyId, agentId),
    getAgentActivitySummary(companyId, agentId, 30),
    getAgentAuditEntries(companyId, agentId, 20),
    getAgentSubscriptions(companyId, agentId),
    getAgentMetadata(companyId, agentId),
  ]);

  // Display fields fold: latest agent_metadata_updated wins per-field;
  // fall back to the agent's registered values otherwise. The fold lives
  // in `getAgentMetadata` (lib/agents.ts); the page just consumes the
  // resolved values for display.
  const displayName = metadata.displayName ?? agent.displayName;
  const description = metadata.description;

  // Derived: distinct domain set, in case operators want to scan it
  // at a glance.
  const domainTargets = Array.from(
    new Set(
      grants
        .filter((g) => g.status === "active" && g.grantKind === "domain.read")
        .map((g) => g.grantTarget),
    ),
  ).sort();

  return (
    <PageBoundary
      surface="people agents detail"
      traceQuery={`?surface=people.agents.detail&agent_id=${encodeURIComponent(agentId)}`}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. IV · Governance lens · agent detail
        </span>
        <h1
          data-testid="agent-detail-title"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 32,
            fontWeight: 500,
            letterSpacing: "-0.01em",
            display: "flex",
            alignItems: "baseline",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          {displayName}
          <span
            data-testid="agent-detail-status"
            className="wb-mono"
            style={{
              fontSize: 12,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              padding: "2px 8px",
              border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.18))",
              color:
                agent.status === "active"
                  ? "var(--wb-color-botanical, #2d6a4f)"
                  : "var(--wb-color-hash-gray, #6b6256)",
            }}
          >
            {agent.status}
          </span>
        </h1>
        <p style={SECTION_HINT}>
          Agent identity, access, activity, and audit — all derived from
          the ledger. Every action recorded here is hash-chained and
          replayable.
        </p>
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 6,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          {isAdmin ? (
            <>
              <EditAgentButton
                agentId={agent.id}
                currentDisplayName={displayName}
                currentDescription={description}
                updateAction={updateAgentMetadata}
              />
              <RevertMetadataButton
                agentId={agent.id}
                currentDisplayName={displayName}
                hasPriorUpdate={metadata.updateCount > 0}
                revertAction={revertAgentMetadata}
              />
              {agent.status === "active" ? (
                <RevokeAgentButton
                  agentId={agent.id}
                  expectedConfirm={displayName}
                  revokeAction={revokeAgent}
                />
              ) : (
                <span
                  data-testid="agent-detail-revoke-already"
                  aria-disabled="true"
                  className="wb-mono"
                  title="This agent has no active grants — revoke is a no-op."
                  style={{
                    padding: "6px 12px",
                    border:
                      "1px solid var(--wb-color-hash-gray, #6b6256)",
                    background: "var(--wb-color-paper, #f6f1e7)",
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    fontSize: 12,
                    cursor: "not-allowed",
                    opacity: 0.6,
                  }}
                >
                  Revoked
                </span>
              )}
            </>
          ) : null}
          <Link
            href="/people/agents"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
              textDecoration: "none",
            }}
          >
            ← back to agents
          </Link>
        </div>
      </header>

      {revokeError ? (
        <div
          data-testid="agent-detail-revoke-error-banner"
          role="alert"
          style={{
            padding: "10px 14px",
            border: "1px solid var(--wb-color-error, #b03a2e)",
            background: "rgba(176,58,46,0.06)",
            color: "var(--wb-color-error, #b03a2e)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          Revoke failed: {revokeError}
        </div>
      ) : null}

      {editError ? (
        <div
          data-testid="agent-detail-edit-error-banner"
          role="alert"
          style={{
            padding: "10px 14px",
            border: "1px solid var(--wb-color-error, #b03a2e)",
            background: "rgba(176,58,46,0.06)",
            color: "var(--wb-color-error, #b03a2e)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          Edit failed: {editError}
        </div>
      ) : null}

      {editedFlash ? (
        <div
          data-testid="agent-detail-edit-success-banner"
          role="status"
          style={{
            padding: "10px 14px",
            border:
              "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
            background: "rgba(60,122,85,0.08)",
            color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          Agent metadata updated. Audit panel below shows the new
          {" "}<code>agent_metadata_updated</code> entry.
        </div>
      ) : null}

      {revertError ? (
        <div
          data-testid="agent-detail-revert-error-banner"
          role="alert"
          style={{
            padding: "10px 14px",
            border: "1px solid var(--wb-color-error, #b03a2e)",
            background: "rgba(176,58,46,0.06)",
            color: "var(--wb-color-error, #b03a2e)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          Revert failed: {revertError}
        </div>
      ) : null}

      {revertedFlash ? (
        <div
          data-testid="agent-detail-revert-success-banner"
          role="status"
          style={{
            padding: "10px 14px",
            border:
              "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
            background: "rgba(60,122,85,0.08)",
            color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          Agent metadata reverted. A new
          {" "}<code>agent_metadata_updated</code> entry was written
          carrying the prior state; the prior entry remains in the audit
          trail untouched (forward-only doctrine).
        </div>
      ) : null}

      {/* ===================== Identity ===================== */}
      <section data-testid="agent-detail-identity" style={SECTION_STYLE}>
        <h2 style={SECTION_H2}>Identity</h2>
        <table style={TABLE_STYLE}>
          <tbody>
            <tr>
              <th style={TH_STYLE}>agent_id</th>
              <td style={TD_MONO} data-testid="agent-detail-id">
                {agent.id}
              </td>
            </tr>
            <tr>
              <th style={TH_STYLE}>provider</th>
              <td style={TD_STYLE}>{agent.externalProvider}</td>
            </tr>
            <tr>
              <th style={TH_STYLE}>person_id</th>
              <td style={TD_MONO}>{agent.personId}</td>
            </tr>
            <tr>
              <th style={TH_STYLE}>description</th>
              <td
                style={{
                  ...TD_STYLE,
                  whiteSpace: "pre-wrap",
                  color: description
                    ? undefined
                    : "var(--wb-color-hash-gray, #6b6256)",
                  fontStyle: description ? undefined : "italic",
                }}
                data-testid="agent-detail-description"
              >
                {description ?? "— (none set — use Edit to add one)"}
              </td>
            </tr>
            <tr>
              <th style={TH_STYLE}>registered_at</th>
              <td style={TD_STYLE}>{formatTs(agent.registeredAt)}</td>
            </tr>
            <tr>
              <th style={TH_STYLE}>last_seen_at</th>
              <td style={TD_STYLE} data-testid="agent-detail-last-seen-at">
                {formatTs(activity.lastSeenAt)}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* ===================== Access ===================== */}
      <section data-testid="agent-detail-access" style={SECTION_STYLE}>
        <h2 style={SECTION_H2}>Access</h2>
        <p style={SECTION_HINT}>
          Active grants for this agent. Every grant is a ledger-resident
          PEVR cycle — revocation is one write, not a side-channel.{" "}
          {agent.activeGrantCount}{" "}
          {agent.activeGrantCount === 1 ? "grant" : "grants"} active.
        </p>
        {grants.length === 0 ? (
          <div data-testid="agent-detail-grants-empty" style={EMPTY_CELL}>
            No grants recorded yet. The agent has no access — register a
            grant via the admin API or the agent-as-teammate MCP path.
          </div>
        ) : (
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <th style={TH_STYLE}>kind</th>
                <th style={TH_STYLE}>target</th>
                <th style={TH_STYLE}>status</th>
                <th style={TH_STYLE}>granted_at</th>
                <th style={TH_STYLE}>budget_usd</th>
              </tr>
            </thead>
            <tbody>
              {grants.map((g) => (
                <tr key={g.id} data-testid={`agent-detail-grant-${g.id}`}>
                  <td style={TD_MONO}>{g.grantKind}</td>
                  <td style={TD_MONO}>{g.grantTarget}</td>
                  <td style={TD_STYLE}>
                    <span
                      style={{
                        fontFamily:
                          "var(--wb-font-mono, ui-monospace, monospace)",
                        fontSize: 11,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        color:
                          g.status === "active"
                            ? "var(--wb-color-botanical, #2d6a4f)"
                            : "var(--wb-color-hash-gray, #6b6256)",
                      }}
                    >
                      {g.status}
                    </span>
                  </td>
                  <td style={TD_STYLE}>{formatTs(g.grantedAt)}</td>
                  <td style={{ ...TD_STYLE, textAlign: "right" }}>
                    {g.budgetRemainingUsd ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {domainTargets.length > 0 ? (
          <p
            data-testid="agent-detail-domain-summary"
            style={{ ...SECTION_HINT, marginTop: 4 }}
          >
            Domain access:{" "}
            <span
              style={{
                fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              }}
            >
              {domainTargets.join(", ")}
            </span>
          </p>
        ) : null}
      </section>

      {/* ===================== Activity ===================== */}
      <section data-testid="agent-detail-activity" style={SECTION_STYLE}>
        <h2 style={SECTION_H2}>
          Activity{" "}
          <span style={SECTION_HINT}>
            (last {activity.windowDays} days)
          </span>
        </h2>
        <table style={TABLE_STYLE}>
          <tbody>
            <tr>
              <th style={TH_STYLE}>Queries run</th>
              <td
                style={{ ...TD_STYLE, textAlign: "right" }}
                data-testid="agent-detail-queries-run"
              >
                {activity.queriesRun > 0 ? (
                  <Link
                    href={`/trace?agent_id=${encodeURIComponent(agentId)}`}
                    style={{
                      color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
                      textDecoration: "none",
                      fontFamily:
                        "var(--wb-font-mono, ui-monospace, monospace)",
                    }}
                  >
                    {activity.queriesRun}
                  </Link>
                ) : (
                  <span style={{ color: "var(--wb-color-hash-gray)" }}>0</span>
                )}
              </td>
            </tr>
            <tr>
              <th style={TH_STYLE}>Templates promoted</th>
              <td
                style={{ ...TD_STYLE, textAlign: "right" }}
                data-testid="agent-detail-templates-promoted"
              >
                {activity.templatesPromoted}
              </td>
            </tr>
            <tr>
              <th style={TH_STYLE}>Bad-pattern proposals</th>
              <td
                style={{ ...TD_STYLE, textAlign: "right" }}
                data-testid="agent-detail-bad-patterns"
              >
                {activity.badPatternsTriggered}
              </td>
            </tr>
            <tr>
              <th style={TH_STYLE}>Data products consumed</th>
              <td
                style={{ ...TD_STYLE, textAlign: "right" }}
                data-testid="agent-detail-data-products-consumed"
              >
                {activity.dataProductsConsumed > 0 ? (
                  <Link
                    href={`/data-products?consumed_by=${encodeURIComponent(agentId)}`}
                    style={{
                      color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
                      textDecoration: "none",
                      fontFamily:
                        "var(--wb-font-mono, ui-monospace, monospace)",
                    }}
                  >
                    {activity.dataProductsConsumed}
                  </Link>
                ) : (
                  <span style={{ color: "var(--wb-color-hash-gray)" }}>0</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
        {activity.queriesRun === 0 &&
        activity.templatesPromoted === 0 &&
        activity.badPatternsTriggered === 0 &&
        activity.dataProductsConsumed === 0 ? (
          <p
            data-testid="agent-detail-activity-empty"
            style={SECTION_HINT}
          >
            No recorded activity in the last {activity.windowDays} days.
          </p>
        ) : null}
      </section>

      {/* ===================== Subscriptions ===================== */}
      <section data-testid="agent-detail-subscriptions" style={SECTION_STYLE}>
        <h2 style={SECTION_H2}>Subscriptions</h2>
        <p style={SECTION_HINT}>
          Active push-event filters this agent has registered.{" "}
          {subscriptions.length}{" "}
          {subscriptions.length === 1 ? "subscription" : "subscriptions"}{" "}
          active.
        </p>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
          <Link
            href={`/people/agents/${encodeURIComponent(agentId)}/subscriptions`}
            data-testid="agent-detail-subscriptions-link"
            className="wb-mono"
            style={{
              padding: "6px 12px",
              border:
                "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
              background: "var(--wb-color-botanical-green, #3c7a55)",
              color: "var(--wb-color-paper, #f6f1e7)",
              fontSize: 12,
              textDecoration: "none",
            }}
          >
            View subscriptions
          </Link>
          {isAdmin ? (
            <Link
              href={`/people/agents/${encodeURIComponent(agentId)}/subscriptions/new`}
              data-testid="agent-detail-subscriptions-new-link"
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-botanical-green-deep, #2a5b3f)",
                textDecoration: "none",
              }}
            >
              + Create subscription
            </Link>
          ) : null}
        </div>
      </section>

      {/* ===================== Audit ===================== */}
      <section data-testid="agent-detail-audit" style={SECTION_STYLE}>
        <h2 style={SECTION_H2}>Audit</h2>
        <p style={SECTION_HINT}>
          Last 20 ledger entries written about (or by) this agent. The
          full trail is available in the trace stream.
        </p>
        {audit.length === 0 ? (
          <div data-testid="agent-detail-audit-empty" style={EMPTY_CELL}>
            No audit entries recorded yet. Once this agent registers,
            receives grants, runs queries, or has events delivered, they
            will appear here.
          </div>
        ) : (
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <th style={TH_STYLE}>ts</th>
                <th style={TH_STYLE}>seq</th>
                <th style={TH_STYLE}>summary</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((row) => (
                <tr key={row.seq} data-testid={`agent-detail-audit-${row.seq}`}>
                  <td style={TD_STYLE}>{formatTs(row.ts)}</td>
                  <td style={TD_MONO}>{row.seq}</td>
                  <td style={TD_STYLE}>{row.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </PageBoundary>
  );
}
