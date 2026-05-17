/**
 * GET /api/auth/slack/callback — sign-in alias for the Slack OAuth callback.
 *
 * Phase 1B.C of the multi-tenancy v2 plan. Slack lets us register
 * multiple redirect_uris on one app. This route provides the canonical
 * "sign-in with Slack" surface — distinct from the onboarding redirect
 * URI (``/onboarding/oauth/slack/callback``), so a Phase 4C sign-in UI
 * can register *this* path with Slack while the install flow keeps
 * registering ``/onboarding/oauth/slack/callback``.
 *
 * Both paths re-use the same handler: the canonical OAuth callback at
 * ``app/onboarding/oauth/[platform]/callback/route.ts``. The wrapper
 * below injects ``{platform: 'slack'}`` into the ctx so the shared
 * handler doesn't need to know it was invoked from a different path.
 *
 * For 1B we ship the API surface signup-ready. The actual sign-in UI
 * button lands in Phase 4C.
 */
import type { NextRequest, NextResponse } from "next/server";
import { GET as canonicalCallback } from "../../../../onboarding/oauth/[platform]/callback/route";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  return canonicalCallback(req, {
    params: Promise.resolve({ platform: "slack" }),
  });
}
