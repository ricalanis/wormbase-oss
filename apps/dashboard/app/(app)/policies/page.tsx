import { getDomains, getPolicies } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { PolicyTable } from "../../../components/policies/PolicyTable";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Policies" };

/**
 * /policies — Step 3b of the canonical product arc. Sortable table with
 * inline classification editing. Polls /api/governance/policy every 10s so
 * the audience sees classification changes ratify into the live ledger
 * without a page reload.
 */
export default async function PoliciesPage() {
  const companyId = await getCurrentCompanyId();
  const [policies, domains] = await Promise.all([
    getPolicies(companyId),
    getDomains(companyId),
  ]);

  return (
    <PageBoundary surface="policies" traceQuery="?surface=policies">
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
          Pl. IX · Policy register · live
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
          Policies · {policies.length}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Click the classification cell to reclassify; click a column header to sort.
          Every change re-emits a policy_applied entry to the ledger.
        </p>
      </header>
      {policies.length === 0 ? (
        <EmptyState
          testId="policies-empty"
          eyebrow="no policies yet"
          title="The worm hasn't loaded a policy pack yet."
          description={
            "Policies (PII redaction, warmup gating, interjection budget) ship " +
            "with the default pack and apply automatically once warmup runs. " +
            "Complete onboarding to seed the canonical pack, then return here " +
            "to inspect, edit, or scope per-channel rules."
          }
          cta={{ label: "Run the wizard", href: "/onboarding" }}
        />
      ) : (
        <PolicyTable initialPolicies={policies} initialDomains={domains} />
      )}
    </PageBoundary>
  );
}
