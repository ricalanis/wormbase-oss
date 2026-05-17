/**
 * GET /api/v1/connectors/list — proxy to worm-core's connector registry.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Replaces the hardcoded `lib/connectors-catalog.ts` for the
 * `/sources/new` picker. The dashboard now fetches the catalog from
 * worm-core so promoting a connector status (coming_soon → preview →
 * production) requires editing exactly one place: the Python connector
 * class. Keeps the connector picker honest with the runtime.
 *
 * The worm-core `/api/v1/connectors` endpoint is read-only and
 * unauthenticated (parallel to `/mcp/catalog`); we forward the response
 * unchanged plus a small envelope tagged with the upstream URL for
 * debug. On worm-core unreachable we return 502 with an honest message
 * — the picker page renders an empty grid + retry link rather than
 * faking the catalog.
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

export interface ConnectorField {
  name: string;
  label: string;
  type: "string" | "password" | "number" | "boolean";
  required?: boolean;
  placeholder?: string;
  description?: string;
}

export type ConnectorStatus = "production" | "preview" | "coming_soon";

export interface ConnectorEntry {
  kind: string;
  label: string;
  status: ConnectorStatus;
  status_note: string;
  capabilities: string[];
  classification_hints: string[];
  config_schema: ConnectorField[];
}

export interface ConnectorsListBody {
  kinds: ConnectorEntry[];
}

export async function GET(): Promise<NextResponse> {
  const upstreamUrl = `${wormCoreBaseUrl()}/api/v1/connectors`;
  let res: Response;
  try {
    res = await fetch(upstreamUrl, { cache: "no-store" });
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_unreachable",
        message: (err as Error).message ?? String(err),
        upstream: upstreamUrl,
      },
      { status: 502 },
    );
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return NextResponse.json(
      {
        error: "worm_core_status",
        status: res.status,
        message: text.slice(0, 400),
        upstream: upstreamUrl,
      },
      { status: 502 },
    );
  }
  let body: ConnectorsListBody;
  try {
    body = (await res.json()) as ConnectorsListBody;
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_non_json",
        message: (err as Error).message ?? String(err),
        upstream: upstreamUrl,
      },
      { status: 502 },
    );
  }
  const kinds = Array.isArray(body.kinds) ? body.kinds : [];
  return NextResponse.json({ kinds });
}
