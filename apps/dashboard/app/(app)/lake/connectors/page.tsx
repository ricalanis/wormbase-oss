/**
 * /lake/connectors — L3 Sub-wave D (2026-05-29).
 *
 * Marketplace shell: read-only catalog of the Connector registry,
 * grouped by status (PRODUCTION / PREVIEW / COMING SOON), with
 * per-tenant connection state per row.
 *
 * Reads from the dashboard's ``/api/v1/connectors/list`` proxy which
 * forwards to worm-core's ``GET /api/v1/connectors``. On registry
 * unreachable, the page falls back to the static
 * ``CONNECTOR_CATALOG`` so the marketplace still renders with an
 * honest "registry unreachable" banner.
 */
import Link from "next/link";

import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { ConnectorCatalogRow } from "../../../../components/lake/ConnectorCatalogRow";
import { getConnectorCatalog } from "../../../../lib/connectors";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Lake · Connectors" };

export const dynamic = "force-dynamic";

export default async function LakeConnectorsPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const catalog = await getConnectorCatalog(companyId);
  const totalRows =
    catalog.production.length + catalog.preview.length + catalog.comingSoon.length;
  const connectedCount = [
    ...catalog.production,
    ...catalog.preview,
  ].filter((c) => c.connectionState === "connected").length;

  return (
    <PageBoundary
      surface="lake connectors"
      traceQuery="?surface=lake.connectors"
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Lake · connector marketplace · read-only catalog
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
            Connectors · {totalRows} kinds · {connectedCount} connected
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
            Every connector the worm knows how to talk to. Status badges
            reflect the Python registry's runtime capability — promote a
            kind by editing exactly one place (the Connector class).
            "Add source" routes to the existing connector-picker flow.
          </p>
        </div>
        <Link
          href="/sources/new"
          data-testid="lake-connectors-add-source-cta"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-aged-ink)",
            color: "var(--wb-color-paper)",
            textDecoration: "none",
          }}
        >
          Add source…
        </Link>
      </header>

      {catalog.registryUnreachable ? (
        <div
          data-testid="lake-connectors-registry-unreachable"
          role="alert"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-paper-deep)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            connector registry unreachable
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Showing the static catalog fallback so the marketplace still
            renders. Real-time status will resume when worm-core is
            reachable. {catalog.registryError ?? null}
          </span>
        </div>
      ) : null}

      {totalRows === 0 ? (
        <EmptyState
          testId="lake-connectors-empty"
          eyebrow="no connectors registered"
          title="The connector registry returned no kinds."
          description={
            "The Python registry at packages/connectors/ is the source " +
            "of truth — if this list is empty, the worm-core service is " +
            "likely starting up or the WORMBASE_LEDGER_API_BASE env " +
            "var is misconfigured."
          }
          cta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          <CatalogSection
            heading="Production"
            description="Production-ready connectors. Every method wired against the real platform."
            rows={catalog.production}
            testId="lake-connectors-production"
          />
          <CatalogSection
            heading="Preview"
            description="Wired end-to-end against the real platform but pending production graduation (operator-approved scopes / scale validation)."
            rows={catalog.preview}
            testId="lake-connectors-preview"
          />
          <CatalogSection
            heading="Coming soon"
            description="Connector skeleton present; full integration lands in a future wave. The 'Notify me' affordance is wired for v1.5."
            rows={catalog.comingSoon}
            testId="lake-connectors-coming-soon"
          />
        </>
      )}
    </PageBoundary>
  );
}

interface CatalogSectionProps {
  heading: string;
  description: string;
  rows: Awaited<ReturnType<typeof getConnectorCatalog>>["production"];
  testId: string;
}

function CatalogSection({
  heading,
  description,
  rows,
  testId,
}: CatalogSectionProps): JSX.Element | null {
  if (rows.length === 0) return null;
  return (
    <section
      data-testid={testId}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
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
          {heading} · {rows.length}
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 12,
          }}
        >
          {description}
        </p>
      </header>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          border: "1px solid var(--wb-color-paper-edge)",
          borderTop: "none",
        }}
      >
        {rows.map((row) => (
          <ConnectorCatalogRow key={row.kind} row={row} />
        ))}
      </ul>
    </section>
  );
}
