/**
 * GET /onboarding/connect/{connector}/callback — OAuth callback.
 *
 * Sub-wave D (2026-05-30): Stripe is now the reference impl. When
 * ``connector === "stripe"`` and the Stripe OAuth env vars
 * (``STRIPE_OAUTH_CLIENT_ID`` + ``STRIPE_OAUTH_CLIENT_SECRET``) are
 * set, this route exchanges ``?code=`` for an access token, stores it
 * via the CredentialBroker (Vault when ``VAULT_ADDR`` set; env-
 * resident otherwise), emits a ``source_connected`` ledger entry, and
 * redirects to the source detail page.
 *
 * When the env vars are MISSING for Stripe, the route renders an
 * honest "not configured" surface — we deliberately do NOT fall back
 * to the credential-paste form (that fallback was the bug Sub-wave D
 * graduated out of). The other three OAuth-style connectors
 * (salesforce / hubspot / gsheets) still use the credential-paste
 * fallback; OAuth ports for them are a future wave.
 *
 * Failure modes:
 *   - 400 on state-cookie mismatch (CSRF)
 *   - 400 on missing/empty code
 *   - 502 on Stripe token-exchange failure (passes through Stripe's
 *     ``invalid_grant`` / ``invalid_client`` error contract)
 *
 * No synthesized identities. No fake grants. The honest-disabled
 * "not configured" path is preferable to a working-looking redirect
 * to a credential-paste form that's secretly broken.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import {
  STRIPE_STATE_COOKIE,
  exchangeStripeCode,
  readStripeOAuthConfig,
  storeStripeToken,
} from "../../../../../lib/oauth/stripe";

export const dynamic = "force-dynamic";

const STRIPE_KIND = "stripe";

/** Connectors still using the credential-paste fallback (future-wave OAuth ports). */
const CREDENTIAL_PASTE_CONNECTORS = new Set([
  "salesforce",
  "hubspot",
  "gsheets",
]);

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ connector: string }> },
): Promise<NextResponse> {
  const { connector } = await ctx.params;
  const origin = new URL(req.url).origin;
  const url = new URL(req.url);
  const code = (url.searchParams.get("code") ?? "").trim();
  const state = (url.searchParams.get("state") ?? "").trim();
  const stripeError = (url.searchParams.get("error") ?? "").trim();

  if (connector === STRIPE_KIND) {
    return handleStripeCallback({
      origin,
      code,
      state,
      providerError: stripeError,
    });
  }

  // The other three OAuth-style connectors stay on the credential-paste
  // fallback for now. Future-wave port follows the same pattern as
  // Stripe.
  if (CREDENTIAL_PASTE_CONNECTORS.has(connector)) {
    const target = new URL(
      `/onboarding/connect/${connector}/credentials`,
      origin,
    );
    target.searchParams.set("oauth_unconfigured", "1");
    target.searchParams.set(
      "hint",
      `OAuth handshake for ${connector} lands in a future wave; ` +
        "paste an API key for now (Stripe is the reference impl shipped first)",
    );
    return NextResponse.redirect(target, { status: 303 });
  }

  // Unknown connector — render a generic 404-style error.
  return NextResponse.json(
    {
      ok: false,
      error: `unknown OAuth connector ${connector}`,
    },
    { status: 404 },
  );
}

interface StripeCallbackOpts {
  origin: string;
  code: string;
  state: string;
  providerError: string;
}

