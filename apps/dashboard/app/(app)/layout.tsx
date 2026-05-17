import { redirect } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import { Sidebar } from "../../components/chrome/Sidebar";
import { TopRule } from "../../components/chrome/TopRule";
import { AskTheWormFloater } from "../../components/voice/AskTheWormFloater";
import { TenantProvider } from "../../lib/tenant-context";
import { getTenantFromCookies } from "../../lib/tenant-cookies";
import {
  getCurrentInstall,
  getCurrentPerson,
} from "../../lib/server/identity";

/**
 * App-shell layout: 240px sidebar (sticky), then a scrollable main column with
 * a TopRule across the top. Dense brutalist grid; thin botanical-green rule
 * separates nav from content.
 *
 * Redirect guard sequence (Block I5 of the production-dashboard PRD §17,
 * REVISED 2026-04-27 minimal-friction onboarding):
 *
 *   1. No install → /onboarding (T0 chat-platform connect)
 *   2. Install exists, setup_mode null, setup_completed null
 *      → render dashboard with a "Want a tour?" banner CTA (no redirect).
 *      The whats-next + setup-mode-fork pages are now reached from that
 *      banner rather than via a forced redirect — minimal friction.
 *   3. setup_mode == "wizard" AND setup_completed null → render dashboard
 *      with a "Continue setup" banner linking to /onboarding/tier2.
 *   4. setup_mode == "bot" AND setup_completed null → render dashboard
 *      with a "Setup in progress in your chat" banner.
 *   5. setup_completed non-null → render dashboard normally.
 *
 * The dashboard is not browsable in any other state. There is no
 * "anonymous observer" mode and no synthetic Person fallback. The matching
 * `getCurrentPerson` is guaranteed non-null because the install always
 * carries a Person grant.
 */
export default async function AppShellLayout({
  children,
}: {
  children: ReactNode;
}) {
  const tenant = await getTenantFromCookies();

  // Guard 1: no install → redirect to onboarding. Dashboard is install-only.
  const install = await getCurrentInstall(tenant.companyId);
  if (!install) {
    redirect("/onboarding");
  }

  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    // Defensive: an Install row exists but no installer/admin Person was
    // resolved. Treat as a broken install and re-onboard.
    redirect("/onboarding?error=missing_installer_person");
  }
  // Block I5: setup_mode null + setup_completed null is now the normal
  // post-install state for fresh tenants — no redirect. The dashboard
  // renders with a tour banner that links to /onboarding/whats-next +
  // /onboarding/setup-mode/choose. wizard-without-completion and
  // bot-without-completion render with their own banners (see
  // dashboard/page.tsx for the banner CTAs themselves).

  return (
    <TenantProvider initialSlug={tenant.slug}>
      <div
        data-testid="app-shell"
        style={{
          display: "flex",
          minHeight: "100vh",
          background: "var(--wb-color-paper)",
        }}
      >
        <Sidebar role={me.tenancyRole} />
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
          }}
        >
          <TopRule
            person={{
              person: { name: me.name, position: me.position },
              role: me.tenancyRole,
              personId: me.personId,
            }}
          />
          <main
            style={{
              flex: 1,
              padding: "32px 32px 48px",
              display: "flex",
              flexDirection: "column",
              gap: 32,
            }}
          >
            {children}
          </main>
        </div>
      </div>
      {/*
        W3.A12 — "Ask the worm" voice floater. Mounted on every (app)-
        prefixed route. Wrapped in a Suspense boundary so the bundle
        cost is decoupled from the initial server render. Failure to
        load the floater never blocks the dashboard chrome.
      */}
      <Suspense fallback={null}>
        <AskTheWormFloater />
      </Suspense>
    </TenantProvider>
  );
}
