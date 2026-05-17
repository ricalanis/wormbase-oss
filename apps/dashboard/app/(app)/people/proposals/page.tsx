/**
 * /people/proposals — admin queue for worm-proposed positions.
 *
 * Wave H Phase 2 Task 2C — Position Auto-Confirm UX.
 *
 * Reads the pending proposal queue server-side from worm-core's
 * ``GET /api/v1/people/proposals`` (folded directly from the ledger,
 * not via projections — works on a fresh-replay tenant before
 * projections rebuild). Renders the ``PositionProposalQueue`` client
 * component, which wires confirm / reject actions to the dashboard
 * route proxies.
 *
 * Linked from ``/people`` via the proposal-count badge added in the
 * same task.
 */
import { listPositionProposals } from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";
import { PositionProposalQueue } from "../../../../components/people/PositionProposalQueue";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Position proposals" };

export const dynamic = "force-dynamic";

export default async function PositionProposalsPage() {
  const tenant = await getTenantFromCookies();
  let proposals: Awaited<
    ReturnType<typeof listPositionProposals>
  >["proposals"] = [];
  try {
    const result = await listPositionProposals(tenant.slug);
    proposals = result.proposals;
  } catch {
    // Honest empty state when worm-core is unreachable; the panel
    // surfaces "No pending proposals" rather than a stale fixture.
    proposals = [];
  }

  return (
    <PageBoundary
      surface="position-proposals"
      traceQuery="?surface=position-proposals"
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
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
            Pl. IV.b · Governance lens
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
            Position proposals
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {proposals.length} pending. Each proposal is a worm-inferred
            role waiting for an admin sign-off — confirm to keep, reject
            to clear and let richer signal accumulate.
          </p>
        </div>
      </header>
      <PositionProposalQueue proposals={proposals} />
    </PageBoundary>
  );
}
