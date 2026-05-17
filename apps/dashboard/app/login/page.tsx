/**
 * GET /login — sign-in tenant picker (W1.A3).
 *
 * Renders one card per existing Install across every known tenant. Each
 * card shows the tenant display name, the installer email + display name,
 * the platform the install lives on, and a relative timestamp for the
 * most recent ledger activity in that tenant. Clicking a card invokes the
 * `selectTenant` server action which sets the `wormbase-tenant-slug`
 * cookie and redirects to `/`.
 *
 * Empty state: when no tenant carries any installs, render a panel that
 * directs the user at `/onboarding` to start fresh. No fixture fallback.
 *
 * This page is reached from `Tier0`'s "already installed? sign in" link
 * (which previously 404ed). The dashboard layout redirects to
 * `/onboarding` whenever the cookie does not resolve to a real install,
 * so this picker is the only honest path back into a previously-installed
 * workspace.
 */
import Link from "next/link";

import { Page } from "@wormbase/design";
import { getAllInstalls } from "../../lib/ledger-client";
import type { InstallSummary } from "../../lib/ledger-client.types";
import { MagicLinkForm } from "../../components/login/MagicLinkForm";
import { selectTenant } from "./actions";

export const metadata = {
  title: "WormBase · Sign in",
};

export const dynamic = "force-dynamic";

function relativeFromNow(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return iso;
  const deltaMs = Date.now() - ts;
  if (deltaMs < 0) return "just now";
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365);
  return `${years}y ago`;
}

interface TenantBucket {
  slug: string;
  displayName: string;
  installs: InstallSummary[];
  lastActivityAt: string;
}

function bucketByTenant(installs: InstallSummary[]): TenantBucket[] {
  const byTenant = new Map<string, TenantBucket>();
  for (const install of installs) {
    const existing = byTenant.get(install.tenantSlug);
    if (existing) {
      existing.installs.push(install);
      if (install.lastActivityAt > existing.lastActivityAt) {
        existing.lastActivityAt = install.lastActivityAt;
      }
    } else {
      byTenant.set(install.tenantSlug, {
        slug: install.tenantSlug,
        displayName: install.tenantDisplayName,
        installs: [install],
        lastActivityAt: install.lastActivityAt,
      });
    }
  }
  return Array.from(byTenant.values()).sort((a, b) =>
    b.lastActivityAt.localeCompare(a.lastActivityAt),
  );
}

export default async function LoginPage() {
  const installs = await getAllInstalls();
  const tenants = bucketByTenant(installs);

  return (
    <Page subtitle="sign in · pick a tenant">
      <section
        data-testid="login-fresh-signup"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          padding: 20,
          marginBottom: 24,
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper)",
        }}
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
            sign in · fresh signup
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 20,
              fontWeight: 500,
            }}
          >
            New here? Connect a Slack workspace or send a magic link.
          </h2>
        </header>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link
            href="/api/auth/slack/start"
            data-testid="login-slack-start"
            rel="external"
            className="wb-mono"
            style={{
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "10px 16px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-botanical-green-soft)",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
            }}
          >
            connect to Slack
          </Link>
        </div>
        <MagicLinkForm
          testidPrefix="login-magic-link"
          helpText="magic-link evaluators land on a seeded demo tenant (read-only)."
        />
      </section>

      <section
        data-testid="login-tenant-picker"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          border: "1px solid var(--wb-color-paper-edge)",
          padding: 20,
          background: "var(--wb-color-paper)",
        }}
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
            sign in · existing installs
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 24,
              fontWeight: 500,
            }}
          >
            Pick a workspace to continue
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            One card per Install row in the ledger. Selecting a workspace sets
            the tenant cookie and lands you in the dashboard for that tenant.
          </p>
        </header>

        {tenants.length === 0 ? (
          <div
            data-testid="login-empty"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              padding: "24px 20px",
              border: "1px dashed var(--wb-color-rule-line)",
              background: "var(--wb-color-paper-deep)",
            }}
          >
            <p
              className="wb-mono"
              style={{
                margin: 0,
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              no installs found
            </p>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 14,
                color: "var(--wb-color-aged-ink)",
                lineHeight: 1.55,
              }}
            >
              No tenant in this WormBase deployment has a completed install
              yet. Start a fresh workspace from the onboarding flow.
            </p>
            <Link
              href="/onboarding"
              data-testid="login-empty-cta"
              className="wb-mono"
              style={{
                fontSize: 12,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "10px 16px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-botanical-green-soft)",
                color: "var(--wb-color-aged-ink)",
                textDecoration: "none",
                alignSelf: "flex-start",
              }}
            >
              start fresh at /onboarding
            </Link>
          </div>
        ) : (
          <ul
            data-testid="login-tenant-list"
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            {tenants.map((tenant) => (
              <li key={tenant.slug}>
                <form
                  action={selectTenant}
                  data-testid={`login-tenant-form-${tenant.slug}`}
                >
                  <input type="hidden" name="slug" value={tenant.slug} />
                  <button
                    type="submit"
                    data-testid={`login-tenant-${tenant.slug}`}
                    data-tenant-slug={tenant.slug}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      cursor: "pointer",
                      padding: "16px 20px",
                      border: "1px solid var(--wb-color-aged-ink)",
                      background: "var(--wb-color-paper)",
                      color: "var(--wb-color-aged-ink)",
                      borderRadius: 0,
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      font: "inherit",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                        gap: 12,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "var(--wb-font-serif)",
                          fontSize: 18,
                          fontWeight: 500,
                        }}
                      >
                        {tenant.displayName}
                      </span>
                      <span
                        className="wb-mono"
                        data-testid={`login-tenant-${tenant.slug}-last-activity`}
                        style={{
                          fontSize: 10,
                          letterSpacing: "0.08em",
                          color: "var(--wb-color-hash-gray)",
                        }}
                      >
                        last active {relativeFromNow(tenant.lastActivityAt)}
                      </span>
                    </div>
                    <ul
                      style={{
                        listStyle: "none",
                        margin: 0,
                        padding: 0,
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                      }}
                    >
                      {tenant.installs.map((install) => (
                        <li
                          key={install.installId}
                          data-testid={`login-install-${install.installId}`}
                          className="wb-mono"
                          style={{
                            fontSize: 11,
                            letterSpacing: "0.04em",
                            color: "var(--wb-color-hash-gray)",
                          }}
                        >
                          <span data-testid={`login-install-${install.installId}-platform`}>
                            {install.platform}
                          </span>
                          {" · "}
                          <span data-testid={`login-install-${install.installId}-installer`}>
                            {install.installerEmail ??
                              install.installerName ??
                              "installer not yet folded"}
                          </span>
                          {install.status === "revoked" ? (
                            <span
                              style={{
                                marginLeft: 8,
                                color: "var(--wb-color-sepia-warning-deep)",
                              }}
                            >
                              · revoked
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </button>
                </form>
              </li>
            ))}
          </ul>
        )}

        <Link
          href="/onboarding"
          data-testid="login-back-to-onboarding"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.04em",
            color: "var(--wb-color-hash-gray)",
            textDecoration: "underline",
            textUnderlineOffset: 3,
            alignSelf: "flex-start",
          }}
        >
          start a fresh install instead
        </Link>
      </section>
    </Page>
  );
}
