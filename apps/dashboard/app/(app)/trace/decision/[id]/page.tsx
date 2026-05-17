/**
 * /trace/decision/[id] — Decision → Bytes chain page (Phase 3 Task 3C).
 *
 * Walks the chain from a single decision down to the bronze hash that
 * originated the data feeding it: decision → process map → KPI → source
 * → bronze. Every link is clickable; every entry hash is copy-to-
 * clipboard. This is the SOC-2 / a16z credibility moment — turns
 * "auditable, hash-receipted" from a claim into a thing the auditor can
 * actually click.
 *
 * The chain is read-only over existing entry kinds; intermediate gaps
 * (no process_map yet, no KPI extracted yet) render an honest "not
 * extracted yet" pill rather than fabricated evidence.
 */
import Link from "next/link";
import { getDecisionChain } from "../../../../../lib/decision-chain";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";
import { DecisionChainView } from "../../../../../components/trace/DecisionChainView";
import { EmptyState } from "../../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Decision chain" };
export const dynamic = "force-dynamic";

export default async function DecisionChainPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companyId = await getCurrentCompanyId();
  const chain = await getDecisionChain(companyId, id);

  if (!chain.decision) {
    return (
      <PageBoundary
        surface="decision-chain"
        traceQuery={`?surface=decision-chain&decision_id=${encodeURIComponent(id)}`}
      >
        <EmptyState
          testId="decision-chain-empty"
          eyebrow="decision not found"
          title={`No decision_recorded entry for ${id.slice(0, 24)}…`}
          description={
            "This decision id either doesn't exist on this tenant, or the " +
            "ledger projection hasn't yet caught up. Decisions auto-extract " +
            "from chat — drop the worm into channels where decisions get " +
            "made and check back, or record one by hand on /decisions."
          }
          cta={{ label: "Back to Decisions", href: "/decisions" }}
          secondaryCta={{
            label: "Browse /trace",
            href: "/trace",
          }}
        />
      </PageBoundary>
    );
  }

  const resolvedCount =
    Number(chain.decision !== null) +
    Number(chain.processMap !== null) +
    Number(chain.kpi !== null) +
    Number(chain.source !== null) +
    Number(chain.bronze !== null);

  return (
    <PageBoundary
      surface="decision-chain"
      traceQuery={`?surface=decision-chain&decision_id=${encodeURIComponent(id)}`}
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
          Pl. IX · Decision → Bytes chain · {resolvedCount}/5 resolved
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
          {chain.decision.summary}
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
          Walks every step from this decision down to the bronze bytes that
          originated the data feeding it. Every entry hash is copy-to-
          clipboard; every step deep-links to its resource page. Missing
          intermediate steps render an honest gap rather than fabricated
          evidence — the chain is what the ledger actually says.
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
            href="/decisions"
            data-testid="decision-chain-back-decisions"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
            }}
          >
            ← back to Decisions
          </Link>
          <Link
            href={`/trace?evidence=${encodeURIComponent(id)}`}
            data-testid="decision-chain-trace-link"
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
              borderBottom: "1px dotted var(--wb-color-paper-edge)",
            }}
          >
            open in /trace
          </Link>
        </div>
      </header>

      <DecisionChainView chain={chain} />

      {chain.missing.length > 0 ? (
        <section
          data-testid="decision-chain-missing-summary"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            border: "1px dashed var(--wb-color-paper-edge)",
            padding: "12px 16px",
            background: "var(--wb-color-paper-deep)",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Honest gaps · {chain.missing.length}
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            The chain isn't complete yet:{" "}
            {chain.missing.map((m, i) => (
              <code
                key={m}
                className="wb-mono"
                style={{
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink)",
                  marginRight: i === chain.missing.length - 1 ? 0 : 6,
                }}
              >
                {m}
              </code>
            ))}{" "}
            haven't been emitted for this decision yet. The chain
            auto-completes as the worm catches up; reload after the next
            ramp tick.
          </p>
        </section>
      ) : null}
    </PageBoundary>
  );
}
