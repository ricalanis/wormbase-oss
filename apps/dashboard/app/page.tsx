import Link from "next/link";
import { Button, WormMark } from "@wormbase/design";

import { ArchitectureDiagram } from "../components/landing/ArchitectureDiagram";
import { ChannelPlatforms } from "../components/landing/ChannelPlatforms";
import { HeroDemo } from "../components/landing/HeroDemo";
import { HowItWorks } from "../components/landing/HowItWorks";
import { Pricing } from "../components/landing/Pricing";
import { SignupCTA } from "../components/landing/SignupCTA";

/**
 * Landing page — Wave H · Phase 4A.
 *
 * Public unauthenticated `/` view. Dashboard authenticated routes live
 * under the `(app)` route group and stay protected by their own session
 * checks; this page is intentionally accessible without a session so
 * visitors can see the architecture before signing up.
 *
 * Sections (top → bottom):
 *
 *   1. Masthead
 *   2. Hero        — WormMark + serif headline + tagline + wire-replay
 *                    viewer (HeroDemo; SSR-replays a fixed `until_ts`
 *                    window of a demo tenant's ledger and surfaces
 *                    every row's hash receipt)
 *   3. Architecture — clickable 6-agent diagram with per-agent modals
 *                    (ArchitectureDiagram; sourced from CLAUDE.md §1.5)
 *   4. How it works — 5-beat product arc walkthrough (HowItWorks; canonical
 *                    arc from docs/superpowers/specs/2026-04-26-wormbase-product-arc.md)
 *   5. Pricing      — three real tiers (Pricing; Free / Pro $60 seat + 100
 *                    artifacts / Enterprise custom). Pro CTA links to
 *                    Stripe Checkout via STRIPE_PRO_CHECKOUT_URL env var.
 *   6. Sign-up      — placeholder primary + working /onboarding secondary
 *                    (SignupCTA; real signup wires in 4C)
 *   7. Colophon     — single mono footnote, receipts culture
 *
 * Anti-patterns intentionally avoided (PRD §4.4): no testimonial cards,
 * no feature grid (the architecture diagram is the architecture, not a
 * features grid), no emoji reactions as interface, no cliche AI imagery.
 */
export default async function LandingPage() {
  // 4B: render the wire-replay viewer SSR-side. The HeroDemo server
  // component reads a deterministic replay payload via
  // ``getLandingReplay()`` and hands it to the client viewer.
  const heroDemo = await HeroDemo();
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        position: "relative",
      }}
    >
      {/* Masthead — thin top rule, serif wordmark, mono kicker */}
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
        <div
          style={{
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
        </div>
        <span
          className="wb-mono"
          style={{
            fontSize: "10px",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          MMXXVI · plate 001
        </span>
      </header>

      {/* HERO ------------------------------------------------------------ */}
      <main
        style={{
          maxWidth: 1080,
          margin: "0 auto",
          padding: "72px 48px 96px",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 32,
        }}
      >
        {/* Eyebrow kicker (mono, uppercase, hash-gray) */}
        <span
          className="wb-mono wb-enter wb-enter-1"
          style={{
            fontSize: "11px",
            letterSpacing: "0.24em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Institutional AI · Ledger-Native · Reproducible by Hash
        </span>

        {/* The worm itself — one illustration, never repeated */}
        <figure
          className="wb-enter wb-enter-2"
          style={{
            margin: 0,
            width: "min(640px, 100%)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div
            data-testid="hero-wormmark"
            style={{ display: "flex", justifyContent: "center" }}
          >
            <WormMark
              size={300}
              ink="var(--wb-color-botanical-green)"
              paper="var(--wb-color-paper)"
              title="WormBase monogram — institutional data agent"
            />
          </div>
        </figure>

        {/* Headline — serif, hand-set feel */}
        <h1
          className="wb-enter wb-enter-3"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "clamp(36px, 5vw, 56px)",
            fontWeight: 600,
            letterSpacing: "-0.015em",
            lineHeight: 1.08,
            maxWidth: 780,
          }}
        >
          WormBase
          <span
            aria-hidden="true"
            style={{
              display: "inline-block",
              margin: "0 12px",
              color: "var(--wb-color-hash-gray)",
              fontWeight: 400,
            }}
          >
            —
          </span>
          <span>Institutional AI for your company&rsquo;s data and processes</span>
        </h1>

        {/* Tagline — hash-gray, italic, single line */}
        <p
          className="wb-enter wb-enter-3"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: "var(--wb-text-md)",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
            lineHeight: 1.45,
          }}
        >
          Install on Monday. By Friday it has mapped your data, learned your
          processes, and can prove every answer with a hash.
        </p>

        {/* Single primary action. No secondary CTA, no feature grid. */}
        <div className="wb-enter wb-enter-4" style={{ marginTop: 8 }}>
          <Link href="/onboarding" style={{ textDecoration: "none" }}>
            <Button size="lg" data-testid="create-workspace">
              Create demo workspace
            </Button>
          </Link>
        </div>

        {/* Above-the-fold visualization — replay placeholder for 4B. */}
        <div
          className="wb-enter wb-enter-4"
          style={{ marginTop: 32, width: "100%" }}
        >
          {heroDemo}
        </div>
      </main>

      {/* ARCHITECTURE ---------------------------------------------------- */}
      <ArchitectureDiagram />

      {/* CHANNEL PLATFORMS ----------------------------------------------- */}
      {/* W2-A: data-driven tile section reading PLATFORMS from the
          canonical `lib/platform-status.ts` mirror. Surfaces every
          declared adapter (Slack production, Discord/Teams/WhatsApp
          preview, Signal coming_soon) with capability honesty —
          status badge, capability chips, click-to-modal carrying the
          canonical statusNote. */}
      <ChannelPlatforms />

      {/* HOW IT WORKS ---------------------------------------------------- */}
      <HowItWorks />

      {/* PRICING --------------------------------------------------------- */}
      <Pricing
        stripeCheckoutUrl={(
          process.env.STRIPE_PRO_CHECKOUT_URL ??
          process.env.NEXT_PUBLIC_STRIPE_PRO_CHECKOUT_URL ??
          ""
        ).trim()}
      />

      {/* SIGN-UP --------------------------------------------------------- */}
      <SignupCTA />

      {/* COLOPHON -------------------------------------------------------- */}
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
