/**
 * Pricing — Phase 4D real tiers + Stripe Checkout link.
 *
 * Replaces the 4A `PricingPlaceholder` with the orchestrator-decided pricing:
 *
 *   - Free        — 1 Slack workspace, ≤10 Persons, ≤1 source, conversation-only.
 *                   CTA → /onboarding (the same surface every signup path
 *                   lands on; pricing does not bifurcate the signup wire).
 *
 *   - Pro         — $60/seat/mo + 100 artifacts/mo + $1/artifact thereafter.
 *                   CTA → Stripe Checkout link via `stripeCheckoutUrl` prop
 *                   (sourced from `STRIPE_PRO_CHECKOUT_URL` env var on the
 *                   server, or `NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL` for the
 *                   client. v1 ships without billing webhooks; the link is
 *                   enough — Stripe handles the seat math and tells us by
 *                   email when a checkout completes).
 *
 *   - Enterprise  — custom. CTA → mailto: contact-sales link with a routed
 *                   subject so support can triage fast.
 *
 * The Pricing component is rendered both as a section on `/` and as the
 * core of the standalone `/pricing` route. The route version is preferred
 * for direct linking from blog posts, sales decks, and email signatures.
 *
 * Field Notebook design system: receipt-style three-column grid, serif
 * headlines, mono kickers, hash-gray meta lines, paper backgrounds.
 */
import Link from "next/link";
import { Button } from "@wormbase/design";
import type { CSSProperties } from "react";

const FALLBACK_STRIPE_URL =
  "https://buy.stripe.com/wormbase-pro-placeholder-not-yet-wired";

const CONTACT_SALES_MAILTO =
  "mailto:sales@wormbase.io" +
  "?subject=" +
  encodeURIComponent("WormBase Enterprise — pricing inquiry") +
  "&body=" +
  encodeURIComponent(
    "Hi WormBase team,\n\n" +
      "We'd like to talk about an Enterprise deployment.\n\n" +
      "Company:\nTeam size:\nChat platforms in use:\nData sources we'd connect:\nDeployment preference (SaaS / on-prem / VPC):\n\nThanks.",
  );

interface Tier {
  id: "free" | "pro" | "enterprise";
  name: string;
  pitch: string;
  priceLine: string;
  meterLine: string | null;
  bullets: string[];
  ctaLabel: string;
  ctaHref: (stripeUrl: string) => string;
  ctaVariant: "primary" | "secondary";
  /** Outbound `mailto:` / `https://` links bypass the Next router. */
  external: boolean;
}

const TIERS: Tier[] = [
  {
    id: "free",
    name: "Free",
    pitch: "One team, one chat platform — try the receipts.",
    priceLine: "$0 · forever",
    meterLine: "no card · upgrade when you outgrow it",
    bullets: [
      "1 Slack workspace",
      "Up to 10 Persons",
      "1 source connected",
      "Conversation-only — gold lake from chatter",
      "Receipts under every answer",
    ],
    ctaLabel: "Start free",
    ctaHref: () => "/onboarding",
    ctaVariant: "secondary",
    external: false,
  },
  {
    id: "pro",
    name: "Pro",
    pitch: "Whole company, every chat, every source, governed.",
    priceLine: "$60 / seat / month",
    meterLine: "100 artifacts / mo included · $1 / artifact thereafter",
    bullets: [
      "Unlimited Slack / Discord / Teams workspaces",
      "Unlimited Persons + per-Person autoresearch",
      "External warehouses (Snowflake, BigQuery, Postgres, S3)",
      "Domain owners, classification policies, audit log",
      "Reproducible-by-hash artifacts; replay any answer",
    ],
    ctaLabel: "Start Pro on Stripe",
    ctaHref: (stripeUrl) => stripeUrl,
    ctaVariant: "primary",
    external: true,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    pitch: "Custom deployment, on-prem option, dedicated success.",
    priceLine: "custom · annual",
    meterLine: "VPC inference · SOC2 trail · custom retention",
    bullets: [
      "Bring-your-own VPC inference endpoint",
      "Customer-hosted own-inference (private VLAN)",
      "Custom retention + classification policies",
      "Dedicated success engineer",
      "Priority connector + adapter requests",
    ],
    ctaLabel: "Contact sales",
    ctaHref: () => CONTACT_SALES_MAILTO,
    ctaVariant: "secondary",
    external: true,
  },
];

interface PricingProps {
  /**
   * Stripe Checkout URL for the Pro tier. Pages compose this from
   * `STRIPE_PRO_CHECKOUT_URL` (server) or
   * `NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL` (client).
   *
   * Falling back to `FALLBACK_STRIPE_URL` keeps the link non-empty when a
   * deployment hasn't wired Stripe yet — the placeholder URL self-marks
   * as a placeholder so QA notices.
   */
  stripeCheckoutUrl?: string;
}

