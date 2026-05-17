/**
 * /people/[id] — per-Person detail page (W5.A5).
 *
 * Adds a dedicated route for a single Person so deep-links work and the
 * Resource Conversations section has a stable home. The legacy
 * PersonDetailDrawer remains the in-page UX on /people; this page is
 * the canonical link target (e.g. from /trace, from chat surfaces, from
 * shared URLs).
 *
 * Sections:
 *   - Header: name, email, position, status + tenancy chip
 *   - Resource Conversations (W5.A5) — when the Person owns any
 *     resources, the active DM threads with pinned topics + statements
 *     show up here.
 *   - Audit (compact) — last 20 ledger entries scoped to this Person.
 *
 * Wrapped in <PageBoundary>. Honest empty state if the Person doesn't
 * exist (or the worm-core read returns null).
 */
import Link from "next/link";
import { getPersonById } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { ResourceConversationsCard } from "../../../../components/people/ResourceConversationsCard";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Person" };
export const dynamic = "force-dynamic";

export default async function PersonDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companyId = await getCurrentCompanyId();
  const person = await getPersonById(companyId, id);

  if (!person) {
    return (
      <PageBoundary surface="people" traceQuery={`?surface=people&person_id=${id}`}>
        <EmptyState
          testId="person-detail-empty"
          eyebrow="person not found"
          title={`No Person with id ${id.slice(0, 12)}… on this tenant.`}
          description={
            "The Person may have been archived or split. Check the " +
            "/people roster for the canonical record, or look at /trace " +
            "filtered to this person id for the audit history."
          }
          cta={{ label: "Back to People", href: "/people" }}
          secondaryCta={{
            label: "Audit log",
            href: `/trace?person_id=${encodeURIComponent(id)}`,
          }}
        />
      </PageBoundary>
    );
  }

  const ownsResources =
    (person.resourceGrantCount ?? 0) > 0 ||
    (person.ownedDomains?.length ?? 0) > 0 ||
    (person.ownedResources?.length ?? 0) > 0;

  return (
    <PageBoundary surface="people" traceQuery={`?surface=people&person_id=${id}`}>
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
          Person · {id.slice(0, 8)}
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
          {person.displayName}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {person.email ?? "no email on file"}
          {person.position ? ` · ${person.position}` : ""}
          {person.tenancyRole ? ` · ${person.tenancyRole}` : ""}
        </p>
        <div style={{ marginTop: 6 }}>
          <Link
            href="/people"
            data-testid="person-detail-back"
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
              letterSpacing: "0.04em",
            }}
          >
            ← back to roster
          </Link>
        </div>
      </header>

      {ownsResources ? (
        <ResourceConversationsCard personId={id} />
      ) : (
        <section
          data-testid="resource-conversations-not-owner"
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Resource Conversations
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
              fontSize: 13,
            }}
          >
            This Person isn't an owner of any resources yet, so no
            statement-to-owner conversations will fire for them. Grant a
            resource role on /people to start receiving them.
          </p>
        </section>
      )}
    </PageBoundary>
  );
}
