import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { SemanticGapQueue } from "../../../../components/metrics-proposed/SemanticGapQueue";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { getSemanticGaps } from "../../../../lib/metrics-proposed";
import { promoteSemanticGap } from "./actions";

export const metadata = { title: "WormBase · Lake · Metrics proposed" };

export const dynamic = "force-dynamic";

/**
 * /lake/metrics-proposed — Semantic Layer Wave 3 Task 5.
 *
 * The admin queue for ``semantic_gap_proposed`` ledger entries. Surfaces
 * every NL question an agent couldn't answer because no matching metric
 * exists in the catalog. Admins promote a gap to a registered metric
 * via the "Promote" action — routes through worm-core's write API
 * (NOT a direct ledger write).
 *
 * Empty state is honest: when no gaps have been proposed yet, the
 * page surfaces the agent-onboarding / catalog-mirror affordance
 * instead of a fixture.
 */

export default async function LakeMetricsProposedPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const rows = await getSemanticGaps(companyId, { unresolved: true });

  return (
    <PageBoundary
      surface="lake metrics-proposed"
      traceQuery="?surface=lake.metrics-proposed"
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
          Semantic layer · metric-proposal queue · admin
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
          Metrics proposed · {rows.length}{" "}
          {rows.length === 1 ? "gap" : "gaps"}
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
          When an agent cannot find a metric to answer a user's question,
          it emits a ``semantic_gap_proposed`` entry instead of guessing.
          Promote a gap to register the missing metric — the next agent
          run picks it up from the catalog automatically.
        </p>
      </header>

      {rows.length === 0 ? (
        <EmptyState
          testId="lake-metrics-proposed-empty"
          eyebrow="no gaps yet"
          title="No semantic gaps proposed yet."
          description={
            "Agents emit a ``semantic_gap_proposed`` entry when they " +
            "can't find a matching metric for an NL question. The first " +
            "gap appears the moment an agent runs a query the catalog " +
            "can't answer — connect a data source or invite an agent to " +
            "populate."
          }
          cta={{ label: "See connected agents", href: "/people/agents" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <SemanticGapQueue rows={rows} promoteAction={promoteSemanticGap} />
      )}
    </PageBoundary>
  );
}
