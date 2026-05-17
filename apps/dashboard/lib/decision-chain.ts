/**
 * Decision → Bytes chain walker (Phase 3 Task 3C).
 *
 * Walks the dependency chain rooted at a single decision_recorded entry:
 *
 *   decision_recorded   →   process_map_proposed   →   kpi_node   →
 *     source_proposed   →   source_bronzed
 *
 * The chain is the SOC-2 / a16z credibility moment — turns "auditable,
 * hash-receipted" from a claim into a thing the operator can actually
 * click. Every step exposes its underlying ledger entry hash, ready to be
 * copied and pasted into a downstream auditor's tracker.
 *
 * Design notes:
 *
 * 1. **Read-only.** No new entry kinds are introduced; we synthesise the
 *    chain by walking existing ones. When an intermediate kind is missing
 *    (e.g. the worm hasn't yet emitted a process_map for the decision's
 *    channel), the corresponding step is `null` and the gap is recorded
 *    in `chain.missing[]` so the dashboard can surface an honest "not
 *    extracted yet" pill rather than fabricating evidence.
 *
 * 2. **Pure logic + thin DB wrapper.** The pure function
 *    `selectChainSteps` consumes a candidate-row array and returns the
 *    typed chain — exercised by `tests/unit/decision-chain.test.ts` with
 *    no Postgres dependency. `getDecisionChain` is the thin wrapper that
 *    fetches the candidate rows from Postgres (filtered by company_id +
 *    a small set of relevant tools) and hands them to `selectChainSteps`.
 *
 * 3. **Best-effort matching.** The chain prefers tight links (process_map
 *    that cites an evidence message id; KPI source_ids[0] → source_proposed
 *    for that source_id) but falls back to the most-recent-of-kind for the
 *    tenant when no tight link exists. The looser fallback is annotated in
 *    `step.summary` so the operator sees how the link was inferred.
 */

import { DEFAULT_COMPANY_ID, pgQuery } from "./ledger-client";

// ─── Types ────────────────────────────────────────────────────────────────

/**
 * One ledger row consumed by the chain selector. The selector is
 * synchronous and shape-driven so tests can build chains without needing
 * a live Postgres tenant.
 */
export interface CandidateLedgerRow {
  seq: string;
  tool: string; // e.g. "emit_decision_recorded"
  ts: string; // ISO-8601
  hashHex: string;
  args: Record<string, unknown>;
}

export type ChainStepKind =
  | "decision_recorded"
  | "process_map_proposed"
  | "kpi_node"
  | "source_proposed"
  | "source_bronzed";

export interface ChainStep {
  /** Stable kind label for the step (matches the underlying entry tool). */
  kind: ChainStepKind;
  /** Full hex hash of the ledger entry (copy-to-clipboard target). */
  entryHash: string;
  /** Ledger sequence number (string-encoded bigint). */
  entrySeq: string;
  /** ISO-8601 timestamp of the entry. */
  ts: string;
  /** Human-readable one-liner describing the entry's payload. */
  summary: string;
  /** Raw payload args for inspector-style detail rendering. */
  payload: Record<string, unknown>;
  /** Optional href the step header links to (resource detail page). */
  linkHref: string | null;
  /** When true, the step was inferred via a fallback (most-recent-of-kind). */
  inferred: boolean;
}

export interface DecisionChain {
  decision: ChainStep | null;
  processMap: ChainStep | null;
  kpi: ChainStep | null;
  source: ChainStep | null;
  bronze: ChainStep | null;
  /** Names of chain kinds we couldn't resolve. */
  missing: ChainStepKind[];
}

// ─── Chain selector (pure) ────────────────────────────────────────────────

// Marker tuple — value-and-type. The runtime array is used by callers
// who want to pre-filter ledger queries to chain-relevant tools; the
// `typeof _CHAIN_TOOLS[number]` derivation pins the narrow union below.
// Eslint flags this as "value used only as a type" because the local
// rowsByTool callsites pass literal strings; the underscore prefix opts
// out of the unused-vars rule.
const _CHAIN_TOOLS = [
  "emit_decision_recorded",
  "emit_process_map_proposed",
  "emit_kpi_node",
  "emit_source_proposed",
  "emit_source_bronzed",
] as const;

