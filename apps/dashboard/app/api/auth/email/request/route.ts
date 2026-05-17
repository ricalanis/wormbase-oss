/**
 * POST /api/auth/email/request — magic-link request endpoint.
 *
 * Phase 1B.D of the multi-tenancy v2 plan. The evaluator sends an
 * email; the worm mints a signed magic-link token (15-min TTL) and
 * sends it via the configured ``MagicLinkSender`` (default:
 * ``LogOnlySender`` — Phase 4 polish wires SMTP/SES).
 *
 * Body:
 *   ``{"email": "evaluator@example.com"}``
 *
 * Response (production):
 *   ``{"sent": true, "expires_in_s": 900, "pending_token_hash": "..."}``
 *
 * Response (dev mode — ``WORMBASE_AUTH_DEV_MODE=1``):
 *   ``{"sent": true, "expires_in_s": 900, "pending_token_hash": "...",
 *      "magic_link": "https://.../api/auth/email/confirm?token=..."}``
 *
 * The pending_token_hash is what the matching ``tenant_signup_initiated``
 * ledger entry's ``pending_token_hash`` field will carry — the confirm
 * endpoint re-derives this hash from the presented token to verify the
 * request matches a recently-emitted initiation.
 *
 * Errors:
 *   - 400 invalid_email / bad_json
 *   - 503 auth_secret_unset (WORMBASE_LEDGER_API_TOKEN missing)
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import {
  LogOnlySender,
  encodeMagicLinkToken,
  hashTokenForLedger,
  isValidEmailShape,
} from "../../../../../lib/server/auth/magic-link";

export const dynamic = "force-dynamic";

const TOKEN_TTL_S = 900;

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: { email?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "bad_json", message: "request body must be JSON" },
      { status: 400 },
    );
  }
  const email =
    typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !isValidEmailShape(email)) {
    return NextResponse.json(
      { error: "invalid_email", message: "email field required" },
      { status: 400 },
    );
  }

  const secret = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!secret) {
    return NextResponse.json(
      {
        error: "auth_secret_unset",
        message:
          "WORMBASE_LEDGER_API_TOKEN unset; magic-link auth disabled until configured",
      },
      { status: 503 },
    );
  }

  const token = encodeMagicLinkToken({
    email,
    secret,
    expiresInSeconds: TOKEN_TTL_S,
  });
  const tokenHash = hashTokenForLedger(token);

  const dashboardUrl =
    (process.env.WORMBASE_DASHBOARD_URL ?? "").replace(/\/+$/, "") ||
    new URL(req.url).origin;
  const link = `${dashboardUrl}/api/auth/email/confirm?token=${encodeURIComponent(token)}`;

  const sender = new LogOnlySender();
  await sender.send({ to: email, link, expiresInS: TOKEN_TTL_S });

  const devMode = (process.env.WORMBASE_AUTH_DEV_MODE ?? "").trim() === "1";
  const respBody: Record<string, unknown> = {
    sent: true,
    expires_in_s: TOKEN_TTL_S,
    pending_token_hash: tokenHash,
  };
  if (devMode) respBody.magic_link = link;
  return NextResponse.json(respBody, { status: 200 });
}
