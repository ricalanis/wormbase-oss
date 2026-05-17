import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { OutcomeLedgerView } from "../../../../components/query-improvement/OutcomeLedgerView";
import { RetryChainViz } from "../../../../components/query-improvement/RetryChainViz";
import { TemplateLibrary } from "../../../../components/query-improvement/TemplateLibrary";
import {
  getQueryOutcomes,
  getQueryTemplates,
  getSemanticGaps,
} from "../../../../lib/query-improvement";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Lake · Query improvement" };

export const dynamic = "force-dynamic";

/**
 * /lake/query-improvement — Semantic Layer Wave 3 Task 4.
 *
 * The compounding-loop visualisation. Three panels, each backed by a
 * dedicated accessor against the ledger projection layer:
 *
 *   1. ``Outcomes`` — recent ``query_outcome_recorded`` entries with
 *      quality scores. Each outcome links to its agent_query chain at
 *      ``/trace/agent_query/[id]`` (Task 3) where the auditor can
 *      verify the full PEVR + inference + credential trail.
 *   2. ``Templates`` — promoted query templates from
 *      ``query_template_promoted``. Each template shows the cluster
 *      that drove the promotion (3+ high-quality outcomes on the same
 *      canonical NL intent) and the cache hit count.
 *   3. ``Semantic gaps`` — agent-reported "no matching metric" events.
 *      Each gap links to ``/lake/metrics-proposed`` (sibling Task 5)
 *      where the admin can promote it to a real metric.
 *
 * Empty state per-panel is honest: when the compounding loop hasn't
 * spun up yet, each panel renders its own "no outcomes recorded yet"
 * affordance rather than fixture rows. The full-page empty state
 * (no outcomes, no templates, no gaps) points the operator at
 * ``/people/agents`` to register an external agent.
 *
 * The three accessors fetch in parallel via Promise.all so the page
 * renders as fast as the slowest projection query — typically <50ms
 * on a warm pool.
 */
export default async function LakeQueryImprovementPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const [outcomes, templates, gaps] = await Promise.all([
    getQueryOutcomes(companyId, { limit: 50 }),
    getQueryTemplates(companyId, { limit: 50 }),
    getSemanticGaps(companyId, { limit: 50 }),
  ]);

  const totalRows = outcomes.length + templates.length + gaps.length;

  return (
    <PageBoundary
      surface="lake query-improvement"
      traceQuery="?surface=lake.query-improvement"
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
          Semantic layer · §4.5 compounding loop · live
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
          Query improvement · {outcomes.length} outcomes · {templates.length}{" "}
          templates · {gaps.length} gaps
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
          The compounding loop: agents record outcomes, useful clusters
          promote to templates, and the unanswered tail becomes the
          metric backlog. The lake learns from every query — the trace
          is the proof.
        </p>
      </header>

      {totalRows === 0 ? (
        <EmptyState
          testId="lake-query-improvement-empty"
          eyebrow="loop not spun up yet"
          title="No query outcomes recorded yet."
          description={
            "Connect an external agent (Claude / OpenAI / Kimi) via the " +
            "admin API or MCP register_agent tool. Once an agent invokes " +
            "lake.semantic.metric and calls lake.query.record_outcome, the " +
            "compounding loop starts populating these panels in real time."
          }
          cta={{ label: "Register an agent", href: "/people/agents" }}
          secondaryCta={{ label: "Browse the catalog", href: "/lake/catalog" }}
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
          <Section
            eyebrow="Outcomes · query_outcome_recorded"
            title="Recent outcomes"
            description="One row per outcome the agent recorded post-resolve. Click any question to walk the audit chain."
            isEmpty={outcomes.length === 0}
            emptyEyebrow="no outcomes yet"
            emptyTitle="No outcomes recorded yet."
            emptyDescription="The first outcome lands after an agent calls lake.query.record_outcome. The execute row is folded into projection_query_outcomes within a render cycle."
            emptyTestId="lake-query-improvement-outcomes-empty"
          >
            <OutcomeLedgerView rows={outcomes} />
          </Section>

          <Section
            eyebrow="Templates · query_template_promoted"
            title="Promoted query templates"
            description="OutcomeToTemplatePromotion fires when 3+ high-quality outcomes cluster on the same canonical NL intent. Promoted templates serve subsequent queries from cache."
            isEmpty={templates.length === 0}
            emptyEyebrow="no clusters yet"
            emptyTitle="No templates promoted yet."
            emptyDescription="Templates promote automatically once the Reactivity sees 3+ outcomes on the same intent with quality_score ≥ 0.9. Until then, every query runs through the full PEVR cycle."
            emptyTestId="lake-query-improvement-templates-empty"
          >
            <TemplateLibrary rows={templates} />
          </Section>

          <Section
            eyebrow="Gaps · semantic_gap_proposed"
            title="Semantic gaps queue"
            description="Questions the agent couldn't answer with the existing catalog. Promote any gap to a real metric via the admin queue."
            isEmpty={gaps.length === 0}
            emptyEyebrow="no gaps yet"
            emptyTitle="No semantic gaps proposed yet."
            emptyDescription="Agents call lake.semantic.gap when no matching metric is found. The propose-phase ledger entry surfaces here and at /lake/metrics-proposed for admin review."
            emptyTestId="lake-query-improvement-gaps-empty"
          >
            <RetryChainViz rows={gaps} />
          </Section>
        </div>
      )}
    </PageBoundary>
  );
}

function Section({
  eyebrow,
  title,
  description,
  isEmpty,
  emptyEyebrow,
  emptyTitle,
  emptyDescription,
  emptyTestId,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  isEmpty: boolean;
  emptyEyebrow: string;
  emptyTitle: string;
  emptyDescription: string;
  emptyTestId: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {eyebrow}
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          {title}
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
            fontSize: 14,
          }}
        >
          {description}
        </p>
      </header>
      {isEmpty ? (
        <EmptyState
          testId={emptyTestId}
          eyebrow={emptyEyebrow}
          title={emptyTitle}
          description={emptyDescription}
        />
      ) : (
        children
      )}
    </section>
  );
}
