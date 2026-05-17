import { CatalogTable } from "../../../../components/lake-catalog/CatalogTable";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { getCatalogTables } from "../../../../lib/lake-catalog";

export const metadata = { title: "WormBase · Lake catalog" };

export const dynamic = "force-dynamic";

/**
 * /lake/catalog — Semantic Layer Wave 3 Task 1.
 *
 * Renders the most-recent ``external_catalog_imported`` snapshot per
 * connected catalog source: dbt manifest, Snowflake native catalog,
 * Cube semantic layer, … Each row shows table count, edge count,
 * metric count + lineage edge counts so the operator can see at a
 * glance which upstream lakes the worm has mirrored.
 *
 * Empty state is honest: when no catalog has been imported yet, the
 * page surfaces the catalog-source connect affordance instead of a
 * fixture. The first row appears within seconds of a
 * ``source_profiled`` cascade firing the catalog-mirror Reactivity.
 *
 * Filters:
 *
 *   * ``?domain=<uuid>`` — restrict to a single Domain
 *   * ``?q=<substring>`` — case-insensitive substring on source_kind
 *
 * Both are pass-through query params; the SQL pushes them into the
 * accessor and skips fetching everything-and-filtering-in-memory.
 */

function asString(v: string | string[] | undefined): string | undefined {
  if (typeof v === "string" && v.length > 0) return v;
  if (Array.isArray(v) && v.length > 0 && typeof v[0] === "string") return v[0];
  return undefined;
}

export default async function LakeCatalogPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}): Promise<JSX.Element> {
  const params = await searchParams;
  const domainId = asString(params.domain);
  const search = asString(params.q);
  const companyId = await getCurrentCompanyId();
  const tables = await getCatalogTables(companyId, {
    domainId,
    search,
  });

  const filtered = Boolean(domainId || search);

  return (
    <PageBoundary surface="lake catalog" traceQuery="?surface=lake.catalog">
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
          Semantic layer · catalog mirror · live
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
          Lake catalog · {tables.length}{" "}
          {tables.length === 1 ? "source" : "sources"}
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
          The worm mirrors every connected catalog source into the ledger.
          Each row is the most-recent snapshot — table count, lineage edges,
          and semantic-layer metrics — with the snapshot hash that drift
          detection compares against on every refresh pass.
        </p>
      </header>

      {tables.length === 0 ? (
        filtered ? (
          <EmptyState
            testId="lake-catalog-empty-filtered"
            eyebrow="no matching catalogs"
            title="No catalogs match this filter."
            description={
              "Try widening the search or clearing the domain filter. The " +
              "worm mirrors every connected dbt / Snowflake / Cube source " +
              "automatically — if nothing shows up, the source may not be " +
              "connected yet."
            }
            cta={{ label: "Add a data source", href: "/sources/new" }}
            secondaryCta={{ label: "Clear filters", href: "/lake/catalog" }}
          />
        ) : (
          <EmptyState
            testId="lake-catalog-empty"
            eyebrow="no catalogs yet"
            title="No catalogs imported yet."
            description={
              "Connect a dbt or Snowflake source via /sources/new to populate. " +
              "The catalog-mirror worm runs on every source-profiled cascade — " +
              "the first snapshot lands within a minute of the source being " +
              "connected."
            }
            cta={{ label: "Connect a source", href: "/sources/new" }}
            secondaryCta={{ label: "See raw activity", href: "/activity" }}
          />
        )
      ) : (
        <CatalogTable rows={tables} />
      )}
    </PageBoundary>
  );
}
