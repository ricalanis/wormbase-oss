/**
 * /onboard — unified onboarding landing page
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * 7-tab navigation surface: chat / source / domain / person / policy /
 * agent / subscription. Each tile shows a ready/pending status snapshot
 * from the relevant ledger projection. Existing per-tier wizard pages
 * at /onboarding/tier-{0,1,2,3} stay untouched and continue to handle
 * the linear install flow; /onboard is the consolidated surface where
 * an admin can pick which object kind to extend next.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../components/chrome/PageBoundary";
import {
  getOnboardLandingSnapshot,
  type OnboardTabSummary,
} from "../../../lib/onboard";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard" };

export const dynamic = "force-dynamic";

export default async function OnboardLandingPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const snapshot = await getOnboardLandingSnapshot(companyId);
  return (
    <PageBoundary
      surface="onboard"
      traceQuery="?surface=onboard"
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          institutional onboarding · unified surface
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
          Onboard
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
          One surface for every onboarding act. Pick a tab to extend the
          tenant — connect a chat platform, add a data source, pick a
          domain pack, invite a co-admin, scan the policy registry, or
          register an agent + subscription. Each tile shows the current
          ready/pending count from the live ledger.
        </p>
      </header>

      <ul
        data-testid="onboard-tab-grid"
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 14,
        }}
      >
        {snapshot.tabs.map((tab) => (
          <OnboardTabCard key={tab.tab} tab={tab} />
        ))}
      </ul>
    </PageBoundary>
  );
}

interface OnboardTabCardProps {
  tab: OnboardTabSummary;
}

function OnboardTabCard({ tab }: OnboardTabCardProps): JSX.Element {
  const href = `/onboard/${tab.tab}`;
  return (
    <li
      data-testid={`onboard-tab-${tab.tab}`}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <Link
        href={href}
        data-testid={`onboard-tab-link-${tab.tab}`}
        style={{
          textDecoration: "none",
          color: "inherit",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
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
            @onboard {tab.tab}
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            {tab.label}
          </h2>
        </header>
        <div
          data-testid={`onboard-tab-counts-${tab.tab}`}
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink)",
            display: "flex",
            gap: 12,
          }}
        >
          <span data-testid={`onboard-tab-ready-${tab.tab}`}>
            ready: {tab.ready}
          </span>
          <span data-testid={`onboard-tab-pending-${tab.tab}`}>
            pending: {tab.pending}
          </span>
          <span data-testid={`onboard-tab-total-${tab.tab}`}>
            total: {tab.total}
          </span>
        </div>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {tab.hint}
        </p>
      </Link>
    </li>
  );
}
