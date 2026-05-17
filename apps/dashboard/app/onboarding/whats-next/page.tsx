/**
 * GET /onboarding/whats-next — T2 fork (Block G4 / PRD §17).
 *
 * Server component. Three buttons:
 *   1. "Add another source" → /onboarding (loop back to T0 grid)
 *   2. "Connect a chat platform" → /onboarding/oauth/slack/start (existing)
 *   3. "Continue setup" → /onboarding/setup-mode/choose (wizard-vs-bot fork)
 *
 * Reached after the first connector connect + cascade fires. The user
 * can iterate (more sources) before committing to a setup mode.
 */
import Link from "next/link";
import { Page } from "@wormbase/design";

export const metadata = {
  title: "WormBase · What's next?",
};

export const dynamic = "force-dynamic";

const CARDS: Array<{
  testId: string;
  href: string;
  title: string;
  blurb: string;
  variant: "primary" | "secondary";
}> = [
  {
    testId: "whats-next-continue-setup",
    href: "/onboarding/setup-mode/choose",
    title: "Continue setup",
    blurb:
      "Pick how to finish onboarding — dashboard wizard or worm-driven chat. Both cover the same ground; the wizard is faster, the bot is more conversational.",
    variant: "primary",
  },
  {
    testId: "whats-next-add-source",
    href: "/onboarding",
    title: "Add another source",
    blurb:
      "Loop back to the connector grid and wire up a second data source before completing setup. The medallion cascade fires on every new source.",
    variant: "secondary",
  },
  {
    testId: "whats-next-connect-platform",
    href: "/onboarding/oauth/slack/start",
    title: "Connect a chat platform",
    blurb:
      "Bring your team in. The worm joins your Slack workspace, lurks for ingest, and unlocks the bot-driven setup path.",
    variant: "secondary",
  },
];

export default async function WhatsNextPage() {
  return (
    <Page subtitle="onboarding · tier 2 · what's next">
      <section
        data-testid="whats-next"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          border: "1px solid var(--wb-color-paper-edge)",
          padding: 22,
          background: "var(--wb-color-paper)",
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            tier 2 · what's next
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 24,
              fontWeight: 500,
            }}
          >
            Source connected. The cascade is running.
          </h2>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink-soft)",
              fontSize: 14,
              lineHeight: 1.55,
              maxWidth: 640,
            }}
          >
            Bronze → silver → gold is firing now; your first KPI proposal is
            seconds away. Pick the next move:
          </p>
        </header>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12,
          }}
        >
          {CARDS.map((c) => (
            <Link
              key={c.testId}
              href={c.href}
              data-testid={c.testId}
              data-variant={c.variant}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                border: "1px solid var(--wb-color-paper-edge)",
                borderLeft:
                  c.variant === "primary"
                    ? "3px solid var(--wb-color-botanical-green)"
                    : "3px solid var(--wb-color-paper-edge)",
                background:
                  c.variant === "primary"
                    ? "var(--wb-color-paper)"
                    : "var(--wb-color-paper-deep)",
                padding: 16,
                textDecoration: "none",
                color: "var(--wb-color-aged-ink)",
                borderRadius: 0,
              }}
            >
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 18,
                  fontWeight: 500,
                }}
              >
                {c.title}
              </span>
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  color: "var(--wb-color-aged-ink-soft)",
                  lineHeight: 1.5,
                }}
              >
                {c.blurb}
              </span>
            </Link>
          ))}
        </div>
      </section>
    </Page>
  );
}