async function handleStripeCallback(
  opts: StripeCallbackOpts,
): Promise<NextResponse> {
  const config = readStripeOAuthConfig();
  if (!config.configured) {
    // Honest "not configured" surface — never the broken
    // credential-paste fallback for Stripe.
    const target = new URL("/onboarding/connect/stripe/not-configured", opts.origin);
    target.searchParams.set(
      "missing",
      config.missing.join(","),
    );
    return NextResponse.redirect(target, { status: 303 });
  }

  // Stripe-side error path. The provider passes ``error=access_denied``
  // when the user clicks "Cancel" on the consent screen — we surface
  // that distinctly from a token-exchange failure.
  if (opts.providerError) {
    const target = new URL("/onboarding/connect/stripe/error", opts.origin);
    target.searchParams.set("error", opts.providerError);
    target.searchParams.set("phase", "consent");
    return NextResponse.redirect(target, { status: 303 });
  }

  // CSRF check — the ``./start`` route sets the state cookie before
  // redirecting to Stripe's authorize URL.
  const cookieStore = await cookies();
  const stateCookie = cookieStore.get(STRIPE_STATE_COOKIE)?.value ?? "";
  if (!opts.state || !stateCookie || opts.state !== stateCookie) {
    return NextResponse.json(
      {
        ok: false,
        error: "state_mismatch",
        detail:
          "CSRF state cookie missing or did not match the state query " +
          "param. Restart the connect flow from the Stripe Add Source CTA.",
      },
      { status: 400 },
    );
  }

  if (!opts.code) {
    return NextResponse.json(
      { ok: false, error: "missing_code" },
      { status: 400 },
    );
  }

  // Token exchange.
  let token;
  try {
    token = await exchangeStripeCode({
      code: opts.code,
      // Resolve the secret via env://STRIPE_OAUTH_CLIENT_SECRET (the
      // canonical scheme). Operators using Vault override by setting
      // STRIPE_OAUTH_CLIENT_SECRET to vault://<path>.
      clientSecretRef:
        (process.env.STRIPE_OAUTH_CLIENT_SECRET ?? "").startsWith("vault://") ||
        (process.env.STRIPE_OAUTH_CLIENT_SECRET ?? "").startsWith("env://")
          ? (process.env.STRIPE_OAUTH_CLIENT_SECRET as string)
          : "env://STRIPE_OAUTH_CLIENT_SECRET",
    });
  } catch (err) {
    const e = err as Error & { code?: string; status?: number };
    const target = new URL("/onboarding/connect/stripe/error", opts.origin);
    target.searchParams.set("error", e.code ?? "token_exchange_failed");
    target.searchParams.set("phase", "token_exchange");
    target.searchParams.set("detail", e.message.slice(0, 200));
    return NextResponse.redirect(target, { status: 303 });
  }

  // Resolve tenant slug. The dashboard owns the cookie name; the
  // value is set by the channel-OAuth install or the test harness.
  const tenantSlug =
    cookieStore.get("wormbase-tenant-slug")?.value ?? "baseworm";

  // Token storage.
  let storage;
  try {
    storage = await storeStripeToken({
      tenantSlug,
      token,
    });
  } catch (err) {
    const e = err as Error;
    const target = new URL("/onboarding/connect/stripe/error", opts.origin);
    target.searchParams.set("error", "storage_failed");
    target.searchParams.set("phase", "token_storage");
    target.searchParams.set("detail", e.message.slice(0, 200));
    return NextResponse.redirect(target, { status: 303 });
  }

  // Best-effort: emit a source_connected ledger entry via the existing
  // ledger-client write path (synthetic receipt + tryPgWrite). The
  // worm's auto-bronze cascade picks the entry up on the next refresh.
  try {
    const { emitStripeSourceConnected } = await import(
      "../../../../../lib/oauth/stripe-ledger"
    );
    await emitStripeSourceConnected({
      tenantSlug,
      stripeUserId: token.stripe_user_id,
      scope: token.scope,
      livemode: token.livemode,
      credentialHandle: storage.handle,
      credentialScheme: storage.scheme,
    });
  } catch {
    // Non-fatal — the credential is stored, the user can re-trigger
    // the discover step from the source page if the ledger write
    // races.
  }

  // Clear the state cookie + redirect to the source detail page.
  const target = new URL(
    `/sources/new/stripe?connected=1&account=${encodeURIComponent(token.stripe_user_id)}`,
    opts.origin,
  );
  const res = NextResponse.redirect(target, { status: 303 });
  res.cookies.set(STRIPE_STATE_COOKIE, "", {
    maxAge: 0,
    path: "/",
  });
  return res;
}
