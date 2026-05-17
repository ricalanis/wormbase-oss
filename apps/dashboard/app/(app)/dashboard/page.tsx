import { Card } from "@wormbase/design";
import { RampGauges } from "../../../components/RampGauges";
import { RampGauge } from "../../../components/dashboard/RampGauge";
import { TimeToAhaPanel } from "../../../components/onboarding/TimeToAhaPanel";
import { PostInstallBanner } from "../../../components/onboarding/PostInstallBanner";
import { WormActivityTile } from "../../../components/dashboard/WormActivityTile";
import { SlackWelcomeMoment } from "../../../components/dashboard/SlackWelcomeMoment";
import { AskTheWormPanel } from "../../../components/dashboard/AskTheWormPanel";
import { EvaluatorWelcomeBanner } from "../../../components/dashboard/EvaluatorWelcomeBanner";
import { ActivityRollupLine } from "../../../components/dashboard/ActivityRollupLine";
import { Receipt } from "../../../lib/receipts";
import { EmptyState } from "../../../components/chrome/EmptyState";
import {
  getRampValues,
  getDomains,
  getOnboardingMilestones,
  getWormActivitySummary,
  getFirstWormMessage,
  getKnowledgeRampGauges,
  getActivityRollup,
} from "../../../lib/ledger-client";
import { getCurrentInstall } from "../../../lib/server/identity";
import { readAndBumpLastSeen } from "../../../lib/server/last-seen";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = {
  title: "WormBase · Dashboard",
};

interface DashboardPageProps {
  // Phase 4C — magic-link evaluators land on /dashboard?welcome=email so
  // the EvaluatorWelcomeBanner above renders. Other welcome sources can
  // be added; unrecognized values render nothing (forward-compat).
  searchParams?: Promise<{ welcome?: string }>;
}

export default async function DashboardPage({
  searchParams,
}: DashboardPageProps) {
  const tenant = await getTenantFromCookies();
  const companyId = tenant.companyId;
  const welcomeSource = (await searchParams)?.welcome;
  // Phase 3 Task 3A — read the prior last-seen timestamp (bumping the
  // cookie to "now") so the digest tile reads "since you logged off"
  // on every visit after the first. First visits return null → the
  // helper falls back to "since install" copy honestly.
  const sinceTs = await readAndBumpLastSeen(tenant.slug);
  const [
    axes,
    domains,
    milestones,
    install,
    activity,
    firstWormMsg,
    knowledgeRamp,
    activityRollup,
  ] = await Promise.all([
    getRampValues(companyId),
    getDomains(companyId),
    getOnboardingMilestones(companyId),
    getCurrentInstall(companyId),
    getWormActivitySummary(companyId, sinceTs),
    getFirstWormMessage(companyId),
    getKnowledgeRampGauges(companyId),
    // W4-C — last-24h per-platform digest line. Independent of the
    // "since you logged off" tile above; this one is fixed-window so
    // it reads the same on every visit and grounds the worm's recent
    // activity even when the user just logged off.
    getActivityRollup(companyId),
  ]);

  return (
    <PageBoundary surface="dashboard" traceQuery="?surface=dashboard">
      <EvaluatorWelcomeBanner
        source={welcomeSource}
        tenantDisplayName={tenant.displayName}
      />

      <WormActivityTile summary={activity} />

      <ActivityRollupLine rollup={activityRollup} />

      <AskTheWormPanel />

      {firstWormMsg ? <SlackWelcomeMoment message={firstWormMsg} /> : null}

      {install ? (
        <PostInstallBanner
          setupMode={install.setupMode}
          setupCompletedAt={install.setupCompletedAt}
        />
      ) : null}

      <TimeToAhaPanel milestones={milestones} />

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
          Plate I · Ramp
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
          Knowledge ramp · live
        </h1>
      </header>

      {axes.length === 0 ? (
        <EmptyState
          testId="ramp-gauges-empty"
          eyebrow="no ramp snapshot yet"
          title="The worm hasn't moved a ramp axis yet."
          description={
            "Six axes — ontology, schema, business definitions, KPI relational, " +
            "conversational, operational — each rise as the worm confirms " +
            "concepts, profiles tables, and lurks in channels. Run onboarding " +
            "or connect a chat platform; the first snapshot lands within a " +
            "minute of the first wire event."
          }
          cta={{ label: "Run the wizard", href: "/onboarding" }}
          secondaryCta={{ label: "Connect a chat platform", href: "/channels" }}
        />
      ) : (
        <RampGauges axes={axes} />
      )}

      {/* P2 — Knowledge Ramp counter gauges (additive; the existing six-axis
          arc gauges above persist unchanged). Three integer counters +
          sparklines wired to ledger projections; click any tile to deep-link
          /trace pre-filtered to that entry kind. */}
      <section
        aria-label="Knowledge ramp · counters"
        data-testid="knowledge-ramp-section"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
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
            Plate II · counters · ledger-projected
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
            Knowledge ramp · live counts
          </h2>
        </header>
        <div
          data-testid="knowledge-ramp-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 16,
          }}
        >
          {knowledgeRamp.gauges.map((g) => (
            <RampGauge
              key={g.axis}
              axis={g.axis}
              label={g.label}
              count={g.count}
              sparkline={g.sparkline}
              emptyHint={g.emptyHint}
              populatedHint={g.populatedHint}
              traceFilter={g.traceFilter}
              lastSeq={g.lastSeq}
              lastTs={g.lastTs}
            />
          ))}
        </div>
      </section>

      {domains.length === 0 ? (
        <EmptyState
          testId="dashboard-domains-empty"
          eyebrow="no domains yet"
          title="No governance domains registered."
          description={
            "Domains scope ownership, classification, and policy. Pick a domain " +
            "pack (saas / fintech / marketplace) during onboarding and the " +
            "worm seeds the first set."
          }
          cta={{ label: "Run the wizard", href: "/onboarding" }}
        />
      ) : (
        <Card eyebrow="PROJECTION · governance" title={`${domains.length} domains ready`}>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              lineHeight: 1.55,
            }}
          >
            Onboarding Tier 2 seeded {domains.length} domains with default
            classifications. Owners are assigned. Sources are connected via the
            five worm-driven flows; see <span className="wb-mono">/sources</span>{" "}
            for provenance.
          </p>
          <ul
            data-testid="dashboard-domain-list"
            style={{
              marginTop: 16,
              padding: 0,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
              listStyle: "none",
            }}
          >
            {domains.map((d) => (
              <li
                key={d.domainId}
                style={{
                  border: "1px solid var(--wb-color-paper-edge)",
                  padding: 12,
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 18,
                    fontWeight: 500,
                  }}
                >
                  {d.name}
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                    letterSpacing: "0.04em",
                  }}
                >
                  owner @{d.owner} · class {d.classificationDefault} ·{" "}
                  {d.resourceCount} resources
                </span>
                <Receipt
                  hash={d.receipt.hash}
                  source={d.receipt.source}
                  owner={d.receipt.owner}
                  classification={d.receipt.classification}
                  compact
                />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageBoundary>
  );
}