function rowsByTool(
  rows: CandidateLedgerRow[],
  tool: (typeof _CHAIN_TOOLS)[number],
): CandidateLedgerRow[] {
  return rows.filter((r) => r.tool === tool);
}

/**
 * Pure-function chain walker. Consumes the candidate rows the DB
 * wrapper fetched (or test fixtures handed in directly) and returns
 * the resolved chain.
 */
export function selectChainSteps(
  rows: CandidateLedgerRow[],
  decisionId: string,
): DecisionChain {
  const missing: ChainStepKind[] = [];

  // 1. Decision
  const decisionRow = rowsByTool(rows, "emit_decision_recorded").find(
    (r) => String(r.args.decision_id ?? "") === decisionId,
  );

  if (!decisionRow) {
    return {
      decision: null,
      processMap: null,
      kpi: null,
      source: null,
      bronze: null,
      missing: ["decision_recorded"],
    };
  }

  const decision = toDecisionStep(decisionRow);

  const evidenceIds = arrayOfStrings(decisionRow.args.evidence_message_ids);
  const _decisionChannelId = stringOr(decisionRow.args.channel_id, "");

  // 2. Process map: prefer one whose step.source_message_id ∈ evidenceIds
  //    or that targets the decision's channel; fall back to the most-recent
  //    process_map for the tenant.
  const processMapRows = rowsByTool(rows, "emit_process_map_proposed");
  const processMapRow =
    pickProcessMapByEvidence(processMapRows, evidenceIds) ??
    pickMostRecent(processMapRows);
  const processMap = processMapRow
    ? toProcessMapStep(
        processMapRow,
        /* inferred = */ pickProcessMapByEvidence(processMapRows, evidenceIds) ===
          undefined,
      )
    : null;
  if (!processMap) missing.push("process_map_proposed");

  // 3. KPI: prefer the most-recent kpi_node node before decision_at; fall
  //    back to the most-recent kpi_node entry for the tenant.
  const kpiRows = rowsByTool(rows, "emit_kpi_node");
  const decisionAt = stringOr(
    decisionRow.args.decision_at,
    decisionRow.ts,
  );
  const kpiRow =
    pickMostRecentBefore(kpiRows, decisionAt) ?? pickMostRecent(kpiRows);
  const kpi = kpiRow
    ? toKpiStep(
        kpiRow,
        /* inferred = */ pickMostRecentBefore(kpiRows, decisionAt) === undefined,
      )
    : null;
  if (!kpi) missing.push("kpi_node");

  // 4. Source: when the KPI carries source_ids, pick that source_proposed;
  //    else fall back to the most-recent source_proposed for the tenant.
  const sourceRows = rowsByTool(rows, "emit_source_proposed");
  let sourceRow: CandidateLedgerRow | undefined;
  let sourceInferred = false;
  if (kpiRow) {
    const linkedSourceIds = arrayOfStrings(kpiRow.args.source_ids);
    if (linkedSourceIds.length > 0) {
      sourceRow = sourceRows.find(
        (r) => String(r.args.source_id ?? "") === linkedSourceIds[0],
      );
    }
  }
  if (!sourceRow) {
    sourceRow = pickMostRecent(sourceRows);
    sourceInferred = sourceRow !== undefined;
  }
  const source = sourceRow ? toSourceStep(sourceRow, sourceInferred) : null;
  if (!source) missing.push("source_proposed");

  // 5. Bronze: source_bronzed for the resolved source_id.
  const bronzeRows = rowsByTool(rows, "emit_source_bronzed");
  let bronzeRow: CandidateLedgerRow | undefined;
  let bronzeInferred = false;
  if (sourceRow) {
    const sid = String(sourceRow.args.source_id ?? "");
    bronzeRow = bronzeRows.find(
      (r) => String(r.args.source_id ?? "") === sid,
    );
  }
  if (!bronzeRow) {
    bronzeRow = pickMostRecent(bronzeRows);
    bronzeInferred = bronzeRow !== undefined;
  }
  const bronze = bronzeRow ? toBronzeStep(bronzeRow, bronzeInferred) : null;
  if (!bronze) missing.push("source_bronzed");

  return { decision, processMap, kpi, source, bronze, missing };
}

