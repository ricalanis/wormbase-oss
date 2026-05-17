/**
 * /onboard/person — co-admin invites + Person discovery
 *
 * Onboarding Sub-wave C (2026-05-30) graduated the read-only list
 * into a list + invite form. The form submits via the
 * ``invitePersonAction`` server action, which emits a
 * ``person_invited`` PEVR cycle through worm-core. The actual
 * ``person_proposed`` → ``person_confirmed`` lifecycle fires when the
 * invitee accepts the signed acceptance URL; this surface only
 * records the invite intent.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import type { CapabilityStatus } from "../../../../components/onboard/CapabilityBadges";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { InvitePersonForm } from "../../../../components/onboard/InvitePersonForm";
import { getOnboardPerson } from "../../../../lib/onboard";
import type { PersonRow } from "../../../../lib/ledger-client.types";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard · Person" };

export const dynamic = "force-dynamic";

function personStatus(row: PersonRow): CapabilityStatus {
  if (row.status === "active") return "works";
  if (row.status === "proposed") return "preview";
  return "failed";
}

export default async function OnboardPersonPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const view = await getOnboardPerson(companyId);
  return (
    <PageBoundary
      surface="onboard person"
      traceQuery="?surface=onboard.person"
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
            @onboard person · co-admin invites
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 30,
              fontWeight: 500,
            }}
          >
            Person · {view.confirmedCount} confirmed ·{" "}
            {view.proposedCount} pending
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
            Confirmed Persons accrue role grants. Proposed Persons came
            in via PersonIdentity auto-discovery and await admin
            confirmation. Invite a co-admin via /people; the existing
            invite form writes per-platform identities.
          </p>
        </div>
        <Link
          href="/people"
          data-testid="onboard-person-people-link"
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
          Open /people
        </Link>
      </header>

      <section data-testid="onboard-person-invite">
        <InvitePersonForm />
      </section>

      {view.people.length === 0 ? (
        <EmptyState
          testId="onboard-person-empty"
          eyebrow="no persons"
          title="No Persons folded yet."
          description="Discovery proposes new Persons from wire traffic. Connect a chat platform first via /onboard/chat to start the auto-discovery loop."
          cta={{ label: "Connect chat", href: "/onboard/chat" }}
        />
      ) : (
        <ul
          data-testid="onboard-person-rows"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            border: "1px solid var(--wb-color-paper-edge)",
            borderTop: "none",
          }}
        >
          {view.people.map((p) => (
            <li
              key={p.personId}
              data-testid={`onboard-person-row-${p.personId}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(180px, 240px) 1fr minmax(120px, 160px)",
                gap: 12,
                alignItems: "baseline",
                padding: "10px 14px",
                borderTop: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
                opacity: p.status === "archived" ? 0.6 : 1,
              }}
            >
              <div
                style={{ display: "flex", flexDirection: "column", gap: 2 }}
              >
                <strong
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 14,
                  }}
                >
                  {p.displayName}
                </strong>
                <code
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {p.tenancyRole ?? "(no role)"}
                </code>
              </div>
              <CapabilityBadges
                kind="person"
                id={p.personId}
                status={personStatus(p)}
                statusNote={
                  p.identities.length > 0
                    ? `${p.identities.length} identit${p.identities.length === 1 ? "y" : "ies"} · ${p.identities
                        .map((i) => i.platform)
                        .join(" · ")}`
                    : "No platform identities linked yet."
                }
              />
              <Link
                href={`/status/person/${encodeURIComponent(p.personId)}`}
                data-testid={`onboard-person-status-${p.personId}`}
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
    </PageBoundary>
  );
}
