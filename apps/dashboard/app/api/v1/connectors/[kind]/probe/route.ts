/**
 * GET /api/v1/connectors/{kind}/probe — Sub-wave D dashboard proxy.
 *
 * Forwards to worm-core's ``GET /api/v1/connectors/{kind}/probe``.
 * Returns the same envelope (``{kind, state, reason}``) so the
 * dashboard's ``lib/connector-probes.ts`` accessor can call us
 * without knowing about the upstream layout.
 *
 * On upstream unreachable we synthesize an honest ``state="unknown"``
 * response (with the error in ``reason``) rather than 502'ing — the
 * marketplace row renders a neutral badge so the page still loads.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function wormCoreBaseUrl(): string {
  return (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_WORM_CORE_BASE
  ).replace(/\/+$/, "");
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ kind: string }> },
): Promise<NextResponse> {
  const { kind } = await ctx.params;
  const cleanKind = (kind ?? "").trim();
  if (!cleanKind) {
    return NextResponse.json(
      { kind: "", state: "unknown", reason: "empty connector kind" },
      { status: 400 },
    );
  }
  const upstreamUrl =
    `${wormCoreBaseUrl()}/api/v1/connectors/` +
    `${encodeURIComponent(cleanKind)}/probe`;
  let res: Response;
  try {
    res = await fetch(upstreamUrl, { method: "GET", cache: "no-store" });
  } catch (err) {
    return NextResponse.json(
      {
        kind: cleanKind,
        state: "unknown",
        reason: `worm-core unreachable: ${(err as Error).message ?? String(err)}`,
      },
      { status: 200 },
    );
  }
  if (res.status === 404) {
    return NextResponse.json(
      {
        kind: cleanKind,
        state: "unknown",
        reason: `unknown connector kind '${cleanKind}'`,
      },
      { status: 404 },
    );
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return NextResponse.json(
      {
        kind: cleanKind,
        state: "unknown",
        reason: `worm-core probe HTTP ${res.status}: ${text.slice(0, 200)}`,
      },
      { status: 200 },
    );
  }
  let body: Record<string, unknown>;
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch (err) {
    return NextResponse.json(
      {
        kind: cleanKind,
        state: "unknown",
        reason: `non-JSON probe response: ${(err as Error).message ?? String(err)}`,
      },
      { status: 200 },
    );
  }
  return NextResponse.json(body, { status: 200 });
}
