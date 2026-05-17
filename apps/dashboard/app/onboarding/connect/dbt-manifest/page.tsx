/**
 * /onboarding/connect/dbt-manifest — Wave 3.2 Hole #2 "Import existing
 * catalog" branch (dbt project sub-path).
 *
 * Admin-only form for importing a dbt manifest as a CatalogMirror source.
 * Submission routes through the `importDbtManifest` server action, which
 * forwards to worm-core's HTTP write API. The dashboard NEVER direct-writes
 * the ledger — every import lands as a `source_proposed → source_connected`
 * PEVR cycle from the catalog-mirror layer.
 *
 * Defense in depth: the page short-circuits to a "admin required" panel
 * for non-admins; the server action re-checks the role before forwarding
 * to worm-core. A non-admin can neither see the form nor bypass the page
 * by posting directly to the action.
 */
import Link from "next/link";

import { DbtManifestImportForm } from "../../../../components/onboarding/DbtManifestImportForm";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import {
  getDomains,
  getRolesForPerson,
} from "../../../../lib/ledger-client";
import { importDbtManifest } from "./actions";

export const metadata = { title: "WormBase · Import dbt manifest" };

export const dynamic = "force-dynamic";

export default async function ImportDbtManifestPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);
  const isAdmin = await resolveIsAdmin(companyId, person);

  return (
    <PageBoundary
      surface="onboarding import dbt-manifest"
      traceQuery="?surface=onboarding.connect.dbt-manifest"
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
          Onboarding · Tier 3 · Import existing catalog · dbt
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Import a dbt manifest
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
          Mirror an existing dbt project into the WormBase catalog. The
          CatalogMirror layer resolves the manifest, materializes each model
          as a source row, and tags discovered tables under the bound domain.
          Subsequent drift is detected by the catalog-mirror Reactivities.
        </p>
      </header>

      {!isAdmin ? (
        <EmptyState
          testId="onboarding-dbt-manifest-not-admin"
          eyebrow="admin required"
          title="Admin role required to import a catalog."
          description={
            "Only Persons with an unrevoked tenancy.admin (or " +
            "tenancy.installer) grant can import a dbt manifest. Ask an " +
            "existing admin to add you, or proceed via the admin CLI."
          }
          cta={{ label: "Back to Tier 3", href: "/onboarding/tier3" }}
          secondaryCta={{ label: "See activity", href: "/activity" }}
        />
      ) : (
        <ImportContainer companyId={companyId} />
      )}
    </PageBoundary>
  );
}

async function ImportContainer({
  companyId,
}: {
  companyId: string;
}): Promise<JSX.Element> {
  const domains = await getDomains(companyId);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <DbtManifestImportForm
        domains={domains}
        importAction={importDbtManifest}
      />
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Prefer a Snowflake account?{" "}
        <Link
          href="/onboarding/connect/snowflake-catalog"
          style={{ color: "inherit" }}
        >
          Import a Snowflake catalog
        </Link>{" "}
        instead.
      </p>
    </div>
  );
}

async function resolveIsAdmin(
  companyId: string,
  person: Awaited<ReturnType<typeof getCurrentPerson>>,
): Promise<boolean> {
  if (!person) return false;
  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return true;
  }
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  return live.includes("admin") || live.includes("installer");
}
