import { AgentTable } from "../../../../components/agents/AgentTable";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { getAgents } from "../../../../lib/agents";
import { getAgentSubscriptionCounts } from "../../../../lib/agent-subscriptions";

export const metadata = { title: "WormBase · People · Agents" };

export const dynamic = "force-dynamic";

/**
 * /people/agents — Semantic Layer Wave 3 Task 2.
 *
 * Renders one row per registered agent (Person sub-type). Shows the
 * external provider, display name, active grant count, and remaining
 * model-access budget per agent. Per-row click-through leads to
 * `/people/agents/[id]` for the per-agent detail view (deferred to a
 * future wave; the row link is emitted today so chrome stays
 * consistent).
 *
 * Empty state is honest: when no agents have been registered yet, the
 * page surfaces the admin-API affordance instead of a fixture. The
 * `register_agent` MCP tool (or its admin-CLI sibling) writes the
 * `agent_registered` ledger entry; the projection-builder folds it
 * into `projection_agents` and the next render of this page picks it
 * up.
 */
export default async function PeopleAgentsPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const agents = await getAgents(companyId);
  const subscriptionCounts = await getAgentSubscriptionCounts(companyId);
  const agentsWithSubs = agents.map((a) => ({
    ...a,
    subscriptionCount: subscriptionCounts.get(a.id) ?? 0,
  }));

  return (
    <PageBoundary
      surface="people agents"
      traceQuery="?surface=people.agents"
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
          Pl. IV · Governance lens · agent identity
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Agents · {agents.length}{" "}
          {agents.length === 1 ? "registered" : "registered"}
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
          Every external agent (Claude, OpenAI, Kimi, …) and every internal
          worm-issued agent is a Person sub-type with its own ledger trail.
          Grants and model budgets are auditable per agent — revocation is
          one ledger write, not a side-channel.
        </p>
      </header>

      {agents.length === 0 ? (
        <EmptyState
          testId="people-agents-empty"
          eyebrow="no agents yet"
          title="No agents registered yet."
          description={
            "Use the admin API to register an agent for an external provider. " +
            "The register_agent MCP tool writes an agent_registered ledger " +
            "entry; the projection folds it into projection_agents and this " +
            "list refreshes."
          }
          cta={{ label: "See raw activity", href: "/activity" }}
          secondaryCta={{ label: "View the trace", href: "/trace" }}
        />
      ) : (
        <AgentTable rows={agentsWithSubs} />
      )}
    </PageBoundary>
  );
}
