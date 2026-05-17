/**
 * /onboard/policy — policy list (read-only)
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Reads from the existing governance policy projection. Sub-wave C
 * extends this with pack-seeded policies; for now we render whatever
 * the warmup pack + per-tenant policies look like today.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import type { CapabilityStatus } from "../../../../components/onboard/CapabilityBadges";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { getOnboardPolicy } from "../../../../lib/onboard";
import type { PolicyRow } from "../../../../lib/ledger-client.types";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard · Policy" };

export const dynamic = "force-dynamic";

function policyStatus(p: PolicyRow): CapabilityStatus {
  if (p.firesLast7d > 0) return "works";
  return "preview";
}

export default async function OnboardPolicyPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const view = await getOnboardPolicy(companyId);
  return (
    <PageBoundary
      surface="onboard policy"
      traceQuery="?surface=onboard.policy"
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
            @onboard policy · ledger-native governance
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 30,
              fontWeight: 500,
            }}
          >
            Policy · {view.policies.length} registered ·{" "}
            {view.firedRecently} fired (7d)
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
            Policies are rule-as-code attached to domains, classifications,
            or resources. Every fire writes a ledger entry. Sub-wave C
            extends this list with pack-seeded policies; today's view is
            read-only over the existing governance projection.
          </p>
        </div>
        <Link
          href="/policies"
          data-testid="onboard-policy-policies-link"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
          }}
        >
          Open /policies
        </Link>
      </header>

      {view.policies.length === 0 ? (
        <EmptyState
          testId="onboard-policy-empty"
          eyebrow="no policies"
          title="No policies registered yet."
          description="Pack-seeded policies land in Sub-wave C. Today, only policies that have been explicitly written via emit_policy_applied appear here."
          cta={{ label: "Pick a domain pack", href: "/onboard/domain" }}
        />
      ) : (
        <ul
          data-testid="onboard-policy-rows"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            border: "1px solid var(--wb-color-paper-edge)",
            borderTop: "none",
          }}
        >
          {view.policies.map((p) => (
            <li
              key={p.policyId}
              data-testid={`onboard-policy-row-${p.policyId}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(180px, 240px) 1fr minmax(120px, 160px)",
                gap: 12,
                alignItems: "baseline",
                padding: "10px 14px",
                borderTop: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
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
                  {p.name}
                </strong>
                <code
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  scope: {p.scope} · {p.firesLast7d} fires (7d)
                </code>
              </div>
              <CapabilityBadges
                kind="policy"
                id={p.policyId}
                status={policyStatus(p)}
                statusNote={p.plainLanguage}
              />
              <Link
                href={`/status/policy/${encodeURIComponent(p.policyId)}`}
                data-testid={`onboard-policy-status-${p.policyId}`}
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
