import Link from "next/link";
import { getKpiTree } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { KpiTreeView } from "../../../components/kpi/KpiTreeView";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  getDomainAccessSet,
  memberHasNoAccess,
} from "../../../lib/server/role-filter";
import { MemberAccessBanner } from "../../../components/chrome/MemberAccessBanner";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { ProposeKpiModal } from "../../../components/kpis/ProposeKpiModal";
import { KpiDomainFilter } from "../../../components/kpis/KpiDomainFilter";
import type { KpiNodeRow } from "../../../lib/ledger-client.types";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · KPIs" };

function flatten(n: KpiNodeRow): { count: number } {
  let c = 1;
  for (const child of n.children) c += flatten(child).count;
  return { count: c };
}

/**
 * /kpis — Step 3a of the canonical product arc (`docs/superpowers/specs/
 * 2026-04-26-wormbase-product-arc.md`). The KPI tree is rendered as an
 * interactive React Flow graph; the audience sees nodes appear, statuses
 * flip, and confidence move as the worm reasons live. The view client-polls
 * /api/kpi-tree/refresh every 5s — that's the "live polling makes the worm
 * feel alive" effect the runbook author quotes.
 */
export default async function KpiPage() {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const access = await getDomainAccessSet(companyId, me);
  const noAccess = memberHasNoAccess(me, access);
  const root = await getKpiTree(companyId);
  const total = root ? flatten(root).count : 0;

  return (
    <PageBoundary surface="kpis" traceQuery="?surface=kpis">
      <MemberAccessBanner show={noAccess} surface="kpis" />
      <header
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
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
          Pl. VII · KPI tree · live
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
            KPI relational · {total} nodes
          </h1>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            {root ? (
              <Link
                href="/kpis/compare"
                data-testid="kpis-compare-link"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-paper-deep)",
                  color: "var(--wb-color-aged-ink)",
                }}
              >
                Compare two replays
              </Link>
            ) : null}
            {root ? <ProposeKpiModal /> : null}
          </div>
        </div>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Edge color encodes confidence: green &gt; 0.8, gray 0.4–0.8, sepia &lt; 0.4.
          Click any node to inspect its receipt. View polls every 5s.
        </p>
        {root ? (
          <div
            data-testid="kpis-toolbar"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              paddingTop: 8,
            }}
          >
            <KpiDomainFilter />
          </div>
        ) : null}
      </header>
      {root ? (
        <KpiTreeView initial={root} />
      ) : (
        <EmptyState
          testId="kpis-empty"
          eyebrow="no kpis yet"
          title="The worm hasn't proposed any KPIs yet."
          description={
            "When your team asks \"what's our X\" in chat, the worm proposes a KPI " +
            "node and links it to the source data behind the answer. Connect a " +
            "data source or invite the worm to lurk in a channel where revenue, " +
            "retention, or activation comes up. You can also propose the first " +
            "KPI yourself — it lands in the ledger and the worm threads it into " +
            "the tree on the next refresh."
          }
          cta={{ label: "Add a source", href: "/sources/new" }}
          secondaryCta={{ label: "Invite the worm", href: "/channels" }}
        />
      )}
      {!root ? (
        <div
          data-testid="kpis-empty-actions"
          style={{ display: "flex", justifyContent: "flex-start" }}
        >
          <ProposeKpiModal />
        </div>
      ) : null}
    </PageBoundary>
  );
}
