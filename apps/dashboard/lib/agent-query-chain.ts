/**
 * agent_query → chain walker (Wave 3 Task 3 — SOC-2-credibility view).
 *
 * Given a root ``audit_trail_id`` for an ``agent_query`` PEVR cycle,
 * assembles the full audit chain that fans out from it: the four PEVR
 * phase entries of the root agent_query itself, every ``inference_served``
 * / ``credential`` / ``query_correction_suggested`` / ``query_outcome_recorded``
 * entry caused by that root, AND every PEVR cycle a chained
 * query_correction_suggested kicked off (the retry-tree under the
 * original query).
 *
 * This is the surface the auditor clicks through to verify:
 *   - which agent issued the call,
 *   - what tool was invoked with what args,
 *   - which model served the inference (if any),
 *   - which scoped credentials were minted (with TTL + scope),
 *   - which gates fired (denials in red),
 *   - what the latency / cost / row_count came back as,
 *   - and — when the call failed — the full retry tree.
 *
 * Read-only, recursive-CTE-backed. Matches the canonical pattern in
 * ``decision-chain.ts``: a single SQL query gathers the candidate rows,
 * the TS side groups them by ``audit_trail_id``, orders by ``ts ASC``
 * for chronological replay, and renders the chain.
 *
 * Empty-state contract: if the root audit_trail_id has no matching
 * entries on this tenant, return ``null`` so the page renders an
 * honest "chain not found" state — never fabricate.
 */

import { DEFAULT_COMPANY_ID, pgQuery } from "./ledger-client";

// ─── Types ────────────────────────────────────────────────────────────────

/**
 * One entry node in the audit chain. Carries everything the timeline
 * component needs to render a per-kind detail row (and to highlight
 * gate denials, model invocations, credential issuance).
 */
export interface ChainEntry {
  /** Ledger seq for chronological ordering + copy-to-clipboard. */
  seq: string;
  /** Envelope kind: propose / execute / verify / resolve for PEVR cycles,
   *  or the payload kind (e.g. ``inference_served``) for one-shot
   *  audit entries. */
  envelopeKind: string;
  /** Effective payload kind — the ``kind`` field on the typed payload
   *  body (``agent_query``, ``credential``, ``inference_served``,
   *  ``query_correction_suggested``, ``query_outcome_recorded``).
   *  Derived from payload shape when the typed kind is implicit. */
  kind: string;
  /** ``audit_trail_id`` for PEVR cycles (== the cycle correlation key
   *  for agent_query); ``null`` for one-shot entries that aren't
   *  enclosed by an agent_query PEVR cycle. */
  auditTrailId: string | null;
  /** ``caused_by`` — references the parent audit_trail_id when this
   *  entry chains off a prior agent_query. */
  causedBy: string | null;
  /** ISO-8601 entry timestamp. */
  ts: string;
  /** Phase string for PEVR entries; ``null`` otherwise. */
  phase: "propose" | "execute" | "verify" | "resolve" | null;
  /** Entry hash hex (copy-to-clipboard / audit-tracker pasting). */
  hashHex: string;
  /** Raw payload body — used by per-kind renderers in the component
   *  (mcp_tool, route_mode, ttl_expires_at, failure_kind, ...). */
  payload: Record<string, unknown>;
}

export interface AgentQueryChain {
  /** The audit_trail_id of the root agent_query the page was opened on. */
  rootAuditTrailId: string;
  /** The agent that issued the root call (denormalized from the
   *  root's propose-phase payload). */
  agentId: string;
  /** The MCP tool the root invoked. */
  mcpTool: string;
  /** Route the gateway took — broker vs federate. */
  routeMode: "broker" | "federate";
  /** Latest phase observed for the ROOT agent_query (status field on
   *  the projection). ``denied`` if a governance gate blocked the call. */
  status: "propose" | "execute" | "verify" | "resolve" | "denied";
  /** Sum of resolve-phase latencies across the entire chain (root +
   *  retries), or ``null`` when no resolve phase has landed yet. */
  totalLatencyMs: number | null;
  /** Sum of resolve-phase cost_usd values across the chain as a
   *  fixed-point string (cost_usd is stored as a Decimal-shaped
   *  string in the ledger and projection). ``null`` when no
   *  resolve phase has landed yet. */
  totalCostUsd: string | null;
  /** Every chain entry in chronological order. PEVR phases stay
   *  grouped by audit_trail_id; one-shot entries interleave on ts. */
  entries: ChainEntry[];
}

