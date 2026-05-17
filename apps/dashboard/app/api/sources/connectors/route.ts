/**
 * GET /api/sources/connectors — list connector kinds + JSON schemas.
 *
 * D4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Returns the static dashboard-side catalog (apps/dashboard/lib/
 * lake-surfaces-catalog.ts). For Thursday this is the source of truth
 * for the picker UI; cross-language sync with the Python registry
 * (packages/connectors/registry.py) is a post-Thursday delta.
 */
import { NextResponse } from "next/server";
import { CONNECTOR_CATALOG } from "../../../../lib/lake-surfaces-catalog";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({
    connectors: CONNECTOR_CATALOG,
  });
}
