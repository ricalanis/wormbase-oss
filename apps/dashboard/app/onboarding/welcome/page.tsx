/**
 * GET /onboarding/welcome — post-OAuth landing surface (W1.A3).
 *
 * Reached automatically after `/onboarding/oauth/<platform>/callback`
 * completes. Renders three sections:
 *
 *   1. Hero: "you're in" + tenant + installer + bot scopes.
 *   2. Live install-cascade panel — SSE feed of the 5 PEVR install
 *      cycles + 4 lake-provision cycles + ramp/concept/autoresearch
 *      milestones. See `InstallCascadePanel`.
 *   3. CTA stack: primary "Explore /sources" + secondary "Open
 *      /onboarding/tier2" (domain-pack picker).
 *
 * Reads the just-completed install via `getCurrentInstall(companyId)`.
 * If no install is folded yet (e.g. the projection runner hasn't
 * caught up) we surface an honest "still wiring" panel and a manual
 * /onboarding link rather than a fictitious receipt — there is no
 * fixture fallback at this surface.
 */
import Link from "next/link";

import { Page } from "@wormbase/design";
import { InstallCascadePanel } from "../../../components/onboarding/InstallCascadePanel";
import { getCurrentInstall } from "../../../lib/ledger-client";
import type { InstallRow } from "../../../lib/ledger-client.types";
import { getCurrentCompanyId, getTenantFromCookies } from "../../../lib/tenant-cookies";

export const metadata = {
  title: "WormBase · You're in",
};

export const dynamic = "force-dynamic";

function formatScopes(scopes: string[]): string {
  if (scopes.length === 0) return "no scopes recorded";
  return scopes.join(", ");
}

function HeroSection({
  install,
  tenantDisplayName,
}: {
  install: InstallRow | null;
  tenantDisplayName: string;
}) {
  return (
    <section
      data-testid="welcome-hero"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 24,
        background: "var(--wb-color-paper)",
      }}
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
        onboarding · welcome
      </span>
      <h1
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 32,
          fontWeight: 500,
          lineHeight: 1.1,
        }}
      >
        You&apos;re in.
      </h1>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 16,
          color: "var(--wb-color-aged-ink)",
          lineHeight: 1.55,
        }}
      >
        The worm has joined <strong>{tenantDisplayName}</strong>. Below is
        the live cascade of ledger entries that wire up your tenant —
        every checkmark is a real PEVR cycle landing in the chain.
      </p>
      {install ? (
        <dl
          data-testid="welcome-install-summary"
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "4px 16px",
            margin: 0,
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
          }}
        >
          <dt style={{ color: "var(--wb-color-hash-gray)" }}>install_id</dt>
          <dd
            data-testid="welcome-install-id"
            style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
          >
            {install.installId}
          </dd>
          <dt style={{ color: "var(--wb-color-hash-gray)" }}>platform</dt>
          <dd
            data-testid="welcome-install-platform"
            style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
          >
            {install.platform}
          </dd>
          <dt style={{ color: "var(--wb-color-hash-gray)" }}>installer</dt>
          <dd
            data-testid="welcome-install-installer"
            style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
          >
            {install.installerName ?? "(name not yet folded)"}
          </dd>
          <dt style={{ color: "var(--wb-color-hash-gray)" }}>scopes</dt>
          <dd
            data-testid="welcome-install-scopes"
            style={{ margin: 0, color: "var(--wb-color-aged-ink)" }}
          >
            {formatScopes(install.scopes)}
          </dd>
        </dl>
      ) : (
        <p
          data-testid="welcome-install-pending"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          Your install is propagating through the projections — the receipt
          will appear here in a moment. The cascade panel below is already
          subscribed to the live feed.
        </p>
      )}
    </section>
  );
}

function CtaStack() {
  return (
    <nav
      data-testid="welcome-cta-stack"
      aria-label="next steps"
      style={{ display: "flex", flexWrap: "wrap", gap: 12 }}
    >
      <Link
        href="/sources"
        data-testid="welcome-cta-sources"
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "12px 18px",
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-botanical-green-soft)",
          color: "var(--wb-color-aged-ink)",
          textDecoration: "none",
        }}
      >
        explore /sources
      </Link>
      <Link
        href="/onboarding/tier2"
        data-testid="welcome-cta-tier2"
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "12px 18px",
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-paper-deep)",
          color: "var(--wb-color-aged-ink)",
          textDecoration: "none",
        }}
      >
        open /onboarding/tier2
      </Link>
      <Link
        href="/trace"
        data-testid="welcome-cta-trace"
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "12px 18px",
          border: "1px solid var(--wb-color-rule-line)",
          background: "transparent",
          color: "var(--wb-color-hash-gray)",
          textDecoration: "none",
        }}
      >
        view /trace
      </Link>
    </nav>
  );
}

export default async function WelcomePage() {
  const [tenant, companyId] = await Promise.all([
    getTenantFromCookies(),
    getCurrentCompanyId(),
  ]);
  const install = await getCurrentInstall(companyId);
  // The cascade panel filters from the install_completed seq onward.
  // We don't have the seq directly without an extra query; passing
  // null is honest — the panel still subscribes and matches by
  // payload.tool. install_id, when known, scopes the SSE filter.
  return (
    <Page subtitle="onboarding · welcome · cascade live">
      <HeroSection
        install={install}
        tenantDisplayName={tenant.displayName}
      />
      <InstallCascadePanel
        installId={install?.installId ?? ""}
        sinceSeq={null}
      />
      <CtaStack />
    </Page>
  );
}