// ─── Pure-function chain assembler ────────────────────────────────────────

/**
 * Internal row shape returned by the recursive CTE. Same shape used by
 * the in-memory test fixtures so the assembler can be unit-tested
 * without a live Postgres tenant.
 */
export interface CandidateChainRow {
  seq: string;
  envelopeKind: string;
  ts: string;
  hashHex: string;
  payload: Record<string, unknown>;
}

/**
 * Recognize a PEVR envelope as belonging to an ``agent_query`` cycle by
 * its payload shape. Mirrors the Python builder's ``_is_agent_query_payload``
 * heuristic so a re-fold on either side picks up the same row stream.
 */
function isAgentQueryPayload(p: Record<string, unknown>): boolean {
  return (
    typeof p.audit_trail_id === "string" &&
    typeof p.phase === "string" &&
    typeof p.mcp_tool === "string" &&
    typeof p.route_mode === "string"
  );
}

/**
 * Recognize a PEVR envelope as belonging to a ``credential`` cycle by
 * its payload shape (single-kind status field per Addendum 3).
 */
function isCredentialPayload(p: Record<string, unknown>): boolean {
  const k = p.credential_kind;
  if (k !== "data" && k !== "model") return false;
  return typeof p.ttl_expires_at === "string" && typeof p.issued_by === "string";
}

/**
 * Pull the chain-effective payload kind from an envelope row.
 *
 * Order of precedence:
 *   1. If the payload carries an ``audit_trail_id`` + ``phase``, it is
 *      part of an agent_query cycle.
 *   2. If the payload carries a CredentialPayload shape, it's a
 *      credential lifecycle event.
 *   3. If the payload carries a top-level ``kind`` field (set on
 *      one-shot entries like ``inference_served`` /
 *      ``query_correction_suggested`` / ``query_outcome_recorded``),
 *      use that.
 *   4. Fall back to the envelope kind — the propose/execute/verify/
 *      resolve envelope itself. Used only for one-shot writes that
 *      bypass the typed-payload helpers.
 */
function effectiveKind(envelopeKind: string, payload: Record<string, unknown>): string {
  if (isAgentQueryPayload(payload)) return "agent_query";
  if (isCredentialPayload(payload)) return "credential";
  if (typeof payload.kind === "string") return payload.kind;
  return envelopeKind;
}

function pickAuditTrailId(payload: Record<string, unknown>): string | null {
  const direct = payload.audit_trail_id;
  if (typeof direct === "string" && direct.length > 0) return direct;
  // query_outcome_recorded references the agent_query via
  // ``agent_query_id``; treat that as the audit_trail_id binding so
  // the row groups under the right chain.
  const aq = (payload.agent_query_id as unknown);
  if (typeof aq === "string" && aq.length > 0) return aq;
  // query_correction_suggested references the failed query via
  // ``original_query_id`` (== that query's audit_trail_id).
  const orig = (payload.original_query_id as unknown);
  if (typeof orig === "string" && orig.length > 0) return orig;
  return null;
}

function pickCausedBy(payload: Record<string, unknown>): string | null {
  const c = payload.caused_by;
  if (typeof c === "string" && c.length > 0) return c;
  // One-shot entries (query_correction_suggested, query_outcome_recorded)
  // express their parent linkage via ``original_query_id`` /
  // ``agent_query_id`` rather than ``caused_by``. Treat those as the
  // implicit caused_by so the chain renderer can indent the row
  // beneath its parent agent_query.
  const orig = payload.original_query_id;
  if (typeof orig === "string" && orig.length > 0) return orig;
  const aq = payload.agent_query_id;
  if (typeof aq === "string" && aq.length > 0) return aq;
  return null;
}

function pickPhase(
  payload: Record<string, unknown>,
): "propose" | "execute" | "verify" | "resolve" | null {
  const p = payload.phase;
  if (p === "propose" || p === "execute" || p === "verify" || p === "resolve") {
    return p;
  }
  return null;
}

