/**
 * /sources/new/stripe — Sub-wave D Stripe Add Source page.
 *
 * Stripe-specific landing in the source-builder flow. Honest-disabled
 * when the OAuth env vars are missing; otherwise renders the
 * "Continue to Stripe" button that targets the ``/start`` route which
 * sets the CSRF cookie + redirects to Stripe's authorize URL.
 *
 * Renders a "connected" banner when the callback redirects back with
 * ``?connected=1&account=...``.
 */
import Link from "next/link";

import { readStripeOAuthConfig } from "../../../../../lib/oauth/stripe";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";

export const dynamic = "force-dynamic";
export const metadata = { title: "WormBase · Add Stripe source" };

export default async function NewStripeSourcePage({
  searchParams,
}: {
  searchParams: Promise<{ connected?: string; account?: string }>;
}): Promise<JSX.Element> {
  const sp = await searchParams;
  const config = readStripeOAuthConfig();
  const connected = sp.connected === "1";
  const account = sp.account ?? "";

  return (
    <PageBoundary
      surface="sources new stripe"
      traceQuery="?surface=sources.new.stripe"
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          Sources · new · stripe (OAuth reference impl)
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Add Stripe source
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray, #7c7569)",
            maxWidth: 640,
          }}
        >
          Stripe is the reference impl for our OAuth connector path —
          Salesforce / HubSpot / GSheets follow the same shape in a
          future wave. Clicking "Continue to Stripe" sets a CSRF state
          cookie and redirects to Stripe Connect's authorize URL.
        </p>
      </header>

      {connected ? (
        <section
          data-testid="stripe-connected-banner"
          style={{
            marginTop: 16,
            border: "1px solid var(--wb-color-botanical-green-deep, #2d5d3a)",
            padding: 14,
            background: "var(--wb-color-paper, #f8f3e1)",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
            }}
          >
            connected
          </span>
          <p style={{ marginTop: 4 }}>
            Stripe account{" "}
            <code className="wb-mono" data-testid="stripe-connected-account">
              {account}
            </code>{" "}
            connected. The worm's source builder will pick up the
            entry on its next cascade tick.
          </p>
        </section>
      ) : null}

      {!config.configured ? (
        <section
          data-testid="stripe-not-configured-banner"
          style={{
            marginTop: 16,
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
            padding: 14,
            background: "var(--wb-color-paper, #f8f3e1)",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            stripe oauth not configured
          </span>
          <p style={{ marginTop: 4 }}>
            Set <code>STRIPE_OAUTH_CLIENT_ID</code> and{" "}
            <code>STRIPE_OAUTH_CLIENT_SECRET</code> on the dashboard
            process, then retry. We don't fall back to credential-paste
            for Stripe.
          </p>
          <p style={{ marginTop: 8 }}>
            Missing:{" "}
            <code data-testid="stripe-not-configured-missing">
              {config.missing.join(", ")}
            </code>
          </p>
        </section>
      ) : (
        <section
          data-testid="stripe-connect-cta"
          style={{
            marginTop: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <Link
            href="/onboarding/connect/stripe/start"
            className="wb-mono"
            data-testid="stripe-start-link"
            style={{
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "10px 18px",
              border: "1px solid var(--wb-color-aged-ink, #2a2620)",
              background: "var(--wb-color-aged-ink, #2a2620)",
              color: "var(--wb-color-paper, #f8f3e1)",
              textDecoration: "none",
              alignSelf: "flex-start",
            }}
          >
            Continue to Stripe →
          </Link>
          <p
            style={{
              fontSize: 12,
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Scope: <code>read_only</code>. You'll be redirected to Stripe to
            authorize the WormBase Connect app. After approval Stripe
            redirects back; we exchange the code, store the access token
            via the CredentialBroker (Vault when{" "}
            <code>VAULT_ADDR</code> is set; env-resident otherwise), and
            emit a <code>source_connected</code> ledger entry.
          </p>
        </section>
      )}
    </PageBoundary>
  );
}
