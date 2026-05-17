import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { PolicySideBySide } from "../../../../components/lake-governance/PolicySideBySide";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getExternalPolicies,
  getWormbasePolicies,
} from "../../../../lib/lake-governance";

export const metadata = { title: "WormBase · Lake governance" };

export const dynamic = "force-dynamic";

/**
 * /lake/governance — Semantic Layer Wave 3 Task 6.
 *
 * Side-by-side comparison of upstream catalog governance (Snowflake
 * masking + row-access policies mirrored via the catalog-mirror data
 * plane) versus WormBase-side governance (warmup pack, PII redaction,
 * interjection budget, channel talkativeness).
 *
 * The two columns are independent reads — either may be empty without
 * affecting the other. Combined empty state surfaces an honest "no
 * policies yet" affordance with a pointer to /sources/new (to start
 * mirroring an upstream catalog) and /policies (the WormBase policy
 * register).
 *
 * S2 spike surfacing: when an upstream policy's body is NULL (the
 * catalog credential lacks APPLY), the card renders the
 * "Body unavailable (insufficient APPLY privilege)" placeholder
 * rather than hiding the policy or pretending the body exists.
 *
 * Filters:
 *
 *   * ``?source=<uuid>`` — restrict the upstream column to a single
 *     mirrored source. The WormBase column is unfiltered (its
 *     policies aren't scoped to upstream sources).
 *
 * Live: ``getExternalPolicies`` + ``getWormbasePolicies`` run in
 * parallel via ``Promise.all`` so the page hits the ledger /
 * projection store once per request, with the same latency
 * characteristics as /lake/catalog.
 */

function asString(v: string | string[] | undefined): string | undefined {
  if (typeof v === "string" && v.length > 0) return v;
  if (Array.isArray(v) && v.length > 0 && typeof v[0] === "string") return v[0];
  return undefined;
}

export default async function LakeGovernancePage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}): Promise<JSX.Element> {
  const params = await searchParams;
  const sourceId = asString(params.source);
  const companyId = await getCurrentCompanyId();

  const [externalPolicies, wormbasePolicies] = await Promise.all([
    getExternalPolicies(companyId, { sourceId }),
    getWormbasePolicies(companyId, { sourceId }),
  ]);

  const bothEmpty =
    externalPolicies.length === 0 && wormbasePolicies.length === 0;
  const filtered = Boolean(sourceId);

  return (
    <PageBoundary
      surface="lake governance"
      traceQuery="?surface=lake.governance"
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
          Semantic layer · governance · side-by-side
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
          Lake governance
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
          Upstream masking + row-access policies mirrored from connected
          catalogs are shown alongside WormBase-applied policies so the
          operator can compare what the upstream lake enforces with what
          WormBase enforces on its own. Read-only catalog credentials
          can&apos;t fetch policy SQL — those bodies surface as
          &ldquo;unavailable&rdquo; rather than disappearing.
        </p>
      </header>

      {bothEmpty ? (
        filtered ? (
          <EmptyState
            testId="lake-governance-empty-filtered"
            eyebrow="no matching policies"
            title="No policies for this source."
            description={
              "Try clearing the source filter to see the full register. " +
              "Upstream policies appear once the catalog-mirror Reactivity " +
              "runs against the connected source."
            }
            cta={{
              label: "Clear filter",
              href: "/lake/governance",
            }}
            secondaryCta={{
              label: "See connected sources",
              href: "/lake/catalog",
            }}
          />
        ) : (
          <EmptyState
            testId="lake-governance-empty"
            eyebrow="no policies yet"
            title="No governance to compare yet."
            description={
              "Connect a Snowflake / dbt source via /sources/new to mirror " +
              "upstream masking + row-access policies, and run onboarding " +
              "to seed the WormBase policy pack. Both columns populate " +
              "automatically as the worm runs."
            }
            cta={{ label: "Connect a source", href: "/sources/new" }}
            secondaryCta={{ label: "Policy register", href: "/policies" }}
          />
        )
      ) : (
        <PolicySideBySide
          externalPolicies={externalPolicies}
          wormbasePolicies={wormbasePolicies}
        />
      )}
    </PageBoundary>
  );
}
