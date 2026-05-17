/**
 * GET /onboarding/connect/{connector}/start — Tier 1 connector-first entry.
 *
 * G3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Routes by connector kind:
 *   - csv_local    → /onboarding/connect/csv/upload (multipart upload page)
 *   - postgres / snowflake / http_csv / bigquery
 *                  → /onboarding/connect/{kind}/credentials (paste form)
 *   - stripe / hubspot / linear / notion (api-key OAuth-style)
 *                  → /onboarding/connect/{kind}/credentials (paste form)
 *                    Real Stripe Connect OAuth requires app registration
 *                    which is out of scope for the current cycle; pasting an
 *                    API key is the production path most evaluators use.
 *   - salesforce / gsheets (require Google / SF OAuth + service-account
 *                  bundle) → coming_soon redirect.
 *
 * Capability honesty: a connector with status="coming_soon" never reaches
 * a connect form; the redirect lands on /onboarding with a "not yet wired"
 * banner. The connector-first grid already prevents the click via the
 * notify-me modal, but this guard is a defense in depth.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  CONNECTOR_CATALOG,
  getConnectorByKind,
} from "../../../../../lib/lake-surfaces-catalog";

export const dynamic = "force-dynamic";

function originOf(req: NextRequest): string {
  return new URL(req.url).origin;
}

function comingSoonRedirect(
  req: NextRequest,
  kind: string,
  hint: string,
): NextResponse {
  const url = new URL("/onboarding", originOf(req));
  url.searchParams.set("error", `${kind}_coming_soon`);
  url.searchParams.set("hint", hint);
  return NextResponse.redirect(url, { status: 303 });
}


export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ connector: string }> },
): Promise<NextResponse> {
  const { connector } = await ctx.params;

  const entry = getConnectorByKind(connector);
  if (!entry) {
    const url = new URL("/onboarding", originOf(req));
    url.searchParams.set("error", "unknown_connector");
    url.searchParams.set(
      "hint",
      `connector kind '${connector}' not in catalog (${CONNECTOR_CATALOG.length} kinds available)`,
    );
    return NextResponse.redirect(url, { status: 303 });
  }

  if (entry.status === "coming_soon") {
    return comingSoonRedirect(req, connector, entry.statusNote);
  }

  // CSV upload routes to the multipart upload page.
  if (entry.kind === "csv_local") {
    return NextResponse.redirect(
      new URL("/onboarding/connect/csv/upload", originOf(req)),
      { status: 303 },
    );
  }

  // Everyone else lands on the credentials form. The form schema is
  // resolved server-side from the catalog entry; the form POSTs to
  // /onboarding/connect/{kind}/connect which runs authenticate + discover
  // + the medallion cascade.
  return NextResponse.redirect(
    new URL(`/onboarding/connect/${connector}/credentials`, originOf(req)),
    { status: 303 },
  );
}
