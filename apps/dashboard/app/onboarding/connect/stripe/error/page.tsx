/**
 * /onboarding/connect/stripe/error — Sub-wave D Stripe OAuth error UI.
 *
 * Surfaces a recoverable Stripe OAuth failure with phase + error code +
 * a retry CTA. Phases:
 *
 *   * ``consent``         — user denied / cancelled on Stripe's screen
 *   * ``token_exchange``  — Stripe rejected the code (invalid_grant /
 *                           invalid_client / network)
 *   * ``token_storage``   — Vault / env write failed after successful
 *                           code exchange
 */
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata = { title: "WormBase · Stripe OAuth error" };

export default async function StripeErrorPage({
  searchParams,
}: {
  searchParams: Promise<{
    error?: string;
    phase?: string;
    detail?: string;
  }>;
}): Promise<JSX.Element> {
  const sp = await searchParams;
  const error = sp.error ?? "unknown";
  const phase = sp.phase ?? "unknown";
  const detail = sp.detail ?? "";

  return (
    <main
      data-testid="stripe-oauth-error"
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
          color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        }}
      >
        Stripe OAuth · error · phase = {phase}
      </span>
      <h1
        style={{
          margin: "8px 0",
          fontSize: 28,
          fontWeight: 500,
          letterSpacing: "-0.01em",
        }}
      >
        Stripe OAuth failed.
      </h1>

      <section
        style={{
          marginTop: 20,
          border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          padding: 14,
          background: "var(--wb-color-paper, #f8f3e1)",
        }}
      >
        <dl style={{ margin: 0 }}>
          <dt
            className="wb-mono"
            style={{ fontSize: 10, textTransform: "uppercase" }}
          >
            error
          </dt>
          <dd
            data-testid="stripe-oauth-error-code"
            className="wb-mono"
            style={{ fontSize: 12, marginBottom: 12 }}
          >
            {error}
          </dd>
          <dt
            className="wb-mono"
            style={{ fontSize: 10, textTransform: "uppercase" }}
          >
            phase
          </dt>
          <dd
            data-testid="stripe-oauth-error-phase"
            className="wb-mono"
            style={{ fontSize: 12, marginBottom: 12 }}
          >
            {phase}
          </dd>
          {detail ? (
            <>
              <dt
                className="wb-mono"
                style={{ fontSize: 10, textTransform: "uppercase" }}
              >
                detail
              </dt>
              <dd
                data-testid="stripe-oauth-error-detail"
                style={{ fontSize: 12 }}
              >
                {detail}
              </dd>
            </>
          ) : null}
        </dl>
      </section>

      <section style={{ marginTop: 24, display: "flex", gap: 12 }}>
        <Link
          href="/onboarding/connect/stripe/start"
          data-testid="stripe-oauth-error-retry"
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
          Retry
        </Link>
        <Link
          href="/lake/surfaces"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink, #2a2620)",
            background: "var(--wb-color-paper, #f8f3e1)",
            color: "var(--wb-color-aged-ink, #2a2620)",
            textDecoration: "none",
          }}
        >
          ← back to connectors
        </Link>
      </section>
    </main>
  );
}
