/**
 * /onboard/subscription — navigation stub
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Subscriptions are managed per-agent — the canonical surface is
 * /people/agents/[id]/subscriptions/new. This tab exists so the
 * unified onboarding ontology covers every object kind; the panel
 * deep-links to the canonical place.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Onboard · Subscription" };

export const dynamic = "force-dynamic";

export default function OnboardSubscriptionPage(): JSX.Element {
  return (
    <PageBoundary
      surface="onboard subscription"
      traceQuery="?surface=onboard.subscription"
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
          @onboard subscription · navigation
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
          }}
        >
          Subscription
        </h1>
      </header>

      <section
        data-testid="onboard-subscription-navigation-panel"
        style={{
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper)",
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            color: "var(--wb-color-aged-ink)",
            maxWidth: 640,
          }}
        >
          Subscriptions are per-agent and live on each agent's detail
          page. Visit /people/agents, pick an agent, and follow the
          subscription form. No duplicate UI here.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link
            href="/people/agents"
            data-testid="onboard-subscription-agents-link"
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
            Pick an agent…
          </Link>
        </div>
      </section>
    </PageBoundary>
  );
}
