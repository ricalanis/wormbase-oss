/**
 * GET /auth/email/confirm — visitor-facing magic-link confirm landing.
 *
 * Phase 4 Task 4C of the Wave H launch. The actual session-binding
 * lives in the API route at ``/api/auth/email/confirm`` (Phase 1B.D
 * + 4C upgrade). This page exists so magic-link emails carry a
 * human-readable URL the visitor can recognize before the API runs.
 * The page itself does one of three things:
 *
 *   1. ``?token=<token>`` present → server-redirect to the API route
 *      (which decodes the token, picks a demo tenant, sets the signed
 *      session cookie, and 303s to ``/dashboard?welcome=email``).
 *
 *   2. ``?error=<code>`` present (the API may bounce the visitor here
 *      with an error code in a future iteration) → render an honest
 *      "your magic link expired / was invalid" panel pointing at the
 *      sign-up form.
 *
 *   3. Neither → render a "missing token" panel directing visitors to
 *      ``/`` (sign-up form lives in the landing's SignupCTA).
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { Page } from "@wormbase/design";

export const metadata = {
  title: "WormBase · confirming magic link",
};

export const dynamic = "force-dynamic";

interface ConfirmPageProps {
  searchParams: Promise<{ token?: string; error?: string }>;
}

function friendlyErrorCopy(code: string | undefined): string {
  if (code === "invalid_or_expired") {
    return "this magic link is expired or invalid. links live for 15 minutes — request a fresh one to continue.";
  }
  if (code === "missing_token") {
    return "this URL is missing the token query param. the magic link in your email carries the full link — try that one again.";
  }
  if (code === "auth_secret_unset") {
    return "magic-link signup is not configured on this deployment yet. install via Slack instead, or contact the operator.";
  }
  if (code === "no_demo_tenants") {
    return "no demo tenants are seeded on this deployment yet — install via Slack to start a fresh tenant.";
  }
  return "something went wrong confirming your magic link. request a fresh one to continue.";
}

export default async function ConfirmPage({ searchParams }: ConfirmPageProps) {
  const params = await searchParams;
  const token = (params.token ?? "").trim();
  const errorCode = (params.error ?? "").trim();

  if (!errorCode && token) {
    // Hand off to the API route which sets the signed session cookie
    // and 303s to /dashboard?welcome=email. We mirror the API route's
    // expected shape — encodeURIComponent matches what /api expects.
    redirect(`/api/auth/email/confirm?token=${encodeURIComponent(token)}`);
  }

  // Either no token was passed, or the API route bounced back with an
  // error param — render an honest empty/error state.
  const message = errorCode
    ? friendlyErrorCopy(errorCode)
    : friendlyErrorCopy("missing_token");

  return (
    <Page subtitle="confirm magic link">
      <section
        data-testid="confirm-section"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          padding: 24,
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
            magic link · confirm
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 24,
              fontWeight: 500,
            }}
          >
            We couldn&rsquo;t finish your sign-in.
          </h1>
        </header>
        <div
          data-testid="confirm-error"
          style={{
            padding: "16px 18px",
            border: "1px dashed var(--wb-color-rule-line)",
            background: "var(--wb-color-paper-deep)",
            color: "var(--wb-color-aged-ink)",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
            lineHeight: 1.55,
          }}
        >
          {message}
        </div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Link
            href="/"
            data-testid="confirm-back-to-signup"
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
            request a fresh magic link
          </Link>
          <Link
            href="/onboarding"
            data-testid="confirm-walk-demo"
            className="wb-mono"
            style={{
              fontSize: 12,
              letterSpacing: "0.08em",
              color: "var(--wb-color-hash-gray)",
              textDecoration: "underline",
              textUnderlineOffset: 3,
              alignSelf: "center",
            }}
          >
            walk the demo workspace instead
          </Link>
        </div>
      </section>
    </Page>
  );
}
