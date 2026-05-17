import { getSources, getPeople } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../lib/server/identity";
import {
  getDomainAccessSet,
  memberHasNoAccess,
} from "../../../lib/server/role-filter";
import { MemberAccessBanner } from "../../../components/chrome/MemberAccessBanner";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";
import { AddSourceButton } from "../../../components/sources/AddSourceButton";
import { SourceListInteractive } from "../../../components/sources/SourceListInteractive";

export const metadata = { title: "WormBase · Sources" };

export default async function SourcesPage() {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const access = await getDomainAccessSet(companyId, me);
  const noAccess = memberHasNoAccess(me, access);
  const rawRows = await getSources(companyId);
  // Block I4: surface the default local lake at the top of the list so
  // the operator sees "yours from minute zero" before the user-driven
  // sources. Sort is stable for the rest of the rows.
  const rows = [...rawRows].sort((a, b) => {
    const aDefault =
      a.kind === "local_lake" && a.addedViaFlow === "provisioned_at_install";
    const bDefault =
      b.kind === "local_lake" && b.addedViaFlow === "provisioned_at_install";
    if (aDefault && !bDefault) return -1;
    if (!aDefault && bDefault) return 1;
    return 0;
  });
  const flows = new Set(rows.map((r) => r.addedViaFlow));

  // W2.A5 — provide a thin people list to the drawer's maintainer
  // picker. Best-effort: if the projection is empty the drawer hides
  // the maintainer section and only renders classification + receipt.
  let people: { personId: string; displayName: string }[] = [];
  try {
    const fullPeople = await getPeople(companyId);
    people = fullPeople.map((p) => ({
      personId: p.personId,
      displayName: p.displayName,
    }));
  } catch {
    people = [];
  }
  const currentPersonId = me?.personId ?? null;

  return (
    <PageBoundary surface="sources" traceQuery="?surface=sources" skeletonProps={{ eyebrow: "loading sources", title: "Reading the source ledger…" }}>
      <MemberAccessBanner show={noAccess} surface="sources" />
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: "1 1 auto" }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Pl. VI · Sources
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
            Sources · {rows.length}
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {flows.size} of 5 worm-driven source-building flows represented.
            Each row exposes how it joined the field notebook.
          </p>
        </div>
        <AddSourceButton />
      </header>

      {rows.length === 0 ? (
        <EmptyState
          testId="sources-empty"
          eyebrow="no sources yet"
          title="No data sources yet."
          description={
            "The default lake provisions on install — connect a chat platform " +
            "via /onboarding to get started. Once the worm is in your workspace " +
            "it'll lurk for ingest, accept dropped files, and propose external " +
            "sources from chatter. You can also add an external source manually."
          }
          cta={{ label: "Add an external source", href: "/sources/new" }}
          secondaryCta={{ label: "Connect a chat platform", href: "/onboarding" }}
        />
      ) : (
        <SourceListInteractive
          rows={rows}
          people={people}
          currentPersonId={currentPersonId}
        />
      )}

      <aside
        style={{
          borderTop: "1px solid var(--wb-color-paper-edge)",
          paddingTop: 16,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Provenance legend — left-border treatment marks the flow:{" "}
        <span className="wb-mono" style={{ fontStyle: "normal" }}>
          drop_and_profile
        </span>{" "}
        (green){" "}
        <span className="wb-mono" style={{ fontStyle: "normal" }}>
          credential_offered_in_dm
        </span>{" "}
        (ink){" "}
        <span className="wb-mono" style={{ fontStyle: "normal" }}>
          mentioned_in_conversation
        </span>{" "}
        (gray){" "}
        <span className="wb-mono" style={{ fontStyle: "normal" }}>
          dashboard_form
        </span>{" "}
        (sepia){" "}
        <span className="wb-mono" style={{ fontStyle: "normal" }}>
          kpi_gap_triggered
        </span>{" "}
        (green dashed)
      </aside>
    </PageBoundary>
  );
}
