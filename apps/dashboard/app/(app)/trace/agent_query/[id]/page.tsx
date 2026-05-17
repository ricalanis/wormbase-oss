/**
 * /trace/agent_query/[id] — SOC-2-credibility view (Wave 3 Task 3).
 *
 * Click-through page for a single ``agent_query`` PEVR cycle. Walks
 * every entry chained off the root ``audit_trail_id``:
 *
 *   - the four PEVR phase rows of the root agent_query itself,
 *   - every ``inference_served`` entry the model invocation produced,
 *   - every ``credential`` lifecycle event the gateway issued,
 *   - every ``query_correction_suggested`` retry attempt,
 *   - every ``query_outcome_recorded`` follow-up,
 *   - and every retry-tree PEVR cycle a correction kicked off.
 *
 * This is the hero beat for ASML's audit demo: an auditor opens the
 * URL with an audit_trail_id pasted from their tracker, sees the
 * exact chain (gate firings highlighted in red, model invocations in
 * indigo, credential issuance in teal), and copies every entry hash
 * back into their tooling without ever leaving the page.
 *
 * Read-only. Reads ``projection_*`` views via the recursive-CTE
 * accessor in ``lib/agent-query-chain.ts``. Returns an honest empty
 * state when the audit_trail_id is unknown to this tenant — never
 * fabricates.
 */
import Link from "next/link";
import { getAgentQueryChain } from "../../../../../lib/agent-query-chain";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import { getRecentDeliveries } from "../../../../../lib/agent-subscriptions";
import type { Delivery } from "../../../../../lib/agent-subscriptions";
import { AgentQueryChainView } from "../../../../../components/trace/AgentQueryChainView";
import { DeliveryTable } from "../../../../../components/agents/SubscriptionTable";
import { EmptyState } from "../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Agent query chain" };
export const dynamic = "force-dynamic";

export default async function AgentQueryChainPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companyId = await getCurrentCompanyId();
  const chain = await getAgentQueryChain(companyId, id);

  // Related deliveries: agent_event_delivered entries whose
  // triggering_entry_seq falls within the seq range of this PEVR chain.
  // Only fetched when the chain renders — empty chain renders the empty
  // state and skips the lookup.
  let relatedDeliveries: Delivery[] = [];
  if (chain !== null && chain.entries.length > 0) {
    const seqs = chain.entries
      .map((e) => Number(e.seq))
      .filter((n) => Number.isFinite(n));
    if (seqs.length > 0) {
      const lo = Math.min(...seqs);
      const hi = Math.max(...seqs);
      relatedDeliveries = await getRecentDeliveries(companyId, {
        querySeqRange: [lo, hi],
        limit: 50,
      });
    }
  }

  if (chain === null) {
    return (
      <PageBoundary
        surface="agent-query-chain"
        traceQuery={`?surface=agent-query-chain&audit_trail_id=${encodeURIComponent(id)}`}
      >
        <EmptyState
          testId="agent-query-chain-empty"
          eyebrow="audit chain not found"
          title={`No agent_query entries for ${id.slice(0, 24)}…`}
          description={
            "This audit_trail_id either doesn't exist on this tenant, " +
            "or the ledger projection hasn't yet caught up. " +
            "Agent queries auto-write a four-phase PEVR cycle through " +
            "the gateway — check that the MCP server is reachable and " +
            "the OutcomeToTemplatePromotion wire is installed for this " +
            "tenant, then refresh."
          }
          cta={{ label: "Back to /trace", href: "/trace" }}
          secondaryCta={{
            label: "Browse /people/agents",
            href: "/people/agents",
          }}
        />
      </PageBoundary>
    );
  }

  return (
    <PageBoundary
      surface="agent-query-chain"
      traceQuery={`?surface=agent-query-chain&audit_trail_id=${encodeURIComponent(id)}`}
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
          Pl. XII · Agent query · {chain.entries.length} entries
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          {chain.mcpTool || "agent_query"}{" "}
          <span
            className="wb-mono"
            style={{
              fontSize: 14,
              color: "var(--wb-color-hash-gray)",
              fontWeight: 400,
            }}
          >
            · {chain.routeMode}
          </span>
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 14,
          }}
        >
          Walks the full audit chain for this PEVR cycle: every phase,
          every chained inference call, every credential issuance, and
          every retry attempt the gateway made on behalf of the agent.
          Gate denials highlight in red. Every entry hash is
          copy-to-clipboard, ready for an external audit tracker.
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
            href="/trace"
            data-testid="agent-query-chain-back-trace"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
            }}
          >
            ← back to /trace
          </Link>
          <Link
            href={`/people/agents/${encodeURIComponent(chain.agentId)}`}
            data-testid="agent-query-chain-agent-link"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
              borderBottom: "1px dotted var(--wb-color-paper-edge)",
            }}
          >
            agent · {chain.agentId.slice(0, 12)}…
          </Link>
          <Link
            href={`/trace?audit_trail_id=${encodeURIComponent(chain.rootAuditTrailId)}`}
            data-testid="agent-query-chain-filter-trace"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
              borderBottom: "1px dotted var(--wb-color-paper-edge)",
            }}
          >
            filter /trace by this chain
          </Link>
        </div>
      </header>

      <AgentQueryChainView chain={chain} />

      <section
        data-testid="agent-query-related-deliveries"
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
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          Related Deliveries
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
          Push events fired by agent subscriptions whose triggering entry
          falls within this chain&apos;s seq range. Each row is an{" "}
          <code>agent_event_delivered</code> ledger entry — the SOC-2
          breadcrumb that proves an external agent was notified.
        </p>
        {relatedDeliveries.length === 0 ? (
          <p
            data-testid="agent-query-related-deliveries-empty"
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
            No related deliveries. Either no agent subscriptions matched
            entries written during this query, or v2.A subscription
            dispatch isn&apos;t enabled on this tenant
            (<code>WORMBASE_SUBSCRIPTIONS_ENABLED</code>).
          </p>
        ) : (
          <DeliveryTable rows={relatedDeliveries} />
        )}
      </section>
    </PageBoundary>
  );
}
