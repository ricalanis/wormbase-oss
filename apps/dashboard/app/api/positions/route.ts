import { NextResponse } from "next/server";

import { POSITIONS } from "../../../lib/positions";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ ok: true, positions: POSITIONS });
}
