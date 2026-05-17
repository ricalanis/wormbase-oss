/**
 * /people/agents/[id]/subscriptions — v2.A Task 7.
 *
 * List of active subscriptions for an agent, plus a recent-deliveries
 * audit panel (50 rows, ordered by triggering_entry_seq DESC). Honest
 * empty state per CLAUDE.md §9 — no fixture fallback.
 *
 * Reads:
 *   * ``getAgentSubscriptions(companyId, agentId)`` — active set
 *   * ``getRecentDeliveries(companyId, {subscriptionId in active set})`` —
 *     last 50 ``agent_event_delivered`` entries for any of the agent's
 *     active subscriptions.
 *
 * Writes: none on render. Revoke writes route through the server action
 * in ``./actions.ts`` which forwards to worm-core's HTTP write API.
 */
import Link from "next/link";

import { SubscriptionTable, DeliveryTable } from "../../../../../../components/agents/SubscriptionTable";
import { EmptyState } from "../../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../../../lib/tenant-cookies";
import {
  getAgentSubscriptions,
  getRecentDeliveries,
} from "../../../../../../lib/agent-subscriptions";
import type { Delivery } from "../../../../../../lib/agent-subscriptions";
import { revokeSubscription } from "./actions";

export const metadata = { title: "WormBase · Agent subscriptions" };
export const dynamic = "force-dynamic";

export default async function AgentSubscriptionsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ created?: string; revoked?: string }>;
}): Promise<JSX.Element> {
  const { id: agentId } = await params;
  const search = (await searchParams) ?? {};
  const companyId = await getCurrentCompanyId();
  const subscriptions = await getAgentSubscriptions(companyId, agentId);

  // Fetch recent deliveries scoped to this agent.
  let deliveries: Delivery[] = [];
  if (subscriptions.length > 0) {
    deliveries = await getRecentDeliveries(companyId, {
      agentId,
      limit: 50,
    });
  }

  return (
    <PageBoundary
      surface="people agents subscriptions"
      traceQuery={`?surface=people.agents.subscriptions&agent_id=${encodeURIComponent(agentId)}`}
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
          Pl. IV · Governance lens · agent subscriptions
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
          Subscriptions ·{" "}
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
          Active filters this agent has registered to receive push events
          from WormBase. Every subscription is a ledger-resident PEVR cycle;
          every delivery is recorded for SOC-2 replay (
          <code>agent_event_delivered</code>).
        </p>
        <div
          style={{
            display: "flex",
            gap: 14,
            marginTop: 8,
            flexWrap: "wrap",
          }}
        >
          <Link
            href={`/people/agents/${encodeURIComponent(agentId)}/subscriptions/new`}
            data-testid="subscriptions-new-cta"
            style={{
              padding: "8px 14px",
              border: "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
              background: "var(--wb-color-botanical-green, #3c7a55)",
              color: "var(--wb-color-paper, #f6f1e7)",
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontSize: 13,
              textDecoration: "none",
            }}
          >
            + Create subscription
          </Link>
          <Link
            href="/people/agents"
            data-testid="subscriptions-back"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
              alignSelf: "center",
            }}
          >
            ← back to agents
          </Link>
        </div>
      </header>

      {search.created ? (
        <div
          data-testid="subscriptions-created-flash"
          style={{
            padding: "8px 12px",
            border: "1px solid var(--wb-color-botanical, #2d6a4f)",
            background: "rgba(45,106,79,0.08)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 11,
            color: "var(--wb-color-botanical, #2d6a4f)",
          }}
        >
          Subscription created: {String(search.created).slice(0, 12)}…
        </div>
      ) : null}
      {search.revoked ? (
        <div
          data-testid="subscriptions-revoked-flash"
          style={{
            padding: "8px 12px",
            border: "1px solid var(--wb-color-hash-gray, #6b6256)",
            background: "rgba(107,98,86,0.08)",
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Subscription revoked: {String(search.revoked).slice(0, 12)}…
        </div>
      ) : null}

      {subscriptions.length === 0 ? (
        <EmptyState
          testId="subscriptions-empty"
          eyebrow="no subscriptions yet"
          title="No subscriptions yet."
          description={
            "Subscriptions let this agent receive push events for ledger " +
            "writes that match a filter (kinds, domains, agent_id_ref, " +
            "or payload path/value pairs). Create the first subscription " +
            "to start receiving pushes via MCP stream or webhook."
          }
          cta={{
            label: "Create subscription",
            href: `/people/agents/${encodeURIComponent(agentId)}/subscriptions/new`,
          }}
          secondaryCta={{ label: "Back to agents", href: "/people/agents" }}
        />
      ) : (
        <>
          <SubscriptionTable
            agentId={agentId}
            rows={subscriptions}
            revokeAction={revokeSubscription}
          />

          <section
            style={{
              marginTop: 24,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <h2
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif, Georgia, serif)",
                fontSize: 20,
                fontWeight: 500,
              }}
            >
              Recent deliveries
            </h2>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                color: "var(--wb-color-hash-gray)",
                fontSize: 13,
              }}
            >
              Last 50 push events (any subscription), ordered by triggering
              entry seq, newest first.
            </p>
            {deliveries.length === 0 ? (
              <p
                data-testid="deliveries-empty"
                style={{
                  margin: 0,
                  padding: "10px 12px",
                  border: "1px dashed var(--wb-color-edge, rgba(0,0,0,0.18))",
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                  fontSize: 13,
                }}
              >
                No deliveries yet for this agent. Once a ledger entry
                matching one of these subscriptions lands, a delivery row
                will appear here.
              </p>
            ) : (
              <DeliveryTable rows={deliveries} />
            )}
          </section>
        </>
      )}
    </PageBoundary>
  );
}
