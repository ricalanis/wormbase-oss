/**
 * /people/agents/[id]/subscriptions/new — v2.A Task 7.
 *
 * Admin-only form for creating a new agent subscription. Submission
 * routes through the ``createSubscription`` server action which forwards
 * to worm-core's HTTP write API. The dashboard NEVER direct-writes the
 * ledger.
 *
 * Defense in depth: the page short-circuits to an "admin required" panel
 * for non-admins; the server action re-checks the role before forwarding.
 */
import Link from "next/link";

import { SubscriptionForm } from "../../../../../../../components/agents/SubscriptionForm";
import { EmptyState } from "../../../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../../../../lib/server/identity";
import {
  getDomains,
  getRolesForPerson,
} from "../../../../../../../lib/ledger-client";
import { getSubscriptionEligibleKinds } from "../../../../../../../lib/server/subscription-kinds";
import { createSubscription } from "../actions";

export const metadata = { title: "WormBase · New agent subscription" };
export const dynamic = "force-dynamic";

export default async function NewSubscriptionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<JSX.Element> {
  const { id: agentId } = await params;
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);
  const isAdmin = await resolveIsAdmin(companyId, person);

  return (
    <PageBoundary
      surface="people agents subscriptions new"
      traceQuery={`?surface=people.agents.subscriptions.new&agent_id=${encodeURIComponent(agentId)}`}
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
          Pl. IV · Governance lens · new subscription
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          New subscription ·{" "}
          <span
            className="wb-mono"
            style={{
              fontSize: 18,
              color: "var(--wb-color-hash-gray)",
              fontWeight: 400,
            }}
          >
            agent {agentId.slice(0, 12)}…
          </span>
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
          }}
        >
          Register an event filter for this agent. WormBase will push every
          matching ledger entry through the chosen transport
          (MCP stream or webhook POST). Every delivery is recorded as an{" "}
          <code>agent_event_delivered</code> ledger entry.
        </p>
      </header>

      {!isAdmin ? (
        <EmptyState
          testId="subscriptions-new-not-admin"
          eyebrow="admin required"
          title="Admin role required to manage subscriptions."
          description={
            "Only Persons with an unrevoked tenancy.admin (or " +
            "tenancy.installer) grant can create subscriptions from the " +
            "dashboard. The agent itself can self-subscribe via the MCP " +
            "agent.subscriptions.create tool."
          }
          cta={{
            label: "Back to subscriptions",
            href: `/people/agents/${encodeURIComponent(agentId)}/subscriptions`,
          }}
          secondaryCta={{ label: "Back to agents", href: "/people/agents" }}
        />
      ) : (
        <NewSubscriptionFormContainer agentId={agentId} companyId={companyId} />
      )}
    </PageBoundary>
  );
}

async function NewSubscriptionFormContainer({
  agentId,
  companyId,
}: {
  agentId: string;
  companyId: string;
}): Promise<JSX.Element> {
  // v1.4 #5: fetch both in parallel — the eligible-kinds endpoint is
  // tenant-agnostic so it has no companyId dep.
  const [domains, kinds] = await Promise.all([
    getDomains(companyId),
    getSubscriptionEligibleKinds(),
  ]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <SubscriptionForm
        agentId={agentId}
        domains={domains}
        createAction={createSubscription}
        availableKinds={kinds}
      />
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Prefer the MCP path?{" "}
        <Link
          href={`/people/agents/${encodeURIComponent(agentId)}/subscriptions`}
          style={{ color: "inherit" }}
        >
          Back to subscriptions
        </Link>{" "}
        — the agent can call <code>agent.subscriptions.create</code> directly.
      </p>
    </div>
  );
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
