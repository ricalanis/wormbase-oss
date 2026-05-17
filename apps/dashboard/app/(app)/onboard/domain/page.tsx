/**
 * /onboard/domain — domain pack picker
 *
 * Onboarding Sub-wave C (2026-05-30) graduated the read-only empty
 * state into a working picker. The 4 YAML packs ship at
 * ``apps/worm-core/src/wormbase_core/onboarding/packs/`` and the
 * picker submits via ``POST /api/v1/write_actions/domain_pack_selected/{pack_id}``
 * through the ``selectDomainPackAction`` server action. The picker is
 * idempotent at the worm-core layer — a re-pick on a tenant that
 * already has a pack-selection surfaces honestly as "already seeded".
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import { DomainPackPicker } from "../../../../components/onboard/DomainPackPicker";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { getOnboardDomain } from "../../../../lib/onboard";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard · Domain" };

export const dynamic = "force-dynamic";

export default async function OnboardDomainPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const view = await getOnboardDomain(companyId);
  return (
    <PageBoundary
      surface="onboard domain"
      traceQuery="?surface=onboard.domain"
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
          @onboard domain · governance baseline
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
          }}
        >
          Domain · {view.domains.length} registered
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
          Pick a domain pack to seed your governance baseline in one
          click. Packs ship as declarative YAML; the picker writes a
          fan-out of domain_proposed, classification_proposed, and
          policy_proposed entries in a single PEVR cycle.
        </p>
      </header>

      <section
        data-testid="onboard-domain-packs"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
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
            domain packs
          </span>
        </header>
        {view.packsAvailable && view.packs.length > 0 ? (
          <DomainPackPicker packs={view.packs} />
        ) : (
          <EmptyState
            testId="onboard-domain-packs-empty"
            eyebrow="pack picker unavailable"
            title="No domain packs registered."
            description="The 4 packs (generic / saas / marketplace / fintech) ship as YAML in apps/worm-core/src/wormbase_core/onboarding/packs/. If this empty state renders, the worm-core bundle is missing the packs/ directory."
            cta={{ label: "See existing /domains", href: "/domains" }}
          />
        )}
      </section>

      <section
        data-testid="onboard-domain-existing"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
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
            registered domains · {view.domains.length}
          </span>
        </header>
        {view.domains.length === 0 ? (
          <EmptyState
            testId="onboard-domain-existing-empty"
            eyebrow="no domains"
            title="No domains registered yet."
            description="Pick a pack above (Sub-wave C) or register a domain directly via /domains."
            cta={{ label: "Open /domains", href: "/domains" }}
          />
        ) : (
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              border: "1px solid var(--wb-color-paper-edge)",
              borderTop: "none",
            }}
          >
            {view.domains.map((d) => (
              <li
                key={d.domainId}
                data-testid={`onboard-domain-row-${d.domainId}`}
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "minmax(160px, 220px) 1fr minmax(120px, 160px)",
                  gap: 12,
                  alignItems: "baseline",
                  padding: "10px 14px",
                  borderTop: "1px solid var(--wb-color-paper-edge)",
                  background: "var(--wb-color-paper)",
                }}
              >
                <strong
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 14,
                  }}
                >
                  {d.name}
                </strong>
                <CapabilityBadges
                  kind="domain"
                  id={d.domainId}
                  status={d.owner === "unassigned" ? "degraded" : "works"}
                  statusNote={
                    d.owner === "unassigned"
                      ? "No owner — assign one on /domains."
                      : `Owner ${d.owner.slice(0, 8)} · ${d.resourceCount} resource${d.resourceCount === 1 ? "" : "s"}`
                  }
                />
                <Link
                  href={`/status/domain/${encodeURIComponent(d.domainId)}`}
                  data-testid={`onboard-domain-status-${d.domainId}`}
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    padding: "5px 10px",
                    border: "1px solid var(--wb-color-aged-ink)",
                    background: "var(--wb-color-paper)",
                    color: "var(--wb-color-aged-ink)",
                    textDecoration: "none",
                  }}
                >
                  Status
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </PageBoundary>
  );
}