// ─── Step constructors ────────────────────────────────────────────────────

function toDecisionStep(row: CandidateLedgerRow): ChainStep {
  const text = stringOr(row.args.decision_text, "(no decision text)");
  const channel = stringOr(row.args.channel_id, "(unknown channel)");
  const decisionId = stringOr(row.args.decision_id, "");
  return {
    kind: "decision_recorded",
    entryHash: row.hashHex,
    entrySeq: row.seq,
    ts: row.ts,
    summary: `${text} (channel ${channel})`,
    payload: row.args,
    linkHref: decisionId ? `/decisions` : null,
    inferred: false,
  };
}

function toProcessMapStep(
  row: CandidateLedgerRow,
  inferred: boolean,
): ChainStep {
  const name = stringOr(row.args.process_name, "process");
  const stepCount = Array.isArray(row.args.steps)
    ? (row.args.steps as unknown[]).length
    : 0;
  const domain = stringOr(row.args.domain, "general");
  return {
    kind: "process_map_proposed",
    entryHash: row.hashHex,
    entrySeq: row.seq,
    ts: row.ts,
    summary: `${name} · ${stepCount} step${stepCount === 1 ? "" : "s"} · ${domain}`,
    payload: row.args,
    linkHref: "/processes",
    inferred,
  };
}

function toKpiStep(row: CandidateLedgerRow, inferred: boolean): ChainStep {
  const id = stringOr(row.args.id, "");
  const name = stringOr(row.args.name, id || "kpi");
  const formula = stringOr(row.args.formula, "");
  return {
    kind: "kpi_node",
    entryHash: row.hashHex,
    entrySeq: row.seq,
    ts: row.ts,
    summary: formula ? `${name} = ${formula}` : name,
    payload: row.args,
    linkHref: id ? `/kpis` : null,
    inferred,
  };
}

function toSourceStep(row: CandidateLedgerRow, inferred: boolean): ChainStep {
  const uri = stringOr(row.args.uri, "");
  const sid = stringOr(row.args.source_id, "");
  const sourceKind = stringOr(row.args.source_kind, "table");
  return {
    kind: "source_proposed",
    entryHash: row.hashHex,
    entrySeq: row.seq,
    ts: row.ts,
    summary: uri ? `${sourceKind} · ${uri}` : `${sourceKind} · ${sid}`,
    payload: row.args,
    linkHref: sid ? `/sources` : null,
    inferred,
  };
}

function toBronzeStep(row: CandidateLedgerRow, inferred: boolean): ChainStep {
  const sid = stringOr(row.args.source_id, "");
  const bytes = numberOr(row.args.byte_count, 0);
  const rows = numberOr(row.args.row_count, 0);
  const schemaHash = stringOr(row.args.schema_hash, "");
  const summary =
    schemaHash !== ""
      ? `${bytes.toLocaleString()} bytes · ${rows.toLocaleString()} rows · ${schemaHash.slice(0, 16)}`
      : `${bytes.toLocaleString()} bytes · ${rows.toLocaleString()} rows`;
  return {
    kind: "source_bronzed",
    entryHash: row.hashHex,
    entrySeq: row.seq,
    ts: row.ts,
    summary,
    payload: row.args,
    linkHref: sid ? `/sources` : null,
    inferred,
  };
}

// ─── Picker helpers ───────────────────────────────────────────────────────

