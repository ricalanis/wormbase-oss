import { getProcessMaps } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { ProcessDiagram } from "../../../components/process/ProcessDiagram";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { ProcessMapEditor } from "../../../components/processes/ProcessMapEditor";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Processes" };

/**
 * /processes — Step 3c of the canonical product arc (process retrieval).
 *
 * One swimlane diagram per ``emit_process_map_proposed`` ledger entry. The
 * worm extracts ordered actor → action sequences from channel chatter
 * ("first Bob exports, then Alice reviews, then Carol approves") and
 * promotes them to first-class process maps. Each map carries a Receipt;
 * confidence is shown alongside.
 */
export default async function ProcessesPage() {
  const companyId = await getCurrentCompanyId();
  const processes = await getProcessMaps(companyId);

  return (
    <PageBoundary surface="processes" traceQuery="?surface=processes">
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
          Pl. VIII · Process retrieval · live
        </span>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 34,
              fontWeight: 500,
              letterSpacing: "-0.01em",
            }}
          >
            Processes · {processes.length}
          </h1>
          <ProcessMapEditor />
        </div>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Process maps auto-build from chat — Kimi (when reachable) plus
          deterministic heuristics over your conversation lake. Drag a
          swimlane to reorder, click a step to jump to /trace, or author
          one by hand for an onboarding seed.
        </p>
      </header>

      {processes.length === 0 ? (
        <EmptyState
          testId="processes-empty"
          eyebrow="process maps auto-build from chat"
          title="No processes yet — first map typically lands within 24h."
          description={
            "This surface fills with swimlane diagrams when the worm sees " +
            "ordered actor → action sequences (\"first Bob exports, then " +
            "Alice reviews, then Carol approves\") in connected channels. " +
            "Drop the worm into more channels to grow the conversation lake. " +
            "Or author the first process by hand to seed the lake — useful " +
            "for onboarding workflows, retro outcomes, or vendor handoffs."
          }
          cta={{ label: "Drop the worm into more channels", href: "/channels" }}
          secondaryCta={{ label: "Browse decisions", href: "/decisions" }}
        />
      ) : (
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 24,
          }}
        >
          {processes.map((p) => (
            <ProcessDiagram key={p.processId} process={p} />
          ))}
        </section>
      )}
    </PageBoundary>
  );
}
