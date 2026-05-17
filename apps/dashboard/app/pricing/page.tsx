import Link from "next/link";

import { Pricing } from "../../components/landing/Pricing";

export const metadata = {
  title: "WormBase · Pricing",
  description:
    "WormBase pricing — Free for one team, $60/seat/mo for Pro with 100 artifacts and $1/artifact thereafter, custom Enterprise.",
};

/**
 * Standalone `/pricing` route — Phase 4D.
 *
 * Deep-linkable pricing page for sales decks, blog posts, and email
 * signatures. Renders the same `Pricing` section the landing page
 * composes, wrapped in the Field Notebook masthead/footer chrome so
 * direct visitors land on a complete page rather than a fragment.
 *
 * Stripe Checkout URL resolution order (server-side, deployment-wired):
 *
 *   1. `STRIPE_PRO_CHECKOUT_URL` — server env, the canonical setting.
 *   2. `NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL` — public-bundle fallback
 *      (for environments where the marketing site bundles client-side).
 *   3. `Pricing` component's internal placeholder fallback — the link
 *      stays non-empty so QA notices a missing wiring.
 */
export default function PricingPage() {
  const stripeCheckoutUrl = (
    process.env.STRIPE_PRO_CHECKOUT_URL ??
    process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL ??
    ""
  ).trim();

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        position: "relative",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          borderBottom: "1px solid var(--wb-color-rule-line)",
          padding: "20px 48px",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 24,
        }}
      >
        <Link
          href="/"
          data-testid="pricing-page-home"
          style={{
            textDecoration: "none",
            color: "inherit",
            display: "inline-flex",
            alignItems: "baseline",
            gap: 12,
          }}
        >
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-md)",
              fontWeight: 600,
              letterSpacing: "-0.01em",
            }}
          >
            WormBase
          </span>
          <span
            className="wb-mono"
            style={{
              fontSize: "10px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            vol. I · field notebook · wormbase.io
          </span>
        </Link>
        <span
          className="wb-mono"
          style={{
            fontSize: "10px",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          MMXXVI · plate v · pricing
        </span>
      </header>

      <main style={{ flex: 1 }}>
        <Pricing stripeCheckoutUrl={stripeCheckoutUrl} />
      </main>

      <footer
        style={{
          borderTop: "1px solid var(--wb-color-rule-line)",
          padding: "32px 48px 48px",
          textAlign: "center",
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: "11px",
            letterSpacing: "0.06em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          specimen / lumbricus terrestris · agent / wormbase@v-demo · every
          answer carries its hash. · wormbase.io
        </span>
      </footer>
    </div>
  );
}
