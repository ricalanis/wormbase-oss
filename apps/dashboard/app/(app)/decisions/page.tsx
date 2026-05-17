import {
  getDecisions,
  getRecurringQuestions,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { DecisionsClient } from "../../../components/decisions/DecisionsClient";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Decisions" };

/**
 * /decisions — Step 3c of the canonical product arc (process retrieval).
 *
 * Lists every decision the worm extracted from channel chatter. Each row
 * carries a Receipt and links to the source messages that evidence the
 * decision. Sidebar shows the top recurring questions (≥2 occurrences).
 */
export default async function DecisionsPage() {
  const companyId = await getCurrentCompanyId();
  const [decisions, recurring] = await Promise.all([
    getDecisions(companyId),
    getRecurringQuestions(companyId),
  ]);

  return (
    <PageBoundary surface="decisions" traceQuery="?surface=decisions">
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
          Pl. VII · Process retrieval · live
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
          Decisions · {decisions.length}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          The worm reads its own conversation lake and promotes sentences with
          explicit decisions ("we decided X", "let's go with Y", "approved",
          "agreed") into ledger entries. Every row is receipt-backed; click an
          evidence id to jump to /trace.
        </p>
      </header>

      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {decisions.length === 0 ? (
          <>
            <EmptyState
              testId="decisions-empty"
              eyebrow="decisions auto-extract from chat"
              title="No decisions yet — the worm will surface them as your team converges."
              description={
                "The worm watches channel chatter and promotes sentences with " +
                "explicit decisions (\"we decided X\", \"let's go with Y\", " +
                "\"approved\", \"agreed\") into ledger entries. Each row carries " +
                "channel, deciders, evidence ids, and a confidence score. Drop " +
                "the worm into channels where decisions get made — first " +
                "decisions typically land within a few hours of the first " +
                "decision-grade chatter. You can also record a decision by hand " +
                "for board minutes, retro outcomes, or replayed audit findings."
              }
              cta={{
                label: "Add the worm to more channels",
                href: "/channels",
              }}
              secondaryCta={{
                label: "What's recurring?",
                href: "#recurring-questions",
              }}
            />
            <DecisionsSamplePreview />
            <DecisionsClient rows={decisions} />
          </>
        ) : (
          <DecisionsClient rows={decisions} />
        )}
      </section>

      {recurring.length > 0 && (
        <section
          id="recurring-questions"
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Recurring questions
          </h2>
          <ul
            data-testid="recurring-questions"
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {recurring.slice(0, 10).map((q) => (
              <li
                key={q.questionId}
                data-testid={`recurring-${q.questionId}`}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 12,
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wb-color-paper-edge)",
                }}
              >
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 12,
                    color: "var(--wb-color-botanical-green)",
                    minWidth: 32,
                  }}
                >
                  ×{q.occurrences}
                </span>
                <span style={{ fontFamily: "var(--wb-font-serif)", flex: 1 }}>
                  {q.normalizedQuestion}
                </span>
                {q.suggestedAutomation && (
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      color: "var(--wb-color-hash-gray)",
                      fontStyle: "italic",
                    }}
                  >
                    suggest: {q.suggestedAutomation}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </PageBoundary>
  );
}

/**
 * DecisionsSamplePreview — rendered alongside the empty state so an
 * operator without any chatter yet can still see what /decisions will
 * look like once the worm has lurked in a channel for a few hours
 * (W2.A7). Pure illustration; no ledger writes; not interactable.
 */
function DecisionsSamplePreview() {
  return (
    <section
      data-testid="decisions-sample-preview"
      aria-hidden="true"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        border: "1px dashed var(--wb-color-paper-edge)",
        padding: "16px 18px",
        background: "var(--wb-color-paper-deep)",
        opacity: 0.78,
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
        Sample · what a populated tab looks like
      </span>
      <ul
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <li
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          <span
            className="wb-mono"
            style={{ color: "var(--wb-color-hash-gray)", marginRight: 8 }}
          >
            #finance · 92%
          </span>
          We decided to push the Q3 close to Friday so accounting can
          re-run reconciliations.
        </li>
        <li
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          <span
            className="wb-mono"
            style={{ color: "var(--wb-color-hash-gray)", marginRight: 8 }}
          >
            #ops · 87%
          </span>
          Approved: roll the deploy on Tuesday after staging signs off.
        </li>
        <li
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          <span
            className="wb-mono"
            style={{ color: "var(--wb-color-hash-gray)", marginRight: 8 }}
          >
            #data · 81%
          </span>
          Let's go with the medallion-cascade ingest cadence at 5 minutes.
        </li>
      </ul>
    </section>
  );
}
