/**
 * /onboard/agent — navigation stub
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Per the design spec §4.1, ``/onboard/agent`` is navigation-only. The
 * canonical agent-registration surface lives at /people/agents/new and
 * carries the form, validation, credential broker config, and grant
 * UI. We deliberately don't duplicate it here — the tab exists so the
 * unified onboarding ontology covers every object kind end-to-end.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Onboard · Agent" };

export const dynamic = "force-dynamic";

export default function OnboardAgentPage(): JSX.Element {
  return (
    <PageBoundary
      surface="onboard agent"
      traceQuery="?surface=onboard.agent"
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
          @onboard agent · navigation
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
          }}
        >
          Agent
        </h1>
      </header>

      <section
        data-testid="onboard-agent-navigation-panel"
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
          Agent registration lives at <code>/people/agents/new</code>. The
          form gathers an agent identity, a credential-broker config
          (vault or env), the initial grant set, and a description. No
          duplication on this surface — visit the canonical page below
          to register a new agent.
        </p>
        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <Link
            href="/people/agents/new"
            data-testid="onboard-agent-register-link"
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
            Register an agent…
          </Link>
          <Link
            href="/people/agents"
            data-testid="onboard-agent-list-link"
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
            See active agents
          </Link>
        </div>
      </section>
    </PageBoundary>
  );
}
