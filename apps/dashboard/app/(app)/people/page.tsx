/**
 * /people — production surface (A5 + W2.A6).
 *
 * Composes the layout: editorial header, BulkConfirmDrawer (auto-discovered
 * pending proposals; one-shot bulk-confirm), the active People roster
 * (sortable table; row click opens PersonDetailDrawer), and the
 * IdentityMergePanel (admin-driven multi-platform-identity merge with
 * irreversibility-confirmation). The legacy InviteModal stays for the
 * platform-handle-known invite flow; W2.A6's InviteByEmailModal is the
 * production-hardened email + position entry point.
 *
 * Reads from the live ledger via `getPeople`; writes flow through the
 * /api/people and /api/v1/people/* endpoints (hash-chained PEVR via
 * worm-core).
 */
import Link from "next/link";
import { getPeople } from "../../../lib/ledger-client";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import { listPositionProposals } from "../../../lib/server/worm-core-write";
import { BulkConfirmDrawer } from "../../../components/people/BulkConfirmDrawer";
import { IdentityMergePanel } from "../../../components/people/IdentityMergePanel";
import { InviteByEmailModal } from "../../../components/people/InviteByEmailModal";
import { InviteModal } from "../../../components/people/InviteModal";
import { PeopleRoster } from "../../../components/people/PeopleRoster";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · People" };

export default async function PeoplePage() {
  const tenant = await getTenantFromCookies();
  const companyId = tenant.companyId;
  const people = await getPeople(companyId);
  const active = people.filter((p) => p.status === "active");
  const proposed = people.filter((p) => p.status === "proposed");

  // D2: thread the current Person id + tenancyRole into the drawer so
  // identity-merge / unlink / link operations carry real admin
  // attribution on the wire (no self-grant placeholders) and so admin-
  // only buttons gate-render when the viewer isn't admin/installer.
  const me = await getCurrentPerson(companyId);
  const currentPersonId = me?.personId ?? null;
  const currentRole = me?.tenancyRole ?? null;
  const isAdmin = currentRole === "admin" || currentRole === "installer";

  // Phase 2 Task 2C — proposal-count badge. Best-effort: a worm-core
  // outage shows zero pending proposals (honest empty state) rather
  // than throwing the whole /people page.
  let positionProposalCount = 0;
  try {
    const result = await listPositionProposals(tenant.slug);
    positionProposalCount = result.proposals.length;
  } catch {
    positionProposalCount = 0;
  }

  return (
    <PageBoundary surface="people" traceQuery="?surface=people">
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
            Pl. IV · Governance lens
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
            People
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {active.length} active · {proposed.length} pending. Each row carries
            a Receipt — provenance is the surface, not a footnote.
          </p>
        </div>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <Link
            href="/people/proposals"
            data-testid="position-proposal-badge"
            aria-label={
              positionProposalCount > 0
                ? `${positionProposalCount} pending position proposals`
                : "Position proposal queue (empty)"
            }
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink)",
              background:
                positionProposalCount > 0
                  ? "var(--wb-color-sepia-warning-soft)"
                  : "var(--wb-color-paper)",
              color:
                positionProposalCount > 0
                  ? "var(--wb-color-sepia-warning-deep)"
                  : "var(--wb-color-aged-ink)",
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              textDecoration: "none",
            }}
          >
            <span>Position proposals</span>
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                padding: "1px 6px",
                border: "1px solid currentColor",
                background:
                  positionProposalCount > 0
                    ? "var(--wb-color-sepia-warning)"
                    : "transparent",
                color:
                  positionProposalCount > 0
                    ? "var(--wb-color-paper)"
                    : "var(--wb-color-hash-gray)",
                minWidth: 20,
                textAlign: "center",
              }}
            >
              {positionProposalCount}
            </span>
          </Link>
          <InviteByEmailModal />
          <InviteModal />
        </div>
      </header>

      {proposed.length > 0 ? (
        <BulkConfirmDrawer proposals={proposed} />
      ) : null}

      <PeopleRoster
        persons={active}
        adminPersonId={currentPersonId}
        isAdmin={isAdmin}
      />

      <IdentityMergePanel
        persons={active}
        adminPersonId={currentPersonId}
        isAdmin={isAdmin}
      />
    </PageBoundary>
  );
}
