/**
 * /lake/overview — Lake-Side Overview tab (2026-05-16).
 *
 * Single landing surface for the 8-axis lake-side compounding
 * architecture. Three sections:
 *
 *   1. Axis status — 4×2 grid of per-axis cards with proposed /
 *      affirmed / rejected counts. Honors the 3-pattern affirmative-
 *      state doctrine (L3/L4/L5/L6/L7/L8 → confirmed, L1 → promoted,
 *      L2 → acknowledged).
 *
 *   2. Cross-axis chains — 7-row panel listing every chain in the
 *      lake stack with producer + consumer page links. One row is
 *      bidirectional (L4 ↔ L2).
 *
 *   3. Recent activity — last 20 state-changes across all 8 axes,
 *      with relative timestamps + drill-in links using the producer-
 *      side deep-link primary-key URL params from ``bdee480`` where
 *      the axis page supports them.
 *
 * Admin-only (consistent with all /lake/* tabs). The role-nav guard
 * lives in ``lib/role-nav.ts``; the page itself trusts the nav guard
 * + computes ``isAdmin`` from the current Person's tenancy role for
 * the receipt only — no admin-write actions on this surface.
 */
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { AxisStateGrid } from "../../../../components/lake/AxisStateGrid";
import { CrossAxisChainTable } from "../../../../components/lake/CrossAxisChainTable";
import { RecentActivityStream } from "../../../../components/lake/RecentActivityStream";
import {
  getLakeAxisStates,
  getLakeChains,
  getRecentLakeActivity,
} from "../../../../lib/lake-overview";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Lake · Overview" };

export const dynamic = "force-dynamic";

export default async function LakeOverviewPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();

  const [axisStates, activity] = await Promise.all([
    getLakeAxisStates(companyId),
    getRecentLakeActivity(companyId, 20),
  ]);
  const chains = getLakeChains();

  const totalAxisRows = axisStates.reduce(
    (acc, r) => acc + r.proposedCount + r.affirmedCount + r.rejectedCount,
    0,
  );

  return (
    <PageBoundary surface="lake overview" traceQuery="?surface=lake.overview">
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
          Semantic layer · lake overview · admin
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
          Lake-Side Overview
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
          One screen across the 8-axis compounding architecture. Each
          axis proposes, each axis is audited, every state change folds
          forward. Seven cross-axis chains carry evidence between
          axes — the spine of the lake-side stack.
        </p>
      </header>

      <section
        data-testid="lake-overview-section-axis"
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
      >
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
            Axis status · 8 axes · {totalAxisRows} rows tracked
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink)",
              fontSize: 13,
              maxWidth: 720,
            }}
          >
            Per-axis state count: proposed + the per-axis affirmative
            state (confirmed / promoted / acknowledged) + rejected.
            Cards link to the axis's detail page for confirm/reject
            actions.
          </p>
        </header>
        <AxisStateGrid rows={axisStates} />
      </section>

      <section
        data-testid="lake-overview-section-chains"
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
      >
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
            Cross-axis chains · {chains.length} chains
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink)",
              fontSize: 13,
              maxWidth: 720,
            }}
          >
            Each chain forwards evidence from one axis to another —
            confirmed L5 fingerprints become L7 quality checks,
            classified L6 columns elevate L4 impact severity, and so
            on. One chain (L4 ↔ L2) carries data in both directions.
          </p>
        </header>
        <CrossAxisChainTable rows={chains} />
      </section>

      <section
        data-testid="lake-overview-section-activity"
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
      >
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
            Recent activity · {activity.length}
            {activity.length === 20 ? " · capped at 20" : ""}
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink)",
              fontSize: 13,
              maxWidth: 720,
            }}
          >
            The most recent state changes across all 8 lake axes,
            newest first. Each row links into the producing axis page
            — deep-linked to the row's primary key when the page
            honors that filter.
          </p>
        </header>
        {totalAxisRows === 0 && activity.length === 0 ? (
          <EmptyState
            testId="lake-overview-empty"
            eyebrow="lake idle"
            title="No lake activity yet."
            description={
              "The 8 lake-side inference axes fire on source_connected " +
              "and external_catalog_imported cascades. Enable an axis " +
              "(WORMBASE_LINEAGE_DISCOVERY_ENABLED + the per-axis " +
              "sub-knobs), connect a source, and proposals begin landing " +
              "within the next compounding window."
            }
            cta={{ label: "Connect a source", href: "/sources/new" }}
            secondaryCta={{ label: "See raw activity", href: "/activity" }}
          />
        ) : (
          <RecentActivityStream rows={activity} />
        )}
      </section>
    </PageBoundary>
  );
}
