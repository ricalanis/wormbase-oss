/**
 * /onboarding/connect/stripe/not-configured — Sub-wave D honest-disabled UI.
 *
 * When the operator hasn't set ``STRIPE_OAUTH_CLIENT_ID`` and
 * ``STRIPE_OAUTH_CLIENT_SECRET``, the OAuth callback redirects here.
 * The page surfaces the missing env vars + the operator-runbook
 * pointer so the gap is named, not papered-over with a synthetic
 * fallback.
 */
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata = { title: "WormBase · Stripe OAuth not configured" };

export default async function StripeNotConfiguredPage({
  searchParams,
}: {
  searchParams: Promise<{ missing?: string }>;
}): Promise<JSX.Element> {
  const sp = await searchParams;
  const missing = (sp.missing ?? "").split(",").filter(Boolean);

  return (
    <main
      data-testid="stripe-not-configured"
      style={{
        maxWidth: 640,
        margin: "48px auto",
        padding: 24,
        fontFamily: "var(--wb-font-serif)",
        color: "var(--wb-color-aged-ink, #2a2620)",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray, #7c7569)",
        }}
      >
        Stripe OAuth · honest disabled
      </span>
      <h1
        style={{
          margin: "8px 0",
          fontSize: 28,
          fontWeight: 500,
          letterSpacing: "-0.01em",
        }}
      >
        Stripe OAuth is not configured for this deployment.
      </h1>
      <p style={{ marginTop: 0, fontStyle: "italic" }}>
        The operator needs to set the following environment variables on the
        dashboard process before Stripe connect-account OAuth can be
        completed. Until then the Stripe connect path is intentionally
        disabled — we don't fall back to a credential-paste form because
        Stripe Connect requires the OAuth handshake to scope the connected
        account properly.
      </p>

      <section
        style={{
          marginTop: 20,
          border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          padding: 14,
          background: "var(--wb-color-paper, #f8f3e1)",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          Missing env vars
        </h2>
        <ul
          data-testid="stripe-not-configured-missing"
          style={{ marginTop: 8, paddingLeft: 18 }}
        >
          {(missing.length > 0
            ? missing
            : ["STRIPE_OAUTH_CLIENT_ID", "STRIPE_OAUTH_CLIENT_SECRET"]
          ).map((v) => (
            <li key={v} className="wb-mono" style={{ fontSize: 12 }}>
              {v}
            </li>
          ))}
        </ul>
      </section>

      <section style={{ marginTop: 24 }}>
        <p style={{ marginBottom: 8 }}>
          Get the values from Stripe Dashboard → Settings → Connect settings
          → "Live mode" or "Test mode" client id / secret. After setting the
          env vars + redeploying the dashboard, retry the connect flow from
          the source page.
        </p>
        <Link
          href="/lake/connectors"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink, #2a2620)",
            background: "var(--wb-color-aged-ink, #2a2620)",
            color: "var(--wb-color-paper, #f8f3e1)",
            textDecoration: "none",
          }}
        >
          ← back to connectors
        </Link>
      </section>
    </main>
  );
}
