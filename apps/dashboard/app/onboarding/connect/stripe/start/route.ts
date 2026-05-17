/**
 * GET /onboarding/connect/stripe/start — Sub-wave D Stripe OAuth kick-off.
 *
 * Sets the CSRF state cookie, builds the Stripe authorize URL, and
 * redirects. The callback at
 * ``/onboarding/connect/stripe/callback`` verifies the state cookie,
 * exchanges the code, and stores the token via the CredentialBroker.
 *
 * Falls through to the "not configured" surface when env vars are
 * missing — never to a credential-paste fallback for Stripe.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  STRIPE_STATE_COOKIE,
  buildStripeAuthorizeUrl,
  generateOAuthState,
  readStripeOAuthConfig,
} from "../../../../../lib/oauth/stripe";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const config = readStripeOAuthConfig();
  const origin = new URL(req.url).origin;

  if (!config.configured) {
    const target = new URL("/onboarding/connect/stripe/not-configured", origin);
    target.searchParams.set("missing", config.missing.join(","));
    return NextResponse.redirect(target, { status: 303 });
  }

  const state = generateOAuthState();
  const redirectUri = `${origin}/onboarding/connect/stripe/callback`;
  const authorizeUrl = buildStripeAuthorizeUrl({
    clientId: config.clientId as string,
    state,
    redirectUri,
  });

  const res = NextResponse.redirect(authorizeUrl, { status: 303 });
  res.cookies.set(STRIPE_STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 5 * 60, // 5 minutes — Stripe redirects within seconds
    path: "/",
  });
  return res;
}