export function Pricing({ stripeCheckoutUrl }: PricingProps = {}) {
  const stripeUrl = (stripeCheckoutUrl ?? "").trim() || FALLBACK_STRIPE_URL;

  return (
    <section
      data-testid="pricing-section"
      aria-labelledby="pricing-headline"
      style={sectionStyle}
    >
      <div style={innerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate v · pricing
        </p>
        <h2 id="pricing-headline" style={headlineStyle}>
          Pay for the receipts your company keeps.
        </h2>
        <p style={subheadStyle}>
          Free for one team and one chat. $60 per seat once it&rsquo;s the
          whole company — with 100 artifacts per month included and clear
          per-artifact overage. Enterprise is custom: VPC inference,
          on-prem deployment, dedicated success.
        </p>

        <ul style={tiersStyle}>
          {TIERS.map((tier) => (
            <li
              key={tier.id}
              data-testid={`pricing-tier-${tier.id}`}
              style={tier.id === "pro" ? tierStyleFeatured : tierStyle}
            >
              <header style={tierHeaderStyle}>
                <span className="wb-mono" style={tierKickerStyle}>
                  tier · {tier.id}
                </span>
                <h3 style={tierNameStyle}>{tier.name}</h3>
                <p style={tierPitchStyle}>{tier.pitch}</p>
              </header>

              <div style={priceBlockStyle}>
                <p className="wb-mono" style={priceLineStyle}>
                  {tier.priceLine}
                </p>
                {tier.meterLine ? (
                  <p className="wb-mono" style={meterLineStyle}>
                    {tier.meterLine}
                  </p>
                ) : null}
              </div>

              <ul style={bulletsStyle}>
                {tier.bullets.map((bullet) => (
                  <li key={bullet} style={bulletStyle}>
                    <span className="wb-mono" style={bulletDashStyle}>
                      —
                    </span>
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>

              <div style={ctaWrapStyle}>
                <PricingCta tier={tier} stripeUrl={stripeUrl} />
              </div>
            </li>
          ))}
        </ul>

        <p className="wb-mono" style={fineprintStyle}>
          prices in USD · billing handled by Stripe · enterprise contracts via
          sales@wormbase.io · v1 has no auto-renewal lock-in
        </p>
      </div>
    </section>
  );
}

interface PricingCtaProps {
  tier: Tier;
  stripeUrl: string;
}

function PricingCta({ tier, stripeUrl }: PricingCtaProps) {
  const href = tier.ctaHref(stripeUrl);
  const variant = tier.ctaVariant;
  const testId = `pricing-cta-${tier.id}`;

  // External / outbound (Stripe Checkout, mailto:) bypass the Next router.
  if (tier.external) {
    return (
      <a
        data-testid={testId}
        href={href}
        rel="noopener external"
        target={href.startsWith("mailto:") ? undefined : "_blank"}
        style={linkStyle}
      >
        <Button size="md" variant={variant} tabIndex={-1}>
          {tier.ctaLabel}
        </Button>
      </a>
    );
  }

  // Internal CTA (Free → /onboarding) uses next/link prefetch.
  return (
    <Link
      data-testid={testId}
      href={href}
      style={linkStyle}
    >
      <Button size="md" variant={variant} tabIndex={-1}>
        {tier.ctaLabel}
      </Button>
    </Link>
  );
}

const sectionStyle: CSSProperties = {
  width: "100%",
  padding: "96px 24px",
  background: "var(--wb-color-paper-deep)",
  borderTop: "1px solid var(--wb-color-rule-line)",
};

const innerStyle: CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
};

const eyebrowStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
  maxWidth: 820,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const tiersStyle: CSSProperties = {
  listStyle: "none",
  margin: "32px 0 0",
  padding: 0,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 16,
  alignItems: "stretch",
};

const tierStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: "24px 22px",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
};

const tierStyleFeatured: CSSProperties = {
  ...tierStyle,
  borderColor: "var(--wb-color-aged-ink)",
  borderWidth: 2,
  // The "featured" tile reads first by sitting on the same baseline grid
  // but with a thicker rule and a slightly off-paper background.
  background: "var(--wb-color-paper)",
  boxShadow: "0 1px 0 0 var(--wb-color-rule-line)",
};

const tierHeaderStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const tierKickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const tierNameStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-lg)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const tierPitchStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.5,
};

const priceBlockStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  paddingBottom: 12,
  borderBottom: "1px solid var(--wb-color-rule-line)",
};

const priceLineStyle: CSSProperties = {
  margin: 0,
  fontSize: 14,
  letterSpacing: "0.04em",
  color: "var(--wb-color-aged-ink)",
  fontWeight: 600,
};

const meterLineStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
};

const bulletsStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  flex: 1,
};

const bulletStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.5,
};

const bulletDashStyle: CSSProperties = {
  color: "var(--wb-color-botanical-green-deep)",
};

const ctaWrapStyle: CSSProperties = {
  marginTop: "auto",
  paddingTop: 8,
};

const linkStyle: CSSProperties = {
  textDecoration: "none",
  color: "inherit",
  display: "inline-block",
};

const fineprintStyle: CSSProperties = {
  margin: "32px 0 0",
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--wb-color-hash-gray)",
  textAlign: "center",
};
