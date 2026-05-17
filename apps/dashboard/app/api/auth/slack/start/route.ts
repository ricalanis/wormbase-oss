/**
 * GET /api/auth/slack/start — sign-in alias for the Slack OAuth start.
 *
 * Phase 1B.C of the multi-tenancy v2 plan. Companion to
 * ``/api/auth/slack/callback``. Wraps the canonical OAuth start handler
 * at ``app/onboarding/oauth/[platform]/start/route.ts`` and injects
 * ``{platform: 'slack'}``.
 *
 * Distinct from the onboarding start URL so a Phase 4C sign-in UI can
 * register a different redirect_uri (the matching callback at
 * ``/api/auth/slack/callback``) with Slack.
 */
import type { NextRequest, NextResponse } from "next/server";
import { GET as canonicalStart } from "../../../../onboarding/oauth/[platform]/start/route";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  return canonicalStart(req, {
    params: Promise.resolve({ platform: "slack" }),
  });
}
