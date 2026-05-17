/**
 * /reactivities — admin tab for the reactivity registry (W5.A5).
 *
 * Server component; reads the registry via ``getReactivities`` and
 * renders three sections:
 *
 *   1. Active reactivities — registered + state == "active". Sorted
 *      by lastFired desc so the busiest fires sit at the top.
 *   2. Pending proposals — state == "proposed". Each card carries a
 *      Confirm CTA that promotes the reactivity to active.
 *   3. Disabled reactivities — state == "disabled". Hidden by default
 *      behind a "Show disabled" toggle (admin still needs to audit
 *      them but they shouldn't crowd the active surface).
 *
 * Plus a primary CTA at the top: "Propose new reactivity" → opens
 * ProposeReactivityModal. Natural-language description → worm-core's
 * deterministic NL parser → admin previews + confirms.
 *
 * Wrapped in <PageBoundary>. Honest empty state when the registry has
 * zero registered reactivities.
 */
import { getReactivities } from "../../../lib/ledger-client";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";
import { PageBoundary } from "../../../components/chrome/PageBoundary";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { ReactivitiesView } from "../../../components/reactivities/ReactivitiesView";

export const metadata = { title: "WormBase · Reactivities" };
export const dynamic = "force-dynamic";

export default async function ReactivitiesPage() {
  const tenant = await getTenantFromCookies();
  const reactivities = await getReactivities(tenant.companyId, tenant.slug);

  return (
    <PageBoundary surface="reactivities" traceQuery="?surface=reactivities">
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
          Pl. X · Reactivity registry · admin
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
          Reactivities
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
          The worm builds the rules it runs on. Each reactivity is a
          predicate · condition · fire triple with a propose / confirm /
          disable lifecycle and per-day budget gating. Propose new ones
          from chat-shaped statements; admins confirm before they fire.
        </p>
      </header>

      {reactivities.length === 0 ? (
        <EmptyState
          testId="reactivities-empty"
          eyebrow="no reactivities registered"
          title="The reactivity registry is empty for this tenant."
          description={
            "The worm-core registers its built-in reactivities at boot — " +
            "identity discovery, statement-to-owner, phenomenon-gap " +
            "detection. Once worm-core has booted (and the registry " +
            "endpoint is reachable) the rows show up here. You can also " +
            "propose new reactivities from natural-language descriptions."
          }
          cta={{ label: "See ops health", href: "/ops" }}
          secondaryCta={{ label: "View trace", href: "/trace" }}
        />
      ) : (
        <ReactivitiesView initialReactivities={reactivities} />
      )}
    </PageBoundary>
  );
}