function tsCmp(a: string, b: string): number {
  // ISO-8601 strings compare correctly as strings; fall back to
  // numeric parse for any locale-quirk inputs.
  const na = Date.parse(a);
  const nb = Date.parse(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Pure-function chain assembler. Consumes a candidate row list (anchored
 * on the root audit_trail_id plus its caused_by fan-out) and produces a
 * fully-shaped ``AgentQueryChain`` ordered by ts ASC.
 *
 * Tested directly via fixture rows so the chain logic doesn't depend
 * on a live Postgres tenant.
 */
export function assembleChain(
  rows: CandidateChainRow[],
  rootAuditTrailId: string,
): AgentQueryChain | null {
  if (rows.length === 0) return null;

  // Normalize every candidate row into a ChainEntry.
  const entries: ChainEntry[] = rows.map((r) => {
    const payload = r.payload ?? {};
    return {
      seq: r.seq,
      envelopeKind: r.envelopeKind,
      kind: effectiveKind(r.envelopeKind, payload),
      auditTrailId: pickAuditTrailId(payload),
      causedBy: pickCausedBy(payload),
      ts: r.ts,
      phase: pickPhase(payload),
      hashHex: r.hashHex,
      payload,
    };
  });

  // Find the root's propose-phase entry (canonical source of agent_id /
  // mcp_tool / route_mode). Fall back to ANY phase of the root cycle
  // if propose isn't present (defensive — replay-truncation, missing
  // entries on Postgres roll-up).
  const rootPhases = entries.filter(
    (e) => e.auditTrailId === rootAuditTrailId && e.kind === "agent_query",
  );
  if (rootPhases.length === 0) return null;
  const propose = rootPhases.find((e) => e.phase === "propose") ?? rootPhases[0];
  const proposePayload = propose.payload as Record<string, unknown>;
  const agentId = typeof proposePayload.agent_id === "string" ? proposePayload.agent_id : "";
  const mcpTool = typeof proposePayload.mcp_tool === "string" ? proposePayload.mcp_tool : "";
  const routeModeRaw = proposePayload.route_mode;
  const routeMode: "broker" | "federate" =
    routeModeRaw === "federate" ? "federate" : "broker";

  // Resolve the ROOT-cycle status (latest phase observed). ``denied``
  // takes priority if any envelope payload carries that explicit flag.
  const rootStatus = (() => {
    const phasesObserved = new Set(
      rootPhases.map((e) => e.phase).filter((p): p is "propose" | "execute" | "verify" | "resolve" => p !== null),
    );
    const denied = rootPhases.some(
      (e) => e.payload.passed === false || e.payload.status === "denied",
    );
    if (denied) return "denied" as const;
    if (phasesObserved.has("resolve")) return "resolve" as const;
    if (phasesObserved.has("verify")) return "verify" as const;
    if (phasesObserved.has("execute")) return "execute" as const;
    return "propose" as const;
  })();

  // Sum measurements across every resolve-phase entry in the chain
  // (root + any retry trees). Latency is integer ms; cost is a Decimal-
  // shaped string we accumulate via Number then re-stringify at fixed
  // precision so the rendered total stays JSON-safe.
  let totalLatencyMs: number | null = null;
  let totalCostNum: number | null = null;
  for (const e of entries) {
    if (e.kind !== "agent_query") continue;
    if (e.phase !== "resolve") continue;
    const lat = e.payload.latency_ms;
    if (typeof lat === "number" && Number.isFinite(lat)) {
      totalLatencyMs = (totalLatencyMs ?? 0) + lat;
    }
    const cu = e.payload.cost_usd;
    if (typeof cu === "string") {
      const n = Number(cu);
      if (Number.isFinite(n)) totalCostNum = (totalCostNum ?? 0) + n;
    }
  }
  const totalCostUsd = totalCostNum === null ? null : totalCostNum.toFixed(4);

  // Chronological ordering. PEVR phases inside the same audit_trail_id
  // group naturally hold ts ASC because the ledger writes them under a
  // single transaction with monotonic seqs.
  entries.sort((a, b) => {
    const tsdiff = tsCmp(a.ts, b.ts);
    if (tsdiff !== 0) return tsdiff;
    // Tie-break on seq (string-encoded bigint; numeric compare safe up
    // to 2^53).
    const na = Number(a.seq);
    const nb = Number(b.seq);
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
    return a.seq < b.seq ? -1 : 1;
  });

  return {
    rootAuditTrailId,
    agentId,
    mcpTool,
    routeMode,
    status: rootStatus,
    totalLatencyMs,
    totalCostUsd,
    entries,
  };
}

// ─── Postgres-bound entry point ───────────────────────────────────────────

/**
 * Resolve the full audit chain for a single root ``agent_query`` cycle.
 *
 * Recursive CTE strategy:
 *
 *   1. SEED — entries WHERE ``payload->>'audit_trail_id' = $auditTrailId``
 *      AND tenant scope matches. Picks up the four PEVR phase rows.
 *   2. FAN-OUT — entries WHERE ``payload->>'caused_by' = $auditTrailId``
 *      OR ``payload->>'original_query_id' = $auditTrailId``
 *      OR ``payload->>'agent_query_id' = $auditTrailId``.
 *      This catches inference_served / credential / query_correction_suggested
 *      / query_outcome_recorded entries chained off the root.
 *   3. RECURSE — for any chained entry that has its own ``audit_trail_id``
 *      (i.e. a query_correction_suggested kicked off another agent_query
 *      lifecycle), walk its phases too. Bounded by ``LIMIT`` to keep
 *      the chain finite even on pathological retry trees.
 *   4. ORDER BY ts ASC for chronological replay.
 *
 * Read-only — never writes to the ledger. Returns ``null`` when no
 * rows match the root audit_trail_id (the surface renders an honest
 * empty state).
 */
export async function getAgentQueryChain(
  companyId: string = DEFAULT_COMPANY_ID,
  auditTrailId: string,
): Promise<AgentQueryChain | null> {
  if (!auditTrailId) return null;
  if (!process.env.DATABASE_URL && !process.env.WORMBASE_LEDGER_DSN) return null;

  // Recursive CTE walking caused_by upstream AND downstream:
  //   - the SEED captures the four PEVR phase rows for the root
  //     audit_trail_id;
  //   - the FAN-OUT picks up every entry that links back to ANY
  //     audit_trail_id already in the working set, via ``caused_by``,
  //     ``original_query_id``, or ``agent_query_id`` — plus any entry
  //     whose own audit_trail_id is in the working set (a chained
  //     agent_query's PEVR phases).
  //
  // The LIMIT on the working set is defensive. Most chains are <30
  // entries (root PEVR + 1-2 retries + the outcome row); 1000 is a
  // headroom cap for pathological retry trees.
  const sql = `
    WITH RECURSIVE chain (
      seq, envelope_kind, ts, hash_hex, payload, audit_trail_id
    ) AS (
      SELECT l.seq::text                       AS seq,
             l.kind                            AS envelope_kind,
             l.ts                              AS ts,
             encode(l.hash, 'hex')             AS hash_hex,
             l.payload                         AS payload,
             COALESCE(
               l.payload->>'audit_trail_id',
               l.payload->>'original_query_id',
               l.payload->>'agent_query_id'
             )                                 AS audit_trail_id
        FROM ledger l
       WHERE l.company_id = $1
         AND COALESCE(
               l.payload->>'audit_trail_id',
               l.payload->>'original_query_id',
               l.payload->>'agent_query_id'
             ) = $2

      UNION ALL

      SELECT l.seq::text,
             l.kind,
             l.ts,
             encode(l.hash, 'hex'),
             l.payload,
             COALESCE(
               l.payload->>'audit_trail_id',
               l.payload->>'original_query_id',
               l.payload->>'agent_query_id'
             )
        FROM ledger l, chain c
       WHERE l.company_id = $1
         AND (
               l.payload->>'caused_by'         = c.audit_trail_id
            OR l.payload->>'original_query_id' = c.audit_trail_id
            OR l.payload->>'agent_query_id'    = c.audit_trail_id
            OR COALESCE(
                 l.payload->>'audit_trail_id',
                 l.payload->>'original_query_id',
                 l.payload->>'agent_query_id'
               ) = c.audit_trail_id
         )
    )
    SELECT DISTINCT seq, envelope_kind, ts, hash_hex, payload
      FROM chain
     ORDER BY ts ASC, seq ASC
     LIMIT 1000
  `;

  try {
    const res = await pgQuery<{
      seq: string;
      envelope_kind: string;
      ts: Date | string;
      hash_hex: string;
      payload: Record<string, unknown> | null;
    }>(sql, [companyId, auditTrailId]);

    if (res.rowCount === 0) return null;

    const rows: CandidateChainRow[] = res.rows.map((r) => ({
      seq: String(r.seq),
      envelopeKind: r.envelope_kind,
      ts:
        r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString(),
      hashHex: r.hash_hex,
      payload: r.payload ?? {},
    }));

    return assembleChain(rows, auditTrailId);
  } catch {
    // Postgres unavailable (fresh dev tree, ledger schema not yet
    // bootstrapped). Treat as "chain not found" so the surface
    // renders an honest empty state rather than crashing.
    return null;
  }
}
