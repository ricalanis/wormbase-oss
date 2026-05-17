/**
 * /onboard/source — data-source marketplace
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Reuses the /lake/surfaces connector-row data shape — same registry,
 * same capability badges, same Add affordance. The only difference is
 * the framing: ``/onboard/source`` is the operator-facing tab in the
 * unified onboarding surface; ``/lake/surfaces`` is the
 * lineage-axis marketplace.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import type { CapabilityStatus } from "../../../../components/onboard/CapabilityBadges";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { getOnboardSource } from "../../../../lib/onboard";
import type { ConnectorCatalogRow } from "../../../../lib/connectors";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard · Source" };

export const dynamic = "force-dynamic";

function rowStatus(r: ConnectorCatalogRow): CapabilityStatus {
  if (r.status === "production") return "production";
  if (r.status === "preview") return "preview";
  return "coming_soon";
}

export default async function OnboardSourcePage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const view = await getOnboardSource(companyId);
  const totalKinds =
    view.catalog.production.length +
    view.catalog.preview.length +
    view.catalog.comingSoon.length;
  const allRows: ConnectorCatalogRow[] = [
    ...view.catalog.production,
    ...view.catalog.preview,
    ...view.catalog.comingSoon,
  ];
  return (
    <PageBoundary
      surface="onboard source"
      traceQuery="?surface=onboard.source"
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
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
            @onboard source · data sources
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 30,
              fontWeight: 500,
            }}
          >
            Source · {totalKinds} kinds · {view.sources.length} active
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
            Connect the worm to every data store the company runs.
            Production connectors connect today; preview connectors will
            graduate as the underlying methods are wired. The Add button
            routes to the existing /sources/new connector-picker.
          </p>
        </div>
        <Link
          href="/sources/new"
          data-testid="onboard-source-add-cta"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-aged-ink)",
            color: "var(--wb-color-paper)",
            textDecoration: "none",
          }}
        >
          Add source…
        </Link>
      </header>

      {view.catalog.registryUnreachable ? (
        <div
          data-testid="onboard-source-registry-unreachable"
          role="alert"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-paper-deep)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            connector registry unreachable
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Showing the static catalog fallback so the marketplace still
            renders. {view.catalog.registryError ?? ""}
          </span>
        </div>
      ) : null}

      {totalKinds === 0 ? (
        <EmptyState
          testId="onboard-source-empty"
          eyebrow="no connectors registered"
          title="The connector registry returned no kinds."
          description="Verify worm-core is reachable and the Python registry packages/lake-surfaces/ is importable."
          cta={{ label: "See /activity", href: "/activity" }}
        />
      ) : (
        <ul
          data-testid="onboard-source-rows"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            border: "1px solid var(--wb-color-paper-edge)",
            borderTop: "none",
          }}
        >
          {allRows.map((row) => (
            <li
              key={row.kind}
              data-testid={`onboard-source-row-${row.kind}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(160px, 200px) 1fr minmax(140px, 180px)",
                gap: 12,
                alignItems: "baseline",
                padding: "12px 14px",
                borderTop: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
                opacity: row.status === "coming_soon" ? 0.7 : 1,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <strong
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 15,
                  }}
                >
                  {row.label}
                </strong>
                <code
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {row.kind}
                </code>
              </div>
              <CapabilityBadges
                kind="connector"
                id={row.kind}
                status={rowStatus(row)}
                capabilities={row.capabilities}
                statusNote={row.description}
              />
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                {row.status === "coming_soon" ? (
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    Notify me (v1.5)
                  </span>
                ) : (
                  <Link
                    href={`/sources/new/${encodeURIComponent(row.kind)}`}
                    data-testid={`onboard-source-add-${row.kind}`}
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                      padding: "6px 12px",
                      border: "1px solid var(--wb-color-aged-ink)",
                      background:
                        row.connectionState === "connected"
                          ? "var(--wb-color-paper)"
                          : "var(--wb-color-aged-ink)",
                      color:
                        row.connectionState === "connected"
                          ? "var(--wb-color-aged-ink)"
                          : "var(--wb-color-paper)",
                      textDecoration: "none",
                    }}
                  >
                    {row.connectionState === "connected"
                      ? `Connected · ${row.activeSourceCount}`
                      : "Add"}
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </PageBoundary>
  );
}
