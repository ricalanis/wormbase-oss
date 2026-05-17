import {
  getCompositeScoreSeries,
  getExperimentLessonsByScope,
  getExperimentsByAudience,
  getExperimentsForUser,
  getFirstKnowings,
  getHeadlineMetricsHistory,
  getKeepRateSeries,
  getPositionsRegistry,
  getResearchOverview,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import { AudienceTabs } from "../../../components/research/AudienceTabs";
import { CompositeScoreCard } from "../../../components/research/CompositeScoreCard";
import { FirstKnowingsTab } from "../../../components/research/FirstKnowingsTab";
import { KeepRateChart } from "../../../components/research/KeepRateChart";
import { LessonsCard } from "../../../components/research/LessonsCard";
import { ResearchView } from "../../../components/research/ResearchView";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";
import type { ResearchAudience } from "../../../lib/ledger-client.types";

export const metadata = { title: "WormBase · Research" };

export const dynamic = "force-dynamic";

const AUDIENCE_KEYS: ReadonlyArray<ResearchAudience> = ["mine", "team", "company"];

function asAudience(v: string | string[] | undefined): ResearchAudience {
  const raw = typeof v === "string" ? v : Array.isArray(v) ? v[0] : "";
  return AUDIENCE_KEYS.includes(raw as ResearchAudience)
    ? (raw as ResearchAudience)
    : "mine";
}

/**
 * /research — Step 5 of the canonical product arc (per-user Karpathy
 * autoresearch loop). The page delivers two views in one tab:
 *
 *   * **Per-tenant overview**: total experiments run, win rate, top
 *     movers (positions whose headline metric improved most this week),
 *     latest 10 experiments.
 *   * **Per-user view**: filter by selected viewer; their headline
 *     metrics over time (sparkline), their experiments queue, their
 *     wins, what the worm wants to try next (with approve / discard).
 *
 * Live polling every 10s via /api/research/refresh; the autoresearch
 * loop runs at 30s in dev so new entries land within one cycle.
 */
export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const audience = asAudience(params.audience);
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const [overview, registry, allExperiments, compositeSeries, keepRateRows] =
    await Promise.all([
      getResearchOverview(companyId),
      getPositionsRegistry(companyId),
      getExperimentsForUser(companyId, undefined, 50),
      getCompositeScoreSeries(companyId, 9, 7),
      getKeepRateSeries(companyId, 7),
    ]);

  // W5.A5 — audience-scoped slice. ``mine`` is the default; the
  // legacy unfiltered view is preserved when no audience is set + the
  // current Person can't be resolved (defensive fallback).
  const audienceFiltered = me
    ? await getExperimentsByAudience(audience, me.personId, companyId)
    : allExperiments;

  // For the initial render, default to "all" — the client component handles
  // per-user filtering once the operator picks somebody from the dropdown.
  const initialPersonId = registry[0]?.personId ?? null;
  const initialPosition = registry[0]?.position ?? null;
  const history = initialPosition
    ? await getHeadlineMetricsHistory(companyId, initialPosition)
    : null;

  // Demo-day P9 — per-scope ``experiment_lesson`` rows for the LessonsCard.
  // Always fetched (cheap aggregation) so the card can render its empty
  // state honestly when no lessons exist yet.
  const lessonsByScope = await getExperimentLessonsByScope(companyId, 5);

  // Demo-day P12 — un-confirmed worm-detected phenomena. Altman Q1: "What
  // does the worm know that the org's CDO doesn't, with the ledger entry
  // where it knew it first?" Empty list renders an honest empty-state
  // message in the tab; no fixture fallback (CLAUDE.md ¶9).
  const firstKnowings = await getFirstKnowings(companyId, {
    recency: "all",
    limit: 50,
  });

  if (registry.length === 0 && allExperiments.length === 0) {
    return (
      <PageBoundary surface="research" traceQuery="?surface=research">
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
            Pl. IX · Self-improve per user · live
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
            Research
          </h1>
        </header>
        <AudienceTabs current={audience} />
        <EmptyState
          testId="research-empty"
          eyebrow="no experiments yet"
          title="The per-position autoresearch loop fires once a Person has a position."
          description={
            "Once a confirmed Person has a position and a headline metric to " +
            "move, the worm proposes overnight experiments, keeps wins, " +
            "discards losses, and surfaces the loop here. The loop runs every " +
            "30s in dev so the first experiment lands within a cycle of the " +
            "first position assignment. Assign positions on /people to begin."
          }
          cta={{ label: "Assign positions on /people", href: "/people" }}
          secondaryCta={{ label: "See what the worm has decided", href: "/decisions" }}
        />
      </PageBoundary>
    );
  }

  return (
    <PageBoundary surface="research" traceQuery="?surface=research">
      <AudienceTabs current={audience} />
      <ResearchView
        initialOverview={overview}
        initialRegistry={registry}
        initialExperiments={audienceFiltered}
        initialPersonId={initialPersonId}
        initialPosition={initialPosition}
        initialHistory={history}
      />
      {/*
        Demo-day P1 — composite_score curve + per-scope keep-rate baseline.
        Appended below the existing per-user research view; both components
        carry their own honest empty state when the ledger is empty.
      */}
      <CompositeScoreCard series={compositeSeries} />
      <KeepRateChart rows={keepRateRows} />
      {/*
        Demo-day P9 — per-scope ``experiment_lesson`` card. Closes the
        Karpathy autoresearch loop on itself: every kept experiment writes a
        structured lesson; the next proposer reads it. Click any row to
        jump to /trace at the lesson's prior_keep_id.
      */}
      <LessonsCard byScope={lessonsByScope} />
      {/*
        Demo-day P12 — First-Knowing surface. Lists every phenomenon the
        worm has proposed (KPI/Domain/Process/Reactivity/Person gap) whose
        confirmation has not yet landed. Each row deep-links to the
        InfraEvent that triggered it plus a ±3 chatter-context window.
        Altman Q1 made readable.
      */}
      <FirstKnowingsTab rows={firstKnowings} />
    </PageBoundary>
  );
}