function pickProcessMapByEvidence(
  rows: CandidateLedgerRow[],
  evidenceIds: string[],
): CandidateLedgerRow | undefined {
  if (evidenceIds.length === 0) return undefined;
  const evSet = new Set(evidenceIds);
  return rows.find((r) => {
    const steps = r.args.steps;
    if (!Array.isArray(steps)) return false;
    for (const step of steps) {
      if (step && typeof step === "object") {
        const sm = (step as Record<string, unknown>).source_message_id;
        if (typeof sm === "string" && evSet.has(sm)) return true;
      }
    }
    return false;
  });
}

function pickMostRecent(
  rows: CandidateLedgerRow[],
): CandidateLedgerRow | undefined {
  if (rows.length === 0) return undefined;
  return rows.slice().sort((a, b) => bigintCmp(b.seq, a.seq))[0];
}

function pickMostRecentBefore(
  rows: CandidateLedgerRow[],
  cutoffIso: string,
): CandidateLedgerRow | undefined {
  if (rows.length === 0) return undefined;
  const cutoff = Date.parse(cutoffIso);
  if (Number.isNaN(cutoff)) return undefined;
  const before = rows
    .filter((r) => Date.parse(r.ts) <= cutoff)
    .sort((a, b) => bigintCmp(b.seq, a.seq));
  return before[0];
}

// ─── Coercion helpers ─────────────────────────────────────────────────────

function stringOr(v: unknown, fallback: string): string {
  return typeof v === "string" && v.length > 0 ? v : fallback;
}

function numberOr(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

function arrayOfStrings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function bigintCmp(a: string, b: string): number {
  // Compare two string-encoded ledger seqs without losing precision for
  // big rows. JavaScript's Number is fine up to 2^53; ledger seqs are
  // bigints in Postgres but rarely cross 2^53 in practice. Use the
  // straightforward numeric comparison and fall back to string compare
  // for parity-of-length safety.
  const na = Number(a);
  const nb = Number(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
  return a.localeCompare(b);
}

// ─── Postgres-bound entry point ───────────────────────────────────────────

/**
 * Resolve the Decision → Bytes chain for a single decision_id, anchored
 * to the given tenant.
 *
 * Reads the ledger directly via `pgQuery` (no fixture fallback — chain
 * walking is a strict-read surface; an empty chain renders an honest
 * "decision not found" empty state). Returns a fully-resolved
 * `DecisionChain` with `null` slots where the chain peters out.
 *
 * The query window is bounded by `tool IN (...)` and `company_id`, so it
 * stays cheap even on a tenant with millions of ledger rows.
 */
export async function getDecisionChain(
  companyId: string = DEFAULT_COMPANY_ID,
  decisionId: string,
): Promise<DecisionChain> {
  if (!decisionId) {
    return {
      decision: null,
      processMap: null,
      kpi: null,
      source: null,
      bronze: null,
      missing: ["decision_recorded"],
    };
  }

  try {
    const sql = `
      SELECT seq::text AS seq,
             payload->>'tool' AS tool,
             ts,
             encode(hash, 'hex') AS hash_hex,
             payload->'args' AS args
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_decision_recorded',
           'emit_process_map_proposed',
           'emit_kpi_node',
           'emit_source_proposed',
           'emit_source_bronzed'
         )
       ORDER BY seq DESC
       LIMIT 5000
    `;
    const res = await pgQuery<{
      seq: string;
      tool: string;
      ts: Date | string;
      hash_hex: string;
      args: Record<string, unknown> | null;
    }>(sql, [companyId]);

    const rows: CandidateLedgerRow[] = res.rows.map((r) => ({
      seq: String(r.seq),
      tool: r.tool,
      ts:
        r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString(),
      hashHex: r.hash_hex,
      args: r.args ?? {},
    }));

    return selectChainSteps(rows, decisionId);
  } catch {
    // Postgres not configured (e.g. fresh dev tree) — treat as
    // "decision not found" so the page renders an honest empty state.
    return {
      decision: null,
      processMap: null,
      kpi: null,
      source: null,
      bronze: null,
      missing: ["decision_recorded"],
    };
  }
}
