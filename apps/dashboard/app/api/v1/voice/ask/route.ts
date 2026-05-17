/**
 * POST /api/v1/voice/ask — dashboard proxy to the voice-agent service.
 *
 * W3.A12 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * The "Ask the worm" floater (rendered on every (app)-prefixed route)
 * captures a transcript via the Web Speech API (or a typed fallback)
 * and POSTs `{transcript}` here. We resolve the current Person and
 * tenant from cookies, forward to the voice-agent service's `/v1/ask`
 * over the compose network, and return the upstream envelope verbatim
 * (`{answer, hash_receipt, ledger_seq, model, session_id}`).
 *
 * No fixture fallbacks. If the voice-agent is down, return 503 with an
 * honest message; the floater renders a "service unavailable" state.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_VOICE_AGENT_URL = "http://voice-agent:8090";

function voiceAgentBaseUrl(): string {
  return (
    process.env.WORMBASE_VOICE_AGENT_URL ?? DEFAULT_VOICE_AGENT_URL
  ).replace(/\/+$/, "");
}

interface AskRequestBody {
  transcript?: unknown;
}

interface VoiceAgentKPIPayload {
  id: string;
  name: string;
  formula: string | null;
  unit: string | null;
  domain_id: string | null;
  owner_position: string | null;
  status: string | null;
}

interface VoiceAgentResponse {
  answer: string;
  hash_receipt: string;
  ledger_seq: number | null;
  model: string;
  session_id: string;
  // P13 — present on KPI-shaped questions when worm-core's MCP server
  // resolved a hit. The dashboard floater renders the KPI name + a
  // /trace?seq=<n> link pointing at the most recent ledger entry.
  citation_kind?: "kpi_node" | "chat_sent";
  kpi?: VoiceAgentKPIPayload;
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: AskRequestBody;
  try {
    body = (await req.json()) as AskRequestBody;
  } catch {
    return NextResponse.json(
      {
        error: "invalid_json",
        message: "request body must be valid JSON",
      },
      { status: 400 },
    );
  }

  const transcript =
    typeof body.transcript === "string" ? body.transcript.trim() : "";
  if (!transcript) {
    return NextResponse.json(
      {
        error: "transcript_required",
        message: "transcript is required and must be a non-empty string",
      },
      { status: 400 },
    );
  }

  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  // The (app) layout already redirects un-installed tenants to /onboarding,
  // so under normal flows `me` is non-null. Defensive: if a stray request
  // hits this route from outside the layout (e.g. cookie cleared mid-flight)
  // forward as anonymous rather than 401-blocking the floater.
  const personId = me?.personId ?? "anonymous";

  const upstreamUrl = `${voiceAgentBaseUrl()}/v1/ask`;
  let res: Response;
  try {
    res = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript,
        person_id: personId,
        tenant_id: tenant.slug,
      }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: "voice_agent_unreachable",
        message:
          (err as Error).message ??
          "voice-agent service did not respond — check the compose stack",
      },
      { status: 503 },
    );
  }

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    return NextResponse.json(
      {
        error: "voice_agent_non_json",
        message: text.slice(0, 400),
      },
      { status: 502 },
    );
  }

  if (!res.ok) {
    const envelope = (parsed ?? {}) as Record<string, unknown>;
    const message =
      typeof envelope.detail === "string"
        ? envelope.detail
        : typeof envelope.message === "string"
          ? envelope.message
          : `voice-agent returned HTTP ${res.status}`;
    const status = res.status >= 500 ? 503 : res.status;
    return NextResponse.json(
      { error: "voice_agent_error", message, upstream_status: res.status },
      { status },
    );
  }

  const upstream = (parsed ?? {}) as Partial<VoiceAgentResponse>;
  if (typeof upstream.answer !== "string" || upstream.answer.length === 0) {
    return NextResponse.json(
      {
        error: "voice_agent_invalid_envelope",
        message: "upstream response missing 'answer' field",
      },
      { status: 502 },
    );
  }

  return NextResponse.json(
    {
      answer: upstream.answer,
      hash_receipt: upstream.hash_receipt ?? null,
      ledger_seq:
        typeof upstream.ledger_seq === "number" ? upstream.ledger_seq : null,
      model: upstream.model ?? null,
      session_id: upstream.session_id ?? null,
      citation_kind: upstream.citation_kind ?? null,
      kpi: upstream.kpi ?? null,
    },
    { status: 200 },
  );
}
