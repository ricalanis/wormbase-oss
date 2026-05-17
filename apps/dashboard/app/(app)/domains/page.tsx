import {
  getDataProducts,
  getDomains,
  getPeople,
  getSources,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import { DomainCardGrid } from "../../../components/domains/DomainCardGrid";
import { DomainDataProducts } from "../../../components/domains/DomainDataProducts";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Domains" };

/**
 * /domains — Step 3b of the canonical product arc (governance lens). The
 * audience-visible view of the worm's governance bookkeeping. Each domain is
 * a card with inline owner editing and drag-and-drop resource assignment;
 * the page polls /api/governance/domain every 10s so the audience sees the
 * worm "ratify" governance changes live.
 */
export default async function DomainsPage() {
  const companyId = await getCurrentCompanyId();
  const [domains, people, sources, dataProducts, me] = await Promise.all([
    getDomains(companyId),
    getPeople(companyId),
    getSources(companyId),
    getDataProducts(companyId),
    getCurrentPerson(companyId),
  ]);

  // Map sources into a draggable resource shape. The /domains card grid is
  // about governance over resources; the source list is the most concrete
  // resource set we have today (KPIs and policies are governed-but-not-
  // draggable in this view).
  const resources = sources.map((s) => ({
    id: s.sourceId,
    label: s.uri,
    classification: s.receipt.classification,
  }));

  return (
    <PageBoundary surface="domains" traceQuery="?surface=domains">
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
          Pl. V · Governance lens · live
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
          Domains · {domains.length}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Click @owner to reassign. Drag a resource into a domain to govern it.
          Every change writes a propose → execute → verify → resolve cycle to the ledger.
        </p>
      </header>
      {domains.length === 0 ? (
        <EmptyState
          testId="domains-empty"
          eyebrow="no domains yet"
          title="The worm hasn't registered any domains yet."
          description={
            "Domains are functional areas (sales, finance, product) the worm uses " +
            "to scope ownership, classification defaults, and policy. Pick a " +
            "domain pack in onboarding, or connect a source — the worm will " +
            "propose a domain from the source's shape."
          }
          cta={{ label: "Run the wizard", href: "/onboarding" }}
          secondaryCta={{ label: "Add source", href: "/sources/new" }}
        />
      ) : (
        <>
          <DomainCardGrid
            initialDomains={domains}
            initialPeople={people}
            initialResources={resources}
            currentPersonId={me?.personId ?? null}
          />
          <DomainDataProducts domains={domains} dataProducts={dataProducts} />
        </>
      )}
    </PageBoundary>
  );
}
