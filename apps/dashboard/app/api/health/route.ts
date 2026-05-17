import { NextResponse } from "next/server";

/**
 * Simple health probe for Docker-compose orchestration.
 *
 * Returns 200 {"ok": true} when the Next.js process is responsive.
 * Does NOT validate Postgres connectivity — that check belongs on
 * individual data-fetching pages so empty states surface honestly.
 */
export function GET(): NextResponse {
  return NextResponse.json({ ok: true });
}
