/**
 * Ledger read-side client.
 *
 * Strategy: try Postgres first (when DATABASE_URL is set and the ledger schema
 * is populated by worm-core reactivity / channel-adapter wire). On any failure
 * — connection refused, schema not yet present, empty result set — return an
 * honest empty value (`[]` for arrays, `null` for single objects). Each
 * dashboard page's empty state then surfaces meaningful first-day affordances
 * (drop a file in your worm channel, paste a credential in DM, add source)
 * rather than rendering pre-baked fixture rows that lie about tenant state.
 *
 * Two exceptions are preserved:
 *
 *   - `getOntologySeeds` returns the canonical concept list shipped with
 *     WormBase (revenue, MRR, churn, etc.). That's static product config,
 *     not tenant state — the seed pack lives in
 *     `packages/ontology-seed/`.
 *   - `getTraceEntries` keeps an internal `fixturePage()` derived from
 *     `TRACE_ENTRIES`. The /trace surface is the live append-only ledger
 *     view; we still surface a populated fallback there because an empty
 *     /trace would obscure the sample-of-truth pattern this surface
 *     teaches. Workstream 3 will revisit /trace specifically.
 *
 * Each function returns rows that already include their `receipt` field; the
 * caller never has to synthesize one.
 */

import type { Pool, PoolClient, QueryResult } from "pg";
import {
  BASEWORM_COMPANY_UUID,
  ONTOLOGY_SEEDS,
  TRACE_ENTRIES,
} from "./demo-fixture";
import { listKnownTenantsSync } from "./tenants";

import type {
  BusinessDefProposal,
  ChannelRow,
  ConversationMessage,
  ConversationSyncRow,
  ConversationSyncStatus,
  ConversationSyncTrigger,
  DecisionRow,
  DomainRow,
  ExperimentOutcome,
  ExperimentRow,
  CompositeScorePoint,
  CompositeScoreSeries,
  HeadlineMetricSeries,
  InsightCard,
  KeepRateSample,
  KeepRateScope,
  KpiNodeRow,
  LedgerQuadrant,
  MaintenanceSignal,
  MaintenanceSignalKind,
  MetricSamplePoint,
  OnboardingMilestones,
  OntologySeed,
  PersonIdentityDetailRow,
  PersonIdentityRow,
  PersonRoleGrant,
  PersonRow,
  PiiPattern,
  PolicyAppliedEvent,
  PolicyRow,
  PositionMover,
  PositionRegistryRow,
  ProcessMapRow,
  ProcessStep,
  RampGaugeRow,
  Receipt,
  RecurringQuestionRow,
  ResearchOverview,
  SourceFlow,
  SourceRow,
  SystemMapEdge,
  SystemMapNode,
  SystemMapPayload,
  TaskRow,
  Talkativeness,
  TenancyRole,
  TraceCursor,
  TraceEntryRow,
  TracePage,
  InstallRow,
  InstallSummary,
  DataProductRow,
  DataProductRunRow,
  DataProductConsumptionRow,
  NotebookRow,
  NotebookRunRow,
  NotebookCell,
  McpCallRow,
  McpCallOutcome,
  McpCatalog,
  Reactivity,
  ReactivityFire,
  ResearchAudience,
  ResourceConversation,
  ExperimentLessonRow,
  LessonScope,
  FirstKnowingChatRow,
  FirstKnowingPhenomenonKind,
  FirstKnowingRecency,
  FirstKnowingRow,
  FirstKnowingScope,
  KnowledgeRampAxis,
  KnowledgeRampGaugeRow,
  KnowledgeRampGaugesPayload,
} from "./ledger-client.types";
import type { PlatformSlug } from "./platform-status";

export const DEFAULT_COMPANY_ID = BASEWORM_COMPANY_UUID;

/**
 * Postgres availability check. Postgres is the production source of truth;
 * if DATABASE_URL is set we try it first. When DATABASE_URL is unset (e.g.
 * a freshly cloned dev tree before docker-compose up) the dashboard falls
 * back to the curated fixture so every surface still renders with
 * Receipts during local iteration.
 */
function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

/**
 * Lazily-initialized singleton Pool. We avoid eager import of `pg` so SSR-time
 * errors during `next dev` don't cascade when DATABASE_URL is absent.
 */
let _poolPromise: Promise<Pool | null> | null = null;
const _warnedClasses = new Set<string>();

function warnOnce(klass: string, msg: string): void {
  if (_warnedClasses.has(klass)) return;
  _warnedClasses.add(klass);
  if (process.env.NODE_ENV !== "production") {
    console.warn(`[ledger-client] ${msg}`);
  }
}

async function getPool(): Promise<Pool | null> {
  if (!postgresEnabled()) return null;
  if (_poolPromise) return _poolPromise;
  _poolPromise = (async () => {
    try {
      // Literal `import("pg")` so webpack can statically resolve. The
      // module is kept out of the SSR bundle via
      // `serverExternalPackages: ["pg"]` in next.config.mjs so Next won't
      // try to bundle pg's native bindings — runtime resolution from
      // node_modules is what we want.
      let pg: typeof import("pg") | null = null;
      try {
        pg = await import("pg");
      } catch (err) {
        warnOnce(
          "pg-import",
          `pg import failed (${(err as Error).message}); using fixtures`,
        );
        return null;
      }
      const PoolCtor = (pg.default ?? pg).Pool;
      const pool: Pool = new PoolCtor({
        connectionString:
          process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN,
        ssl: false, // docker-compose internal network
        max: 4,
        idleTimeoutMillis: 30_000,
      });
      // Surface pool-level errors but don't crash the dashboard.
      pool.on("error", (err: Error) => {
        warnOnce(`pool-error:${err.name}`, `pool error: ${err.message}`);
      });
      return pool;
    } catch (err) {
      warnOnce(
        `pool-init:${(err as Error).name}`,
        `pool init failed: ${(err as Error).message}`
      );
      return null;
    }
  })();
  return _poolPromise;
}

/**
 * Try Postgres first; fall back to the provided fixture on any error.
 *
 * Server-side only. The dashboard is mostly RSC — these functions get called
 * from server components. Client components receive plain JSON via props.
 *
 * Errors are deduped per error class via a Set so a flapping connection
 * doesn't spam the logs.
 */
async function tryPg<T>(query: () => Promise<T>, fallback: T): Promise<T> {
  if (!postgresEnabled()) return fallback;
  const pool = await getPool();
  if (!pool) return fallback;
  try {
    return await query();
  } catch (err) {
    const e = err as Error;
    warnOnce(
      `query:${e.name}:${e.message.slice(0, 40)}`,
      `Postgres path failed, falling back to fixture: ${e.message}`
    );
    return fallback;
  }
}

/**
 * Run a parameterized SQL query against the singleton pool. Caller is
 * responsible for handling errors (tryPg wraps that for read accessors).
 *
 * Exported for ``lib/server/install.ts`` so the install helper can
 * persist KMS-wrapped or vault-stored bot tokens to a side-table
 * without coupling to ledger-client internals. Server-only consumers.
 */
export async function pgQuery<R extends Record<string, unknown>>(
  sql: string,
  params: unknown[]
): Promise<QueryResult<R>> {
  const pool = await getPool();
  if (!pool) throw new Error("postgres pool unavailable");
  const client: PoolClient = await pool.connect();
  try {
    return (await client.query(sql, params)) as QueryResult<R>;
  } finally {
    client.release();
  }
}

// ─── Reads ───────────────────────────────────────────────────────────────

/**
 * Six-axis knowledge ramp.
 *
 * Live source: the latest `emit_memory_written` execute entry whose
 * `args.content == "ramp_snapshot"`. KnowledgeRamp.compute() in worm-core
 * writes one of these every time the ramp recomputes; the dashboard reads
 * the most-recent snapshot per company. Values come back as 0..100 floats
 * keyed by axis name in `args.values`.
 *
 * Returns `[]` when no snapshot has been written yet — the dashboard renders
 * an honest "the worm hasn't moved any axes yet" empty state instead of a
 * pre-baked fixture that lies about ramp state.
 */
const RAMP_AXIS_LABELS: Record<RampGaugeRow["axis"], string> = {
  ontology: "Ontology",
  schema: "Schema",
  business_definitions: "Business Definitions",
  kpi_relational: "KPI Relational",
  conversational: "Conversational",
  operational: "Operational",
};

const RAMP_AXIS_HINTS: Record<RampGaugeRow["axis"], string> = {
  ontology: "concepts confirmed against the seed ontology",
  schema: "tables profiled / tables connected",
  business_definitions: "tier-2 confirmations / templates",
  kpi_relational: "tree nodes resolved / leaves required",
  conversational: "channel listen coverage",
  operational: "policies active / policies templated",
};

const RAMP_AXIS_ORDER: ReadonlyArray<RampGaugeRow["axis"]> = [
  "ontology",
  "schema",
  "business_definitions",
  "kpi_relational",
  "conversational",
  "operational",
];

export async function getRampValues(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<RampGaugeRow[]> {
  return tryPg(async () => {
    // Latest ramp snapshot per company. The KnowledgeRamp writer stores the
    // 6-axis values in payload.args.values and a deterministic snapshot hash
    // in args.snapshot_hash; we read both and map each axis into the
    // dashboard's RampGaugeRow shape.
    const sql = `
      SELECT ts,
             encode(hash, 'hex') AS hash_hex,
             payload->'args'->'values'         AS values,
             payload->'args'->>'snapshot_hash' AS snapshot_hash
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_memory_written'
         AND payload->'args'->>'content' = 'ramp_snapshot'
       ORDER BY seq DESC
       LIMIT 1
    `;
    const res = await pgQuery<{
      ts: Date | string;
      hash_hex: string;
      values: Record<string, number> | null;
      snapshot_hash: string | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0 || !res.rows[0].values) {
      return [];
    }

    const row = res.rows[0];
    const values = row.values ?? {};
    const updatedAt =
      row.ts instanceof Date ? row.ts.toISOString() : new Date(row.ts).toISOString();
    const baseHash = (row.snapshot_hash ?? row.hash_hex).slice(0, 12);

    return RAMP_AXIS_ORDER.map((axis) => {
      const raw = values[axis];
      const value = typeof raw === "number" && Number.isFinite(raw)
        ? Math.max(0, Math.min(100, Math.round(raw)))
        : 0;
      return {
        axis,
        label: RAMP_AXIS_LABELS[axis],
        value,
        hint: RAMP_AXIS_HINTS[axis],
        receipt: {
          hash: baseHash,
          source: "ramp-projection",
          owner: "system",
          classification: "internal",
        },
        updatedAt,
      };
    });
  }, []);
}

// ─── Knowledge-ramp counter gauges (Demo-day P2) ─────────────────────────

/**
 * Three integer-counted gauges + 60-bucket sparklines, mirroring the
 * canonical projection at
 * ``apps/worm-core/src/wormbase_core/projections/knowledge_ramp.py``.
 *
 * SQL fold lives here so the dashboard can serve the gauge tile without
 * round-tripping to worm-core. The Python projection is the spec; the
 * TS fold is the read-side. Both share their tests via the same input
 * row-stream contract.
 *
 * Empty-state rule (PRD §7 P2): an axis with zero contributing entries
 * returns ``count: 0`` with a zero-vector sparkline. The dashboard
 * renders the count + a hint string honestly; never a fixture.
 */

const KNOWLEDGE_RAMP_AXIS_LABEL: Record<KnowledgeRampAxis, string> = {
  ontology: "Ontology",
  conversational: "Conversational",
  relational: "Relational",
};

const KNOWLEDGE_RAMP_EMPTY_HINT: Record<KnowledgeRampAxis, string> = {
  ontology:
    "no concepts confirmed yet · the worm coins one when chatter names a recurring term",
  conversational:
    "no chat captured yet · invite the worm into a channel to start mining",
  relational:
    "no KPI tree growth yet · drop a metric in chat or run /kpis to seed the first node",
};

const KNOWLEDGE_RAMP_POPULATED_HINT: Record<KnowledgeRampAxis, string> = {
  ontology: "concepts proposed + confirmed across the seed ontology",
  conversational: "messages captured from connected channels",
  relational: "KPI nodes + edges threaded into the tree",
};

const KNOWLEDGE_RAMP_TRACE_FILTER: Record<KnowledgeRampAxis, string> = {
  ontology: "concept_",
  conversational: "chat_received",
  relational: "kpi_",
};

const KNOWLEDGE_RAMP_AXIS_ORDER: ReadonlyArray<KnowledgeRampAxis> = [
  "ontology",
  "conversational",
  "relational",
];

/** Sparkline window mirrors the Python projection: 60 minutes, 60 buckets. */
const KNOWLEDGE_RAMP_SPARKLINE_WINDOW_S = 60 * 60;
const KNOWLEDGE_RAMP_SPARKLINE_BUCKETS = 60;
const KNOWLEDGE_RAMP_SPARKLINE_MAX_ENTRIES = 100;

/** Postgres LIKE patterns for each axis's contributing rows. */
const KNOWLEDGE_RAMP_KIND_PREDICATE: Record<KnowledgeRampAxis, string> = {
  // ontology: kind='concept_proposed'/'concept_confirmed' OR
  // execute+tool LIKE 'emit_concept_%'
  ontology: `(kind IN ('concept_proposed','concept_confirmed') OR (kind = 'execute' AND payload->>'tool' IN ('emit_concept_proposed','emit_concept_confirmed','emit_concept_emitted')))`,
  // conversational: kind='chat_received' OR execute+tool ILIKE '%chat_received'
  conversational: `(kind = 'chat_received' OR (kind = 'execute' AND payload->>'tool' IN ('emit_chat_received','channel_adapter.emit_chat_received')))`,
  // relational: kind='kpi_proposed' OR execute+tool starts with 'emit_kpi_'
  relational: `(kind IN ('kpi_proposed') OR (kind = 'execute' AND payload->>'tool' LIKE 'emit_kpi_%'))`,
};

function buildEmptyGauge(axis: KnowledgeRampAxis): KnowledgeRampGaugeRow {
  return {
    axis,
    label: KNOWLEDGE_RAMP_AXIS_LABEL[axis],
    count: 0,
    sparkline: new Array(KNOWLEDGE_RAMP_SPARKLINE_BUCKETS).fill(0),
    emptyHint: KNOWLEDGE_RAMP_EMPTY_HINT[axis],
    populatedHint: KNOWLEDGE_RAMP_POPULATED_HINT[axis],
    traceFilter: KNOWLEDGE_RAMP_TRACE_FILTER[axis],
    lastSeq: 0,
    lastTs: null,
  };
}

function emptyKnowledgeRampPayload(): KnowledgeRampGaugesPayload {
  return {
    computedAt: new Date().toISOString(),
    windowSeconds: KNOWLEDGE_RAMP_SPARKLINE_WINDOW_S,
    gauges: KNOWLEDGE_RAMP_AXIS_ORDER.map(buildEmptyGauge),
  };
}

interface KnowledgeRampSqlRow extends Record<string, unknown> {
  seq: string | number;
  ts: Date | string;
}

async function foldKnowledgeRampAxis(
  companyId: string,
  axis: KnowledgeRampAxis,
  now: Date,
): Promise<KnowledgeRampGaugeRow> {
  // Two queries: cumulative count + last-row metadata, then most-recent
  // SPARKLINE_MAX_ENTRIES rows in the trailing 60-min window for the
  // sparkline. Each query is tenant-scoped and predicate-bounded; the
  // ``payload`` jsonb path is indexed in production via the standard
  // ledger projections.
  const predicate = KNOWLEDGE_RAMP_KIND_PREDICATE[axis];

  // 1) cumulative count + most-recent contributing seq + ts
  const summarySql = `
    SELECT
      COUNT(*)::bigint AS total,
      COALESCE(MAX(seq), 0)::bigint AS last_seq,
      MAX(ts) AS last_ts
    FROM ledger
    WHERE company_id = $1
      AND ${predicate}
  `;
  const summary = await pgQuery<{
    total: string | number;
    last_seq: string | number;
    last_ts: Date | string | null;
  }>(summarySql, [companyId]);

  const total = Number(summary.rows[0]?.total ?? 0);
  if (!Number.isFinite(total) || total <= 0) {
    return buildEmptyGauge(axis);
  }
  const lastSeq = Number(summary.rows[0]?.last_seq ?? 0);
  const lastTsRaw = summary.rows[0]?.last_ts ?? null;
  const lastTs = lastTsRaw
    ? lastTsRaw instanceof Date
      ? lastTsRaw.toISOString()
      : new Date(lastTsRaw).toISOString()
    : null;

  // 2) recent contributing rows for sparkline; capped by entries AND window.
  const windowStartIso = new Date(
    now.getTime() - KNOWLEDGE_RAMP_SPARKLINE_WINDOW_S * 1000,
  ).toISOString();
  const recentSql = `
    SELECT seq, ts
    FROM ledger
    WHERE company_id = $1
      AND ${predicate}
      AND ts >= $2::timestamptz
    ORDER BY seq DESC
    LIMIT $3
  `;
  const recent = await pgQuery<KnowledgeRampSqlRow>(recentSql, [
    companyId,
    windowStartIso,
    KNOWLEDGE_RAMP_SPARKLINE_MAX_ENTRIES,
  ]);

  const sparkline = new Array<number>(KNOWLEDGE_RAMP_SPARKLINE_BUCKETS).fill(0);
  for (const row of recent.rows) {
    const ts = row.ts instanceof Date ? row.ts : new Date(row.ts);
    const deltaMs = now.getTime() - ts.getTime();
    if (deltaMs < 0) {
      sparkline[KNOWLEDGE_RAMP_SPARKLINE_BUCKETS - 1] += 1;
      continue;
    }
    if (deltaMs >= KNOWLEDGE_RAMP_SPARKLINE_WINDOW_S * 1000) continue;
    const minutesOld = Math.floor(deltaMs / 60_000);
    const idx = Math.max(
      0,
      Math.min(
        KNOWLEDGE_RAMP_SPARKLINE_BUCKETS - 1,
        KNOWLEDGE_RAMP_SPARKLINE_BUCKETS - 1 - minutesOld,
      ),
    );
    sparkline[idx] += 1;
  }

  return {
    axis,
    label: KNOWLEDGE_RAMP_AXIS_LABEL[axis],
    count: total,
    sparkline,
    emptyHint: KNOWLEDGE_RAMP_EMPTY_HINT[axis],
    populatedHint: KNOWLEDGE_RAMP_POPULATED_HINT[axis],
    traceFilter: KNOWLEDGE_RAMP_TRACE_FILTER[axis],
    lastSeq,
    lastTs,
  };
}

export async function getKnowledgeRampGauges(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<KnowledgeRampGaugesPayload> {
  const fallback = emptyKnowledgeRampPayload();
  return tryPg(async () => {
    const now = new Date();
    const gauges = await Promise.all(
      KNOWLEDGE_RAMP_AXIS_ORDER.map((axis) =>
        foldKnowledgeRampAxis(companyId, axis, now),
      ),
    );
    return {
      computedAt: now.toISOString(),
      windowSeconds: KNOWLEDGE_RAMP_SPARKLINE_WINDOW_S,
      gauges,
    };
  }, fallback);
}

/**
 * KPI tree.
 *
 * Live source: every `emit_kpi_node` execute entry contributes one node to
 * the tree. We collect them per `id`, then re-shape into the dashboard's
 * nested KpiNodeRow form using `parent_node_id` to thread children.
 *
 * Returns `null` when no kpi_node entries exist for the tenant — the
 * /kpis page renders an honest empty state inviting the worm to propose
 * the first KPI from chatter rather than showing fixture rows.
 */
interface KpiNodeArgs {
  id: string;
  name?: string;
  parent_node_id?: string | null;
  source_resource_id?: string | null;
  metric_type?: string;
  confidence?: string | number | null;
  classification?: string;
  owner_person_id?: string | null;
}

export async function getKpiTree(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<KpiNodeRow | null> {
  return tryPg<KpiNodeRow | null>(async () => {
    const sql = `
      SELECT DISTINCT ON (payload->'args'->>'id')
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_kpi_node'
         AND payload->'args'->>'id' IS NOT NULL
       ORDER BY payload->'args'->>'id', seq DESC
    `;
    const res = await pgQuery<{
      args: KpiNodeArgs;
      hash_hex: string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return null;

    const byId = new Map<string, KpiNodeRow>();
    const parentOf = new Map<string, string | null>();
    for (const r of res.rows) {
      const a = r.args ?? ({} as KpiNodeArgs);
      const id = String(a.id);
      const classification =
        (typeof a.classification === "string" && a.classification) ||
        "internal";
      const confidenceRaw =
        typeof a.confidence === "number"
          ? a.confidence
          : typeof a.confidence === "string"
            ? Number(a.confidence)
            : NaN;
      const confidence = Number.isFinite(confidenceRaw)
        ? Math.max(0, Math.min(1, confidenceRaw))
        : 0.5;
      const sourceRef =
        (typeof a.source_resource_id === "string" && a.source_resource_id) ||
        "kpi-tree";
      const owner =
        (typeof a.owner_person_id === "string" && a.owner_person_id) || "system";
      byId.set(id, {
        id,
        label: a.name ?? id,
        owner,
        classification,
        confidence,
        hasChildren: false,
        children: [],
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: sourceRef,
          owner,
          classification,
        },
      });
      parentOf.set(id, a.parent_node_id ?? null);
    }

    // Wire children.
    for (const [id, parentId] of parentOf.entries()) {
      if (parentId && byId.has(parentId)) {
        const child = byId.get(id)!;
        const parent = byId.get(parentId)!;
        parent.children.push(child);
        parent.hasChildren = true;
      }
    }

    // Find the root: a node whose parent_node_id is null/unknown. If the
    // ledger contains multiple roots, synthesize a wrapper so the dashboard
    // still gets a single tree.
    const roots: KpiNodeRow[] = [];
    for (const [id, parentId] of parentOf.entries()) {
      if (!parentId || !byId.has(parentId)) {
        const node = byId.get(id);
        if (node) roots.push(node);
      }
    }
    if (roots.length === 1) return roots[0];
    if (roots.length === 0) return null;

    // Multiple roots — wrap in a synthetic parent so the page still renders.
    return {
      id: "kpi_root",
      label: "KPI tree",
      owner: "system",
      classification: "internal",
      confidence: 1,
      hasChildren: true,
      children: roots,
      receipt: {
        hash: "kpi_tree_root",
        source: "kpi-tree",
        owner: "system",
        classification: "internal",
      },
    };
  }, null);
}

/**
 * Apply the in-memory filter set shared by the fixture and Postgres paths
 * of `getTraceEntries`. Centralised so /trace's URL-driven filters
 * (W2.A10) and the existing source/kpi cross-links share one
 * implementation. All filters AND together.
 */
function applyTraceFilters(
  entries: TraceEntryRow[],
  opts: TraceCursor,
): TraceEntryRow[] {
  let out = entries;
  if (opts.forSourceId) {
    out = out.filter((e) =>
      String(e.payload?.summary ?? "").includes(opts.forSourceId!) ||
      e.receipt.source.includes(opts.forSourceId!)
    );
  }
  if (opts.forKpiId) {
    out = out.filter((e) =>
      String(e.payload?.summary ?? "")
        .toLowerCase()
        .includes(opts.forKpiId!.toLowerCase())
    );
  }
  if (opts.quadrant) {
    out = out.filter((e) => e.quadrant === opts.quadrant);
  }
  if (opts.kind) {
    const k = opts.kind.toLowerCase();
    out = out.filter(
      (e) =>
        String(e.kind).toLowerCase().includes(k) ||
        e.quadrant.toLowerCase() === k,
    );
  }
  if (opts.personId) {
    const pid = opts.personId;
    out = out.filter((e) => {
      const payload = (e.payload ?? {}) as Record<string, unknown>;
      const args =
        (payload.args && typeof payload.args === "object"
          ? (payload.args as Record<string, unknown>)
          : {}) as Record<string, unknown>;
      const candidates = [
        payload.actor,
        args.person_id,
        args.added_by_person,
        args.confirmed_by_person,
        args.proposed_by,
        args.granted_by,
      ];
      return candidates.some((v) => typeof v === "string" && v === pid);
    });
  }
  if (opts.channelId) {
    const cid = opts.channelId;
    out = out.filter((e) => {
      const payload = (e.payload ?? {}) as Record<string, unknown>;
      const args =
        (payload.args && typeof payload.args === "object"
          ? (payload.args as Record<string, unknown>)
          : {}) as Record<string, unknown>;
      return (
        (typeof args.channel_id === "string" && args.channel_id === cid) ||
        e.receipt.source === cid
      );
    });
  }
  if (opts.tsFrom) {
    const fromMs = Date.parse(opts.tsFrom);
    if (!Number.isNaN(fromMs)) {
      out = out.filter((e) => Date.parse(e.ts) >= fromMs);
    }
  }
  if (opts.tsTo) {
    const toMs = Date.parse(opts.tsTo);
    if (!Number.isNaN(toMs)) {
      out = out.filter((e) => Date.parse(e.ts) <= toMs);
    }
  }
  return out;
}

export async function getTraceEntries(
  companyId: string = DEFAULT_COMPANY_ID,
  opts: TraceCursor = {}
): Promise<TracePage> {
  const requested = opts.limit ?? 50;
  const limit = Math.min(Math.max(requested, 1), 200);

  // Fixture path (also used as fallback) — preserves the existing filter
  // semantics for forSourceId / forKpiId / quadrant that the route exercises.
  const fixturePage = (): TracePage => {
    const filtered = applyTraceFilters(
      TRACE_ENTRIES.slice().reverse(), // newest first
      opts,
    );
    const start = opts.cursor ? Number(opts.cursor) : 0;
    const slice = filtered.slice(start, start + limit);
    const nextCursor =
      start + limit < filtered.length ? String(start + limit) : null;
    return { entries: slice, nextCursor };
  };

  return tryPg(async () => {
    // Cursor here is a `seq` upper-bound (exclusive), since we order DESC.
    const cursorSeq = opts.cursor ? opts.cursor : null;
    const sql = `
      SELECT seq, kind, ts, payload, encode(hash, 'hex') AS hash_hex,
             encode(prev_hash, 'hex') AS prev_hash_hex
        FROM ledger
       WHERE company_id = $1
         AND ($2::bigint IS NULL OR seq < $2)
       ORDER BY seq DESC
       LIMIT $3
    `;
    const res = await pgQuery<{
      seq: string | number;
      kind: string;
      ts: Date | string;
      payload: Record<string, unknown> | null;
      hash_hex: string;
      prev_hash_hex: string | null;
    }>(sql, [companyId, cursorSeq, limit]);

    if (res.rows.length === 0) {
      // No live entries yet — preserve receipt density via fixture.
      return fixturePage();
    }

    const entries = applyTraceFilters(res.rows.map(rowToTraceEntry), opts);

    const nextCursor =
      res.rows.length === limit
        ? String(res.rows[res.rows.length - 1].seq)
        : null;
    return { entries, nextCursor };
  }, fixturePage());
}

/**
 * Map a raw ledger row to the dashboard's TraceEntryRow shape.
 *
 * The ledger schema stores `kind` as one of {propose, execute, verify,
 * resolve} (the four phases of the write primitive) and the entry-type name
 * lives in `payload.tool` for execute steps. The dashboard's TraceEntryRow
 * separates the two: `quadrant` carries the phase, `kind` carries the
 * entry-type name (e.g. `source_proposed`). When `payload.tool` is present
 * we strip the `emit_` prefix; otherwise we synthesize a kind from the
 * SQL `kind`.
 */
function rowToTraceEntry(row: {
  seq: string | number;
  kind: string;
  ts: Date | string;
  payload: Record<string, unknown> | null;
  hash_hex: string;
  prev_hash_hex: string | null;
}): TraceEntryRow {
  const payload = (row.payload ?? {}) as Record<string, unknown>;
  const tool = typeof payload.tool === "string" ? payload.tool : null;
  const args = (payload.args ?? {}) as Record<string, unknown>;

  const quadrant = (
    ["propose", "execute", "verify", "resolve"].includes(row.kind)
      ? (row.kind as LedgerQuadrant)
      : "execute"
  ) as LedgerQuadrant;

  const derivedKind = tool
    ? tool.replace(/^emit_/, "")
    : row.kind;

  const summary =
    typeof payload.summary === "string"
      ? payload.summary
      : deriveSummary(derivedKind, args);

  const classification =
    (typeof args.classification === "string" && args.classification) ||
    (typeof args.suggested_classification === "string" &&
      args.suggested_classification) ||
    "internal";

  const source =
    (typeof args.uri === "string" && args.uri) ||
    (typeof args.channel_id === "string" && args.channel_id) ||
    (typeof args.source_id === "string" && args.source_id) ||
    "ledger";

  const owner =
    (typeof args.confirmed_by_person === "string" && args.confirmed_by_person) ||
    (typeof args.added_by_person === "string" && args.added_by_person) ||
    (typeof payload.actor === "string" && payload.actor) ||
    "system";

  const ts =
    row.ts instanceof Date ? row.ts.toISOString() : new Date(row.ts).toISOString();
  const hashShort = row.hash_hex.slice(0, 12);

  return {
    id: String(row.seq),
    ts,
    kind: derivedKind,
    quadrant,
    hash: hashShort,
    prevHash: row.prev_hash_hex ? row.prev_hash_hex.slice(0, 12) : null,
    payload: { ...payload, summary },
    receipt: {
      hash: hashShort,
      source,
      owner,
      classification,
    },
  };
}

function deriveSummary(
  derivedKind: string,
  args: Record<string, unknown>
): string {
  const uri = typeof args.uri === "string" ? args.uri : null;
  const sid = typeof args.source_id === "string" ? args.source_id : null;
  switch (derivedKind) {
    case "source_proposed":
      return `Source proposed: ${uri ?? sid ?? "(unknown)"}`;
    case "source_confirmed":
      return `Source confirmed: ${uri ?? sid ?? "(unknown)"}`;
    case "source_connected":
      return `Source connected: ${uri ?? sid ?? "(unknown)"}`;
    case "source_profiled":
      return `Source profiled: ${uri ?? sid ?? "(unknown)"}`;
    default:
      return derivedKind.replace(/_/g, " ");
  }
}

/**
 * People.
 *
 * Live source (post-A1 + A2): the canonical identity + role ledger entries:
 *   - `emit_person_proposed`     — Person + initial PersonIdentity row
 *   - `emit_person_confirmed`    — admin confirms; status flips proposed → active
 *   - `emit_person_archived`     — admin archives; status → archived
 *   - `emit_identity_linked`     — attach a (platform, platform_user_id) to an existing Person
 *   - `emit_identity_unlinked`   — detach a (platform, platform_user_id) from a Person
 *   - `emit_role_assigned`       — tenancy-facet grant
 *   - `emit_role_revoked`        — revoke a tenancy-facet grant
 *   - `emit_domain_role_assigned`   — domain-facet grant
 *   - `emit_resource_role_assigned` — resource-facet grant
 *
 * Reading strategy: **SQL-fold the ledger directly** — the DB-side
 * `projection_persons` / `projection_roles` tables exist in schema but aren't
 * auto-populated by a worker yet. Until the projection-builder runs as a
 * service (a future task), we fold in JS from the canonical execute entries.
 *
 * **No fixture fallback.** Per PRD §11.1 ("no fixture loads in production
 * paths"), an empty ledger returns `[]`. The fixture is sim-only or
 * replay-only; never production.
 */

interface PersonProposedArgs {
  person_id: string;
  tenant_id?: string;
  name: string;
  email?: string | null;
  platform?: string;
  platform_user_id?: string;
  position?: string | null;
  proposed_by?: string;
}

interface PersonConfirmedArgs {
  person_id: string;
  confirmed_by: string;
}

interface PersonArchivedArgs {
  person_id: string;
  archived_by: string;
  reason?: string;
}

interface IdentityLinkArgs {
  person_id: string;
  platform: string;
  platform_user_id: string;
  linked_by?: string;
  unlinked_by?: string;
}

interface RoleAssignedArgs {
  person_id: string;
  role: string;
  granted_by: string;
}

interface RoleRevokedArgs {
  person_id: string;
  role: string;
  revoked_by: string;
}

interface DomainRoleArgs {
  person_id: string;
  domain_id: string;
  role: string;
  granted_by: string;
}

interface ResourceRoleArgs {
  person_id: string;
  resource_id: string;
  resource_type: string;
  role: string;
  granted_by: string;
}

/** Tenancy role priority: when a Person holds multiple unrevoked tenancy
 *  grants, surface the most-privileged one in `tenancyRole`. */
const TENANCY_ROLE_PRIORITY: Record<TenancyRole, number> = {
  installer: 4,
  admin: 3,
  member: 2,
  observer: 1,
};

function isTenancyRole(s: string): s is TenancyRole {
  return s === "installer" || s === "admin" || s === "member" || s === "observer";
}

/**
 * SQL: read every identity / role ledger row for `companyId` ordered by `seq`.
 * One round-trip; the fold happens in JS.
 */
const PERSON_FOLD_SQL = `
  SELECT seq,
         ts,
         payload->>'tool' AS tool,
         payload->'args' AS args,
         encode(hash, 'hex') AS hash_hex
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_person_proposed',
       'emit_person_confirmed',
       'emit_person_archived',
       'emit_identity_linked',
       'emit_identity_unlinked',
       'emit_role_assigned',
       'emit_role_revoked',
       'emit_domain_role_assigned',
       'emit_resource_role_assigned'
     )
   ORDER BY seq ASC
`;

interface FoldedPersonState {
  personId: string;
  displayName: string;
  email: string | null;
  position: string | null;
  status: "proposed" | "active" | "archived";
  tenancyGrants: Map<TenancyRole, { grantedBy: string; grantedAt: string }>;
  identities: Map<string, PersonIdentityDetailRow>; // key: `${platform}|${platform_user_id}`
  domainGrants: Array<{
    domainId: string;
    role: string;
    grantedBy: string;
    grantedAt: string;
  }>;
  resourceGrants: Array<{
    resourceId: string;
    resourceType: string;
    role: string;
    grantedBy: string;
    grantedAt: string;
  }>;
  /** Last hash that touched this Person — used as receipt source. */
  lastHash: string;
}

interface FoldRow extends Record<string, unknown> {
  seq: number | string;
  ts: Date | string;
  tool: string;
  args: Record<string, unknown>;
  hash_hex: string;
}

/**
 * Fold a stream of ordered ledger rows into per-person state.
 *
 * Pure function — the SQL is the only IO. Tested directly via
 * mocked pg in `tests/lib/ledger-client-people.test.ts`.
 */
function foldPersonRows(rows: FoldRow[]): Map<string, FoldedPersonState> {
  const persons = new Map<string, FoldedPersonState>();

  const tsToIso = (ts: Date | string): string =>
    ts instanceof Date ? ts.toISOString() : new Date(ts).toISOString();

  for (const r of rows) {
    const args = (r.args ?? {}) as Record<string, unknown>;
    const tool = r.tool;
    const hashHex = r.hash_hex;
    const ts = tsToIso(r.ts);

    if (tool === "emit_person_proposed") {
      const a = args as unknown as PersonProposedArgs;
      const pid = a.person_id;
      if (!pid) continue;
      const initialIdentities = new Map<string, PersonIdentityDetailRow>();
      if (a.platform && a.platform_user_id) {
        const key = `${a.platform}|${a.platform_user_id}`;
        initialIdentities.set(key, {
          platform: a.platform,
          platformUserId: a.platform_user_id,
          displayName: a.name ?? null,
          addedAt: ts,
          // D2: persist proposed_by so downstream consumers can render
          // discovery-source groupings without an extra round-trip.
          proposedBy: a.proposed_by ?? null,
        });
      }
      // Latest `emit_person_proposed` wins on collisions (per A1 builder
      // semantics — re-proposal overwrites the metadata).
      persons.set(pid, {
        personId: pid,
        displayName: a.name ?? a.email ?? pid,
        email: a.email ?? null,
        position: a.position ?? null,
        status: "proposed",
        tenancyGrants: persons.get(pid)?.tenancyGrants ?? new Map(),
        identities: persons.get(pid)?.identities
          ? new Map([
              ...Array.from(persons.get(pid)!.identities.entries()),
              ...Array.from(initialIdentities.entries()),
            ])
          : initialIdentities,
        domainGrants: persons.get(pid)?.domainGrants ?? [],
        resourceGrants: persons.get(pid)?.resourceGrants ?? [],
        lastHash: hashHex,
      });
    } else if (tool === "emit_person_confirmed") {
      const a = args as unknown as PersonConfirmedArgs;
      const p = persons.get(a.person_id);
      if (p) {
        p.status = "active";
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_person_archived") {
      const a = args as unknown as PersonArchivedArgs;
      const p = persons.get(a.person_id);
      if (p) {
        p.status = "archived";
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_identity_linked") {
      const a = args as unknown as IdentityLinkArgs;
      const p = persons.get(a.person_id);
      if (p && a.platform && a.platform_user_id) {
        const key = `${a.platform}|${a.platform_user_id}`;
        if (!p.identities.has(key)) {
          p.identities.set(key, {
            platform: a.platform,
            platformUserId: a.platform_user_id,
            displayName: null,
            addedAt: ts,
            // D2: identity_linked attribution surfaces as proposedBy.
            proposedBy: a.linked_by ?? null,
          });
        }
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_identity_unlinked") {
      const a = args as unknown as IdentityLinkArgs;
      const p = persons.get(a.person_id);
      if (p && a.platform && a.platform_user_id) {
        const key = `${a.platform}|${a.platform_user_id}`;
        p.identities.delete(key);
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_role_assigned") {
      const a = args as unknown as RoleAssignedArgs;
      const p = persons.get(a.person_id);
      if (p && isTenancyRole(a.role)) {
        p.tenancyGrants.set(a.role, {
          grantedBy: a.granted_by,
          grantedAt: ts,
        });
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_role_revoked") {
      const a = args as unknown as RoleRevokedArgs;
      const p = persons.get(a.person_id);
      if (p && isTenancyRole(a.role)) {
        p.tenancyGrants.delete(a.role);
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_domain_role_assigned") {
      const a = args as unknown as DomainRoleArgs;
      const p = persons.get(a.person_id);
      if (p) {
        p.domainGrants.push({
          domainId: a.domain_id,
          role: a.role,
          grantedBy: a.granted_by,
          grantedAt: ts,
        });
        p.lastHash = hashHex;
      }
    } else if (tool === "emit_resource_role_assigned") {
      const a = args as unknown as ResourceRoleArgs;
      const p = persons.get(a.person_id);
      if (p) {
        p.resourceGrants.push({
          resourceId: a.resource_id,
          resourceType: a.resource_type,
          role: a.role,
          grantedBy: a.granted_by,
          grantedAt: ts,
        });
        p.lastHash = hashHex;
      }
    }
  }

  return persons;
}

/**
 * Pick the highest-priority unrevoked tenancy grant.
 *
 * If a Person holds {admin, member}, surface "admin". Returns null when no
 * tenancy grants are active — this is the default state for proposed
 * Persons before an admin confirms.
 */
function topTenancyRole(
  grants: Map<TenancyRole, { grantedBy: string; grantedAt: string }>,
): TenancyRole | null {
  let top: TenancyRole | null = null;
  let topPri = 0;
  for (const role of grants.keys()) {
    const p = TENANCY_ROLE_PRIORITY[role];
    if (p > topPri) {
      top = role;
      topPri = p;
    }
  }
  return top;
}

/**
 * Project a folded state object → the public PersonRow shape.
 */
function projectPersonRow(s: FoldedPersonState): PersonRow {
  // W4-D: surface `proposedBy` + `addedAt` so the proposal-card surface can
  // render discovery provenance ("Proposed from WhatsApp DM with +5215…")
  // without an extra round-trip through getIdentitiesForPerson. The fields
  // are already folded onto the per-identity detail; we just stop dropping
  // them at the projection edge.
  const identityRows: PersonIdentityRow[] = Array.from(s.identities.values()).map(
    (i) => ({
      platform: i.platform,
      platformUserId: i.platformUserId,
      proposedBy: i.proposedBy ?? null,
      addedAt: i.addedAt ?? null,
    }),
  );
  const tenancyRole = topTenancyRole(s.tenancyGrants);
  const roles: string[] = [];
  if (tenancyRole) roles.push(tenancyRole);
  if (s.position) roles.push(s.position);
  // Derive owned-domains list from domain owner grants for back-compat with
  // the existing `<PersonRow>` table component.
  const ownedDomains = s.domainGrants
    .filter((g) => g.role === "owner")
    .map((g) => g.domainId);
  const ownedResources = s.resourceGrants
    .filter((g) => g.role === "maintainer")
    .map((g) => g.resourceId);
  return {
    personId: s.personId,
    displayName: s.displayName,
    email: s.email,
    position: s.position,
    status: s.status,
    tenancyRole,
    identities: identityRows,
    domainGrantCount: s.domainGrants.length,
    resourceGrantCount: s.resourceGrants.length,
    roles,
    ownedDomains,
    ownedResources,
    receipt: {
      hash: s.lastHash.slice(0, 12),
      source: "people-projection",
      owner: s.personId,
      classification: "internal",
    },
  };
}

export async function getPeople(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<PersonRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<FoldRow>(PERSON_FOLD_SQL, [companyId]);
    const folded = foldPersonRows(res.rows);
    // Sort by personId for stable ordering — useful for tests + UI snapshot.
    return Array.from(folded.values())
      .sort((a, b) => a.personId.localeCompare(b.personId))
      .map(projectPersonRow);
  }, []);
}

/**
 * Single-Person fold. Same SQL as `getPeople` filtered by `person_id` —
 * the JSON `args.person_id` predicate keeps the fold scoped without a
 * separate query path.
 */
const PERSON_FOLD_SQL_BY_ID = `
  SELECT seq,
         ts,
         payload->>'tool' AS tool,
         payload->'args' AS args,
         encode(hash, 'hex') AS hash_hex
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_person_proposed',
       'emit_person_confirmed',
       'emit_person_archived',
       'emit_identity_linked',
       'emit_identity_unlinked',
       'emit_role_assigned',
       'emit_role_revoked',
       'emit_domain_role_assigned',
       'emit_resource_role_assigned'
     )
     AND payload->'args'->>'person_id' = $2
   ORDER BY seq ASC
`;

export async function getPersonById(
  companyId: string,
  personId: string,
): Promise<PersonRow | null> {
  return tryPg(async () => {
    const res = await pgQuery<FoldRow>(PERSON_FOLD_SQL_BY_ID, [companyId, personId]);
    const folded = foldPersonRows(res.rows);
    const state = folded.get(personId);
    return state ? projectPersonRow(state) : null;
  }, null);
}

/**
 * Identities for a single Person — fold from
 *   emit_person_proposed (initial) +
 *   emit_identity_linked  -
 *   emit_identity_unlinked
 */
const PERSON_IDENTITIES_SQL = `
  SELECT seq,
         ts,
         payload->>'tool' AS tool,
         payload->'args' AS args
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_person_proposed',
       'emit_identity_linked',
       'emit_identity_unlinked'
     )
     AND payload->'args'->>'person_id' = $2
   ORDER BY seq ASC
`;

export async function getIdentitiesForPerson(
  companyId: string,
  personId: string,
): Promise<PersonIdentityDetailRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<{
      seq: number | string;
      ts: Date | string;
      tool: string;
      args: Record<string, unknown>;
    }>(PERSON_IDENTITIES_SQL, [companyId, personId]);

    const tsToIso = (ts: Date | string): string =>
      ts instanceof Date ? ts.toISOString() : new Date(ts).toISOString();

    const identities = new Map<string, PersonIdentityDetailRow>();
    for (const r of res.rows) {
      const args = (r.args ?? {}) as Record<string, unknown>;
      const ts = tsToIso(r.ts);
      if (r.tool === "emit_person_proposed") {
        const a = args as unknown as PersonProposedArgs;
        if (a.platform && a.platform_user_id) {
          const key = `${a.platform}|${a.platform_user_id}`;
          identities.set(key, {
            platform: a.platform,
            platformUserId: a.platform_user_id,
            displayName: a.name ?? null,
            addedAt: ts,
            // D2: surface `proposed_by` as the discovery source
            // ("worm:whatsapp_organic_discovery", "worm:slack_roster",
            // "admin_invite", real admin UUID, etc.) so the /people
            // surface can group identities by where they came from.
            proposedBy: a.proposed_by ?? null,
          });
        }
      } else if (r.tool === "emit_identity_linked") {
        const a = args as unknown as IdentityLinkArgs;
        if (a.platform && a.platform_user_id) {
          const key = `${a.platform}|${a.platform_user_id}`;
          if (!identities.has(key)) {
            identities.set(key, {
              platform: a.platform,
              platformUserId: a.platform_user_id,
              displayName: null,
              addedAt: ts,
              // identity_linked carries `linked_by`; treat it as the
              // attribution for "who attached this identity to the Person".
              proposedBy: a.linked_by ?? null,
            });
          }
        }
      } else if (r.tool === "emit_identity_unlinked") {
        const a = args as unknown as IdentityLinkArgs;
        if (a.platform && a.platform_user_id) {
          const key = `${a.platform}|${a.platform_user_id}`;
          identities.delete(key);
        }
      }
    }
    return Array.from(identities.values());
  }, []);
}

/**
 * Role grants for a single Person. Folds tenancy + domain + resource facets.
 * Returns ONLY unrevoked grants (default — matches the surface UX where
 * revoked grants live in an audit log, not the main grants table).
 *
 * Tenancy facet: emit_role_assigned + emit_role_revoked. We dedupe by role.
 * Domain facet: emit_domain_role_assigned. No revoke entry exists yet
 *   (per packages/ledger/src/wormbase_ledger/entries.py:852 — "Domain/resource
 *   revoke entries are intentionally absent until a downstream task requires
 *   them"). Each `emit_domain_role_assigned` is a distinct unrevoked grant.
 * Resource facet: same as domain.
 */
const PERSON_ROLES_SQL = `
  SELECT seq,
         ts,
         payload->>'tool' AS tool,
         payload->'args' AS args
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_role_assigned',
       'emit_role_revoked',
       'emit_domain_role_assigned',
       'emit_resource_role_assigned'
     )
     AND payload->'args'->>'person_id' = $2
   ORDER BY seq ASC
`;

export async function getRolesForPerson(
  companyId: string,
  personId: string,
): Promise<PersonRoleGrant[]> {
  return tryPg(async () => {
    const res = await pgQuery<{
      seq: number | string;
      ts: Date | string;
      tool: string;
      args: Record<string, unknown>;
    }>(PERSON_ROLES_SQL, [companyId, personId]);

    const tsToIso = (ts: Date | string): string =>
      ts instanceof Date ? ts.toISOString() : new Date(ts).toISOString();

    // Tenancy: keyed by role; revoke removes.
    const tenancy = new Map<string, PersonRoleGrant>();
    const domain: PersonRoleGrant[] = [];
    const resource: PersonRoleGrant[] = [];

    for (const r of res.rows) {
      const args = (r.args ?? {}) as Record<string, unknown>;
      const ts = tsToIso(r.ts);
      if (r.tool === "emit_role_assigned") {
        const a = args as unknown as RoleAssignedArgs;
        if (isTenancyRole(a.role)) {
          tenancy.set(a.role, {
            facet: "tenancy",
            role: a.role,
            scopeId: null,
            scopeType: null,
            grantedBy: a.granted_by ?? null,
            grantedAt: ts,
            revokedAt: null,
          });
        }
      } else if (r.tool === "emit_role_revoked") {
        const a = args as unknown as RoleRevokedArgs;
        if (isTenancyRole(a.role)) {
          tenancy.delete(a.role);
        }
      } else if (r.tool === "emit_domain_role_assigned") {
        const a = args as unknown as DomainRoleArgs;
        domain.push({
          facet: "domain",
          role: a.role,
          scopeId: a.domain_id,
          scopeType: "domain",
          grantedBy: a.granted_by ?? null,
          grantedAt: ts,
          revokedAt: null,
        });
      } else if (r.tool === "emit_resource_role_assigned") {
        const a = args as unknown as ResourceRoleArgs;
        resource.push({
          facet: "resource",
          role: a.role,
          scopeId: a.resource_id,
          scopeType: a.resource_type,
          grantedBy: a.granted_by ?? null,
          grantedAt: ts,
          revokedAt: null,
        });
      }
    }

    return [...tenancy.values(), ...domain, ...resource];
  }, []);
}

/**
 * Per-Person audit log.
 *
 * Surfaces the last `limit` ledger entries (any `kind`, any `tool`) whose
 * `payload->args->>person_id` matches `personId`. Used by the
 * PersonDetailDrawer to show a chronological audit trail of every
 * person-scoped ledger write — propose, confirm, archive, identity link /
 * unlink, role grant / revoke. Newest-first.
 *
 * No fixture fallback — empty list is the correct answer for a Person who
 * has never been written to in this tenant.
 */
export interface PersonAuditEntry {
  seq: string;
  ts: string;
  kind: string;
  tool: string | null;
  hash: string;
  args: Record<string, unknown>;
}

export async function getAuditLogForPerson(
  companyId: string,
  personId: string,
  limit = 50,
): Promise<PersonAuditEntry[]> {
  const cappedLimit = Math.min(Math.max(limit, 1), 200);
  return tryPg(async () => {
    const sql = `
      SELECT seq,
             ts,
             kind,
             payload->>'tool' AS tool,
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND payload->'args'->>'person_id' = $2
       ORDER BY seq DESC
       LIMIT $3
    `;
    const res = await pgQuery<{
      seq: string | number;
      ts: Date | string;
      kind: string;
      tool: string | null;
      args: Record<string, unknown> | null;
      hash_hex: string;
    }>(sql, [companyId, personId, cappedLimit]);
    return res.rows.map((r) => ({
      seq: String(r.seq),
      ts:
        r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString(),
      kind: r.kind,
      tool: r.tool,
      hash: r.hash_hex.slice(0, 12),
      args: (r.args ?? {}) as Record<string, unknown>,
    }));
  }, []);
}

/**
 * Domains.
 *
 * Live source: `emit_domain_registered` (CompanyWarmup writes one per
 * pre-seeded domain). `emit_domain_owner_assigned` (or `emit_domain_updated`
 * with `owner_person_id`) overrides the owner. We pick the latest row per
 * domain id and fold in any later owner-assignment.
 */
export async function getDomains(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<DomainRow[]> {
  return tryPg(async () => {
    const sql = `
      WITH domain_events AS (
        SELECT
          payload->'args'->>'id'                     AS id,
          payload->'args'->>'name'                   AS name,
          payload->'args'->>'default_classification' AS default_classification,
          payload->'args'->>'owner_person_id'        AS owner_person_id,
          payload->>'tool'                           AS tool,
          encode(hash, 'hex')                        AS hash_hex,
          seq
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' IN (
            'emit_domain_registered',
            'emit_domain_updated',
            'emit_domain_owner_assigned'
          )
          AND payload->'args'->>'id' IS NOT NULL
      ),
      registered AS (
        SELECT DISTINCT ON (id)
               id, name, default_classification, hash_hex
          FROM domain_events
         WHERE tool = 'emit_domain_registered'
         ORDER BY id, seq ASC
      ),
      latest_owner AS (
        SELECT DISTINCT ON (id)
               id, owner_person_id
          FROM domain_events
         WHERE owner_person_id IS NOT NULL
         ORDER BY id, seq DESC
      ),
      resource_count AS (
        SELECT
          payload->'args'->>'domain_id' AS domain_id,
          COUNT(DISTINCT payload->'args'->>'source_id')::int AS n
          FROM ledger
         WHERE company_id = $1
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_source_confirmed'
           AND payload->'args'->>'domain_id' IS NOT NULL
         GROUP BY domain_id
      )
      SELECT r.id, r.name, r.default_classification, r.hash_hex,
             lo.owner_person_id, COALESCE(rc.n, 0) AS resource_count
        FROM registered r
   LEFT JOIN latest_owner lo USING (id)
   LEFT JOIN resource_count rc ON rc.domain_id = r.id
       ORDER BY r.id
    `;
    const res = await pgQuery<{
      id: string;
      name: string | null;
      default_classification: string | null;
      hash_hex: string;
      owner_person_id: string | null;
      resource_count: number | string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): DomainRow => {
      const owner = r.owner_person_id ?? "unassigned";
      const classification = r.default_classification ?? "internal";
      return {
        domainId: r.id,
        name: r.name ?? r.id,
        owner,
        classificationDefault: classification,
        resourceCount:
          typeof r.resource_count === "number"
            ? r.resource_count
            : Number(r.resource_count) || 0,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "domains-projection",
          owner,
          classification,
        },
      };
    });
  }, []);
}

export async function getSources(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<SourceRow[]> {
  return tryPg(async () => {
    // Single-query projection: fold every emit_source_* execute entry per
    // source_id into one row. The first emit_source_proposed contributes the
    // immutable provenance (uri, kind, flow, classification, who+when); the
    // most-recent emit_source_* contributes the latest status and (for
    // emit_source_profiled) the row count.
    //
    // We use DISTINCT ON to pick the latest row per source_id, then join
    // with the *first* proposed row for the immutable fields. JSON path
    // expressions match the worm-core write primitive: payload->'args'->>'…'.
    const sql = `
      WITH source_events AS (
        SELECT
          payload->'args'->>'source_id'             AS source_id,
          payload->'args'->>'source_kind'           AS source_kind,
          payload->'args'->>'uri'                   AS uri,
          payload->'args'->>'suggested_classification' AS suggested_classification,
          payload->'args'->>'classification'        AS classification,
          payload->'args'->>'added_via_flow'        AS added_via_flow,
          payload->'args'->>'confirmed_by_person'   AS confirmed_by_person,
          payload->'args'->>'row_count'             AS row_count,
          payload->>'tool'                          AS tool,
          ts,
          seq
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' LIKE 'emit_source_%'
          AND payload->'args'->>'source_id' IS NOT NULL
      ),
      first_proposed AS (
        SELECT DISTINCT ON (source_id)
          source_id, source_kind, uri, suggested_classification,
          added_via_flow, ts AS added_at
        FROM source_events
        WHERE tool = 'emit_source_proposed'
        ORDER BY source_id, seq ASC
      ),
      latest_event AS (
        SELECT DISTINCT ON (source_id)
          source_id, tool AS latest_tool, classification AS latest_classification,
          confirmed_by_person, ts AS latest_ts, seq AS latest_seq
        FROM source_events
        ORDER BY source_id, seq DESC
      ),
      latest_profile AS (
        SELECT DISTINCT ON (source_id)
          source_id, row_count, ts AS profile_ts
        FROM source_events
        WHERE tool = 'emit_source_profiled'
        ORDER BY source_id, seq DESC
      ),
      -- Step 2 medallion: bronze / silver / gold status booleans per
      -- source. Each flag is true when at least one corresponding emit_*
      -- entry has been written. See
      -- docs/superpowers/specs/2026-04-26-wormbase-product-arc.md.
      bronzed AS (
        SELECT DISTINCT source_id FROM source_events WHERE tool = 'emit_source_bronzed'
      ),
      silvered AS (
        SELECT DISTINCT source_id FROM source_events WHERE tool = 'emit_source_silvered'
      ),
      golded AS (
        SELECT DISTINCT source_id FROM source_events WHERE tool = 'emit_source_golded'
      ),
      -- D5: latest unrevoked maintainer grant per source. We surface
      -- maintainerPersonId on the source row; the dashboard joins
      -- against the people projection to resolve names.
      maintainer AS (
        SELECT DISTINCT ON (payload->'args'->>'resource_id')
          payload->'args'->>'resource_id' AS source_id,
          payload->'args'->>'person_id'   AS maintainer_person_id
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_resource_role_assigned'
          AND payload->'args'->>'resource_type' = 'source'
          AND payload->'args'->>'role' = 'maintainer'
        ORDER BY payload->'args'->>'resource_id', seq DESC
      ),
      -- Phase 3 Task 3D — latest drift signal per source. Reads
      -- emit_source_drift_detected entries written by the
      -- lake-maintainer's DriftDetectorReactivity. The most-recent row
      -- determines whether the row currently shows a drift badge; the
      -- reason is surfaced via the badge's title attribute.
      latest_drift AS (
        SELECT DISTINCT ON (payload->'args'->>'source_id')
          payload->'args'->>'source_id' AS source_id,
          payload->'args'->>'reason'    AS reason,
          ts                            AS detected_at
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_source_drift_detected'
          AND payload->'args'->>'source_id' IS NOT NULL
        ORDER BY payload->'args'->>'source_id', seq DESC
      ),
      -- Phase 3 Task 3D — last_seen mirrored from
      -- projection_sources (Wave G's v003 migration). The fold above
      -- already derives source_id from the ledger; we LEFT JOIN here
      -- so a source that has been proposed but never observed by the
      -- maintainer still renders, with a null last_seen surfaced as
      -- the honest "never seen" empty-state on the dashboard.
      proj_freshness AS (
        SELECT
          source_id::text AS source_id,
          last_seen
        FROM projection_sources
        WHERE company_id = $1
      )
      SELECT
        fp.source_id,
        fp.source_kind,
        fp.uri,
        COALESCE(le.latest_classification, fp.suggested_classification) AS classification,
        fp.added_via_flow,
        fp.added_at,
        le.latest_tool,
        le.confirmed_by_person,
        lp.row_count,
        lp.profile_ts,
        (b.source_id IS NOT NULL) AS bronzed,
        (s.source_id IS NOT NULL) AS silvered,
        (g.source_id IS NOT NULL) AS golded,
        m.maintainer_person_id AS maintainer_person_id,
        ld.reason            AS drift_reason,
        ld.detected_at       AS drift_detected_at,
        pf.last_seen         AS last_seen
      FROM first_proposed fp
      LEFT JOIN latest_event le USING (source_id)
      LEFT JOIN latest_profile lp USING (source_id)
      LEFT JOIN bronzed b USING (source_id)
      LEFT JOIN silvered s USING (source_id)
      LEFT JOIN golded g USING (source_id)
      LEFT JOIN maintainer m USING (source_id)
      LEFT JOIN latest_drift ld USING (source_id)
      LEFT JOIN proj_freshness pf USING (source_id)
      ORDER BY fp.added_at DESC
    `;
    const res = await pgQuery<{
      source_id: string;
      source_kind: string | null;
      uri: string;
      classification: string | null;
      added_via_flow: string | null;
      added_at: Date | string;
      latest_tool: string | null;
      confirmed_by_person: string | null;
      row_count: string | null;
      profile_ts: Date | string | null;
      bronzed: boolean | null;
      silvered: boolean | null;
      golded: boolean | null;
      maintainer_person_id: string | null;
      drift_reason: string | null;
      drift_detected_at: Date | string | null;
      last_seen: Date | string | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0) {
      // No live source events yet — return the honest empty list. The
      // /sources page renders a meaningful empty state pointing the
      // operator at the five worm-driven source-building flows
      // (drop-and-profile, credential-in-DM, mentioned-in-conversation,
      // dashboard form, kpi-gap-triggered).
      return [];
    }

    // D5: resolve maintainer person_ids → display names via the people
    // fold. Best-effort; the row still renders with the bare person_id
    // when the people projection is unavailable.
    const nameById = new Map<string, string>();
    const hasMaintainers = res.rows.some((r) => r.maintainer_person_id);
    if (hasMaintainers) {
      try {
        const people = await getPeople(companyId);
        for (const p of people) nameById.set(p.personId, p.displayName);
      } catch {
        // Non-fatal.
      }
    }

    // Phase 3 Task 3D — fetch the last 30 days of lake-maintainer
    // signals for every source in this fold. One query, grouped on the
    // server, so the per-row N+1 is avoided. The four tools we surface
    // are the four that the lake-maintainer Reactivities emit
    // (`packages/lake-maintainer/src/wormbase_lake_maintainer/reactivities.py`).
    const signalSql = `
      SELECT
        payload->'args'->>'source_id' AS source_id,
        payload->>'tool'              AS tool,
        payload->'args'->>'reason'    AS reason,
        ts
      FROM ledger
      WHERE company_id = $1
        AND kind = 'execute'
        AND payload->>'tool' IN (
          'emit_source_staleness_signaled',
          'emit_source_drift_detected',
          'emit_source_classification_refreshed',
          'emit_source_lineage_break_detected'
        )
        AND payload->'args'->>'source_id' IS NOT NULL
        AND ts >= NOW() - INTERVAL '30 days'
      ORDER BY ts DESC
    `;
    const signalsBySource = new Map<string, MaintenanceSignal[]>();
    try {
      const sigRes = await pgQuery<{
        source_id: string;
        tool: string;
        reason: string | null;
        ts: Date | string;
      }>(signalSql, [companyId]);
      for (const sr of sigRes.rows) {
        const kind = signalKindFromTool(sr.tool);
        if (!kind) continue;
        const tsIso =
          sr.ts instanceof Date ? sr.ts.toISOString() : new Date(sr.ts).toISOString();
        const list = signalsBySource.get(sr.source_id) ?? [];
        list.push({ kind, ts: tsIso, tool: sr.tool, reason: sr.reason });
        signalsBySource.set(sr.source_id, list);
      }
    } catch {
      // Non-fatal — the row still renders, just with maintenanceSignals
      // omitted (back-compat empty-state).
    }

    return res.rows.map((r) => {
      const flow: SourceFlow = isSourceFlow(r.added_via_flow)
        ? r.added_via_flow
        : "drop_and_profile";
      const classification = r.classification ?? "internal";
      const addedAt =
        r.added_at instanceof Date
          ? r.added_at.toISOString()
          : new Date(r.added_at).toISOString();
      const profileTs =
        r.profile_ts == null
          ? null
          : r.profile_ts instanceof Date
            ? r.profile_ts.toISOString()
            : new Date(r.profile_ts).toISOString();
      const rowCount = r.row_count == null ? 0 : Number(r.row_count) || 0;
      // Receipt hash: first 12 chars of source_id (a uuid). This gives a
      // stable visual identity per source without re-hashing in the read
      // path. The full ledger hash is available via /trace if the user
      // wants the underlying entry.
      const hash = String(r.source_id).replace(/-/g, "").slice(0, 12);
      const maintainerPersonId = r.maintainer_person_id ?? null;
      const maintainerName = maintainerPersonId
        ? (nameById.get(maintainerPersonId) ?? null)
        : null;
      const lastSeen =
        r.last_seen == null
          ? null
          : r.last_seen instanceof Date
            ? r.last_seen.toISOString()
            : new Date(r.last_seen).toISOString();
      const driftDetected = Boolean(r.drift_detected_at);
      const driftReason = driftDetected ? (r.drift_reason ?? null) : null;
      const maintenanceSignals = signalsBySource.get(r.source_id) ?? [];
      return {
        sourceId: r.source_id,
        uri: r.uri,
        kind: r.source_kind ?? "table",
        addedByPerson: r.confirmed_by_person ?? "worm",
        addedAt,
        addedViaFlow: flow,
        addedInResponseTo: null,
        rowCount,
        lastProfileTs: profileTs,
        receipt: {
          hash,
          source: r.uri,
          owner: r.confirmed_by_person ?? "worm",
          classification,
        },
        bronzed: Boolean(r.bronzed),
        silvered: Boolean(r.silvered),
        golded: Boolean(r.golded),
        maintainerPersonId,
        maintainerName,
        ownerDomain: null,
        classification,
        lastSeen,
        driftDetected,
        driftReason,
        maintenanceSignals,
      };
    });
  }, []);
}

/**
 * Map a lake-maintainer ledger tool name to its
 * `MaintenanceSignalKind`. Returns null for any unrelated tool —
 * defensive against unexpected ledger entries.
 */
function signalKindFromTool(tool: string): MaintenanceSignalKind | null {
  switch (tool) {
    case "emit_source_staleness_signaled":
      return "staleness";
    case "emit_source_drift_detected":
      return "drift";
    case "emit_source_classification_refreshed":
      return "classification_refresh";
    case "emit_source_lineage_break_detected":
      return "lineage_break";
    default:
      return null;
  }
}

const SOURCE_FLOWS: ReadonlySet<SourceFlow> = new Set<SourceFlow>([
  "drop_and_profile",
  "credential_offered_in_dm",
  "mentioned_in_conversation",
  "dashboard_form",
  "kpi_gap_triggered",
  "lake_discovery",
]);

function isSourceFlow(v: string | null | undefined): v is SourceFlow {
  return typeof v === "string" && SOURCE_FLOWS.has(v as SourceFlow);
}

/**
 * Policies.
 *
 * Live source: `emit_policy_applied` (one row per template, written by
 * PolicyLoader during warmup). Fires-last-7-days is a count of
 * `emit_gate_fired` rows whose `args.policy_id` (or `args.gate`) matches the
 * policy. We compute it in a single CTE.
 *
 * Plain-language summaries are kept in the fixture-derived map below — the
 * ledger doesn't carry a human-readable explanation; that's an authored
 * dashboard concern. We synthesize one when the policy isn't in our map.
 */
const POLICY_PLAIN_LANGUAGE: Record<string, string> = {
  pii_redaction:
    "Email and phone columns are redacted in any answer that surfaces in a public channel.",
  warmup_required:
    "The worm waits for ramp axes to cross threshold before posting unsolicited insights.",
  interjection_budget:
    "At most 3 unsolicited messages per channel per day; weekly digest otherwise.",
  dm_routing_v1: "Only allowlisted operators may DM the worm.",
  channel_talkativeness_v1:
    "Each channel has a lurker / responsive / proactive disposition.",
};

export async function getPolicies(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<PolicyRow[]> {
  return tryPg(async () => {
    const sql = `
      WITH applied AS (
        SELECT DISTINCT ON (payload->'args'->>'policy_id')
          payload->'args'->>'policy_id'   AS policy_id,
          payload->'args'->>'policy_name' AS policy_name,
          payload->'args'->>'gate_impl'   AS gate_impl,
          payload->'args'->'applies_to'   AS applies_to,
          encode(hash, 'hex')             AS hash_hex,
          seq
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_policy_applied'
          AND payload->'args'->>'policy_id' IS NOT NULL
        ORDER BY payload->'args'->>'policy_id', seq ASC
      ),
      fired_counts AS (
        SELECT
          COALESCE(payload->'args'->>'policy_id', payload->'args'->>'gate') AS policy_key,
          COUNT(*)::int AS fires
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_gate_fired'
          AND ts > now() - interval '7 days'
        GROUP BY policy_key
      )
      SELECT a.policy_id, a.policy_name, a.gate_impl, a.applies_to, a.hash_hex,
             COALESCE(fc.fires, 0) AS fires_last_7d
        FROM applied a
   LEFT JOIN fired_counts fc
          ON fc.policy_key = a.policy_id
          OR fc.policy_key = a.policy_name
       ORDER BY a.policy_name
    `;
    const res = await pgQuery<{
      policy_id: string;
      policy_name: string | null;
      gate_impl: string | null;
      applies_to: Record<string, unknown> | null;
      hash_hex: string;
      fires_last_7d: number | string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): PolicyRow => {
      const name = r.policy_name ?? r.policy_id;
      const scope = (() => {
        const at = r.applies_to ?? {};
        if (typeof at["channel"] === "string") return "per-channel";
        if (typeof at["domain"] === "string") return "per-domain";
        return "global";
      })();
      const fires =
        typeof r.fires_last_7d === "number"
          ? r.fires_last_7d
          : Number(r.fires_last_7d) || 0;
      return {
        policyId: name,
        name,
        plainLanguage:
          POLICY_PLAIN_LANGUAGE[name] ??
          `Policy ${name} from the warmup pack; see gate_impl for the rule.`,
        gateImpl: r.gate_impl ?? "",
        scope,
        firesLast7d: fires,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "policy-pack-v1",
          owner: "system",
          classification: "internal",
        },
      };
    });
  }, []);
}

/**
 * Channels.
 *
 * Live source: distinct `args.channel_id` values across `chat_received`
 * entries (passive ingest). We try to enrich with `emit_channel_registered`
 * if the upstream service writes one; if not, we synthesize a row per
 * channel_id and default talkativeness to `responsive` (which is what the
 * channel-adapter assumes when it has no explicit policy).
 */
const TALKATIVENESS_VALUES = new Set<Talkativeness>([
  "lurker",
  "responsive",
  "proactive",
]);

function isTalkativeness(v: unknown): v is Talkativeness {
  return typeof v === "string" && TALKATIVENESS_VALUES.has(v as Talkativeness);
}

/**
 * Folded list of channel-platform installs for a tenant.
 *
 * Source entries: `emit_install_completed` (creates row, status=active),
 * `emit_install_revoked` (flips matching install to status=revoked). The
 * fold is keyed on (tenant, platform) — the most recent completed install
 * per platform wins, then revokes flip its status.
 *
 * Returns one row per Install (active and revoked alike — the UI mutes
 * revoked rows). Empty list when no install entries exist; no fixture
 * fallback because /channels (D3) is a live-only surface.
 */
export async function getInstalls(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<InstallRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT seq,
             ts,
             payload->>'tool' AS tool,
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_install_completed',
           'emit_install_revoked',
           'emit_setup_mode_chosen',
           'emit_setup_completed'
         )
       ORDER BY seq ASC
    `;
    const res = await pgQuery<{
      seq: string | number;
      ts: Date | string;
      tool: string;
      args: Record<string, unknown>;
      hash_hex: string;
    }>(sql, [companyId]);

    type InstallState = InstallRow;
    // Keyed on platform — most recent completed install per platform wins.
    const byPlatform = new Map<string, InstallState>();
    // Lookup by install_id for the revoke pass.
    const byInstallId = new Map<string, InstallState>();

    for (const r of res.rows) {
      const args = (r.args ?? {}) as Record<string, unknown>;
      const ts =
        r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString();
      const hash = (r.hash_hex ?? "").slice(0, 12);

      if (r.tool === "emit_install_completed") {
        const installId = String(args["install_id"] ?? "");
        const platform = String(args["platform"] ?? "");
        if (!installId || !platform) continue;
        const installerPersonId = args["installer_person_id"]
          ? String(args["installer_person_id"])
          : null;
        const scopesRaw = args["scopes"];
        const scopes = Array.isArray(scopesRaw) ? scopesRaw.map(String) : [];
        // If a prior install row for this platform already carried setup
        // metadata (rare; only when the admin re-installs mid-flow), we
        // preserve those fields so the redirect guard remains stable.
        const prior = byPlatform.get(platform);
        const row: InstallState = {
          installId,
          platform,
          installerPersonId,
          installerName: null,
          installedAt: ts,
          status: "active",
          scopes,
          botUserId: args["bot_user_id"] ? String(args["bot_user_id"]) : null,
          oauthGrantRef: String(args["oauth_grant_ref"] ?? ""),
          setupMode: prior?.setupMode ?? null,
          setupCompletedAt: prior?.setupCompletedAt ?? null,
          // Phase D1 — pairing status for capability-honesty rendering.
          // Slack/Discord/Teams: ``connected`` when active. WhatsApp:
          // ``paired`` (Baileys lifecycle vocabulary; see InstallRow type
          // doc). Re-derived in the second pass below alongside revokes.
          pairingStatus:
            platform === "whatsapp" ? "paired" : "connected",
          receipt: {
            hash,
            source: "install-projection",
            owner: installerPersonId ?? "system",
            classification: "internal",
          },
        };
        byPlatform.set(platform, row);
        byInstallId.set(installId, row);
      } else if (r.tool === "emit_install_revoked") {
        const installId = String(args["install_id"] ?? "");
        const target = byInstallId.get(installId);
        if (target) {
          target.status = "revoked";
          target.pairingStatus =
            target.platform === "whatsapp" ? "expired" : "disconnected";
        }
      } else if (r.tool === "emit_setup_mode_chosen") {
        // Tenant-level — stamp every install row.
        const mode = args["mode"] === "wizard" || args["mode"] === "bot"
          ? args["mode"]
          : null;
        for (const inst of byPlatform.values()) {
          inst.setupMode = mode as "wizard" | "bot" | null;
        }
      } else if (r.tool === "emit_setup_completed") {
        for (const inst of byPlatform.values()) {
          inst.setupCompletedAt = ts;
        }
      }
    }

    // Resolve installer names from people projection (best-effort — empty
    // string if the Person hasn't been folded yet).
    const installs = Array.from(byPlatform.values());
    if (installs.length > 0) {
      try {
        const people = await getPeople(companyId);
        const nameById = new Map(people.map((p) => [p.personId, p.displayName]));
        for (const inst of installs) {
          if (inst.installerPersonId) {
            inst.installerName = nameById.get(inst.installerPersonId) ?? null;
          }
        }
      } catch {
        // Non-fatal — surface the install list without resolved names.
      }
    }

    return installs.sort((a, b) => a.platform.localeCompare(b.platform));
  }, []);
}

/**
 * Resolve the most-recent active install for a single tenant.
 *
 * Reads via `getInstalls(companyId)`, drops revoked rows, prefers the
 * Slack platform first (mirrors the demo's day-one channel), falls back
 * to the lexicographic first active install. Returns `null` when no
 * active install exists — the caller renders an honest empty state.
 *
 * Mirrors `lib/server/identity.getCurrentInstall` so consumers under
 * `lib/server/` and consumers under `lib/` (e.g. the /onboarding/welcome
 * server component) reach for the same accessor without a layer-violation
 * import.
 */
export async function getCurrentInstall(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<InstallRow | null> {
  let installs: InstallRow[] = [];
  try {
    installs = await getInstalls(companyId);
  } catch {
    return null;
  }
  const active = installs.filter((i) => i.status === "active");
  if (active.length === 0) return null;
  const slackFirst = active.find((i) => i.platform === "slack");
  return slackFirst ?? active[0];
}

/**
 * Cross-tenant install index for the `/login` tenant picker.
 *
 * Walks every known tenant (via `listKnownTenantsSync`), folds the
 * canonical install rows out of each tenant's ledger, joins the
 * installer Person row to surface name + email, and computes the most
 * recent ledger activity timestamp per tenant. Returns the aggregated
 * list sorted by `lastActivityAt` descending so the most recently used
 * install lands at the top of the picker.
 *
 * No fixture fallback. Tenants with zero installs are omitted entirely;
 * if every tenant has zero installs the function returns `[]` and the
 * picker renders an honest "No installs found" empty state pointing
 * the user at `/onboarding`.
 */
export async function getAllInstalls(): Promise<InstallSummary[]> {
  const tenants = listKnownTenantsSync();
  const summaries: InstallSummary[] = [];

  for (const tenant of tenants) {
    let installs: InstallRow[] = [];
    let people: PersonRow[] = [];
    let lastActivityAt: string | null = null;
    try {
      installs = await getInstalls(tenant.companyId);
    } catch {
      installs = [];
    }
    if (installs.length === 0) continue;
    try {
      people = await getPeople(tenant.companyId);
    } catch {
      people = [];
    }
    try {
      lastActivityAt = await getLastLedgerTs(tenant.companyId);
    } catch {
      lastActivityAt = null;
    }

    const personById = new Map(people.map((p) => [p.personId, p]));

    for (const install of installs) {
      const installer = install.installerPersonId
        ? personById.get(install.installerPersonId) ?? null
        : null;
      const installerEmail =
        installer && typeof installer.email === "string"
          ? installer.email
          : null;
      const installerName =
        install.installerName ?? installer?.displayName ?? null;
      const fallbackActivity = install.installedAt;
      summaries.push({
        installId: install.installId,
        tenantSlug: tenant.slug,
        tenantDisplayName: tenant.displayName,
        companyId: tenant.companyId,
        platform: install.platform,
        installerPersonId: install.installerPersonId,
        installerName,
        installerEmail,
        installedAt: install.installedAt,
        lastActivityAt: lastActivityAt ?? fallbackActivity,
        status: install.status,
        scopes: install.scopes,
        receipt: install.receipt,
      });
    }
  }

  // Most recent activity first; tenants with the same lastActivityAt
  // sort by installedAt descending.
  return summaries.sort((a, b) => {
    const lhs = b.lastActivityAt.localeCompare(a.lastActivityAt);
    if (lhs !== 0) return lhs;
    return b.installedAt.localeCompare(a.installedAt);
  });
}

/**
 * Most recent ledger ts for a tenant (any kind). Used by the cross-tenant
 * install index to populate `lastActivityAt`. Returns null when no rows
 * exist or the Postgres path is unavailable.
 */
async function getLastLedgerTs(companyId: string): Promise<string | null> {
  return tryPg(async () => {
    const sql = `
      SELECT ts
        FROM ledger
       WHERE company_id = $1
       ORDER BY seq DESC
       LIMIT 1
    `;
    const res = await pgQuery<{ ts: Date | string }>(sql, [companyId]);
    if (res.rows.length === 0) return null;
    const ts = res.rows[0].ts;
    return ts instanceof Date ? ts.toISOString() : new Date(ts).toISOString();
  }, null);
}

export async function getChannels(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<ChannelRow[]> {
  return tryPg(async () => {
    const sql = `
      WITH chat_channels AS (
        SELECT
          payload->'args'->>'channel_id' AS channel_id,
          MAX(seq) AS last_seq,
          MAX(ts)  AS last_ts
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' IN (
            'emit_chat_received',
            'channel_adapter.emit_chat_received'
          )
          AND payload->'args'->>'channel_id' IS NOT NULL
        GROUP BY channel_id
      ),
      registered AS (
        SELECT DISTINCT ON (payload->'args'->>'channel_id')
          payload->'args'->>'channel_id'   AS channel_id,
          payload->'args'->>'name'         AS name,
          payload->'args'->>'talkativeness' AS talkativeness,
          encode(hash, 'hex')               AS hash_hex
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_channel_registered'
          AND payload->'args'->>'channel_id' IS NOT NULL
        ORDER BY payload->'args'->>'channel_id', seq DESC
      )
      SELECT cc.channel_id, cc.last_ts, r.name, r.talkativeness, r.hash_hex
        FROM chat_channels cc
   LEFT JOIN registered r USING (channel_id)
       ORDER BY cc.channel_id
    `;
    const res = await pgQuery<{
      channel_id: string;
      last_ts: Date | string | null;
      name: string | null;
      talkativeness: string | null;
      hash_hex: string | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): ChannelRow => {
      const talk = isTalkativeness(r.talkativeness)
        ? r.talkativeness
        : "responsive";
      const name = r.name ?? r.channel_id;
      const hash = (r.hash_hex ?? r.channel_id).slice(0, 12);
      const platform = inferPlatformFromChannelId(r.channel_id);
      const lastSeenAt =
        r.last_ts == null
          ? null
          : r.last_ts instanceof Date
            ? r.last_ts.toISOString()
            : new Date(r.last_ts).toISOString();
      return {
        channelId: r.channel_id,
        name,
        talkativeness: talk,
        lastPolicyHash: hash,
        platform,
        lastSeenAt,
        receipt: {
          hash,
          source: "channel-policy-v1",
          owner: "system",
          classification: "internal",
        },
      };
    });
  }, []);
}

/**
 * Infer the channel platform from the platform-native id.
 *
 * Slack channel ids start with ``C`` (public/private channel) or ``D`` (DM).
 * WhatsApp jids end in ``@s.whatsapp.net`` (DMs) or ``@g.us`` (group).
 * Discord channel ids are 17–19 digit Snowflakes (no separator).
 *
 * Returns ``undefined`` when the shape doesn't match any known platform —
 * the renderer falls back to the channel_id literal.
 *
 * W4-A — exported so cross-cutting surfaces (topics, trace) and tests can
 * pin the classification rules; mirrors the server-side ``_is_whatsapp_args``
 * predicate in
 * ``packages/wormbase-chat-presence/src/wormbase_chat_presence/predicates.py``.
 */
export function inferPlatformFromChannelId(
  channelId: string | null | undefined,
): PlatformSlug | undefined {
  if (!channelId) return undefined;
  if (channelId.endsWith("@s.whatsapp.net") || channelId.endsWith("@g.us")) {
    return "whatsapp";
  }
  if (/^[CD][A-Z0-9]{8,}$/.test(channelId)) {
    return "slack";
  }
  return undefined;
}

/**
 * Phase D3 — `conversation_sync` history projection.
 *
 * One PEVR cycle per platform reconnect / initial-connect / channel-join is
 * written via ``LedgerWriter.emit_conversation_sync`` (tool name
 * ``channel_adapter.emit_conversation_sync``). The execute entry's
 * ``payload->'args'`` carries the full ConversationSyncPayload shape; we
 * fold them into one row per ``sync_id``.
 *
 * Multiple PEVR quadrants (propose/execute/verify/resolve) land in the
 * ledger for each sync, but we read only the execute quadrant — args carry
 * the canonical bookkeeping (started_at / completed_at / message_count /
 * status). When a sync transitions ``in_progress → completed/interrupted``
 * a fresh execute lands and the latest one wins (folded by sync_id).
 *
 * When ``channelId`` is provided, only syncs whose ``channels`` list
 * contains that id are returned. WhatsApp's per-channel granularity (one
 * sync per ``@s.whatsapp.net`` jid) and Slack's multi-channel reconnects
 * both fold consistently here.
 *
 * Sorted descending by ``started_at`` so the most-recent sync appears at
 * the top of the panel.
 */
const CONVERSATION_SYNC_TRIGGERS: ReadonlyArray<ConversationSyncTrigger> = [
  "initial_connect",
  "reconnect",
  "channel_join",
];
const CONVERSATION_SYNC_STATUSES: ReadonlyArray<ConversationSyncStatus> = [
  "in_progress",
  "completed",
  "interrupted",
];

function isConversationSyncTrigger(
  v: unknown,
): v is ConversationSyncTrigger {
  return (
    typeof v === "string" &&
    (CONVERSATION_SYNC_TRIGGERS as readonly string[]).includes(v)
  );
}

function isConversationSyncStatus(
  v: unknown,
): v is ConversationSyncStatus {
  return (
    typeof v === "string" &&
    (CONVERSATION_SYNC_STATUSES as readonly string[]).includes(v)
  );
}

function tsToIsoOrNull(v: Date | string | null | undefined): string | null {
  if (v == null) return null;
  if (v instanceof Date) return v.toISOString();
  return new Date(v).toISOString();
}

export async function getConversationSyncs(
  companyId: string = DEFAULT_COMPANY_ID,
  channelId?: string,
): Promise<ConversationSyncRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT seq,
             ts,
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'channel_adapter.emit_conversation_sync'
       ORDER BY seq ASC
    `;
    const res = await pgQuery<{
      seq: string | number;
      ts: Date | string;
      args: Record<string, unknown> | null;
      hash_hex: string | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    // Latest execute per sync_id wins (status transitions in_progress →
    // completed/interrupted as the session settles). Multiple PEVR cycles
    // for the same sync collapse to the most-recent canonical state.
    const bySync = new Map<string, ConversationSyncRow>();
    for (const r of res.rows) {
      const args = (r.args ?? {}) as Record<string, unknown>;
      const syncId = String(args["sync_id"] ?? "");
      if (!syncId) continue;
      const platform = String(args["platform"] ?? "");
      const trigger = isConversationSyncTrigger(args["trigger"])
        ? args["trigger"]
        : "initial_connect";
      const status = isConversationSyncStatus(args["status"])
        ? args["status"]
        : "in_progress";
      const channelsRaw = args["channels"];
      const channels = Array.isArray(channelsRaw)
        ? channelsRaw.map((c) => String(c))
        : [];
      const messageCountRaw = args["message_count"];
      const messageCount =
        typeof messageCountRaw === "number"
          ? messageCountRaw
          : Number(messageCountRaw ?? 0);
      const installId = args["install_id"]
        ? String(args["install_id"])
        : null;
      const hash = (r.hash_hex ?? "").slice(0, 12);
      const startedAt =
        tsToIsoOrNull((args["started_at"] as string | null) ?? null) ??
        tsToIsoOrNull(r.ts) ??
        new Date(0).toISOString();
      const completedAt = tsToIsoOrNull(
        (args["completed_at"] as string | null) ?? null,
      );
      const earliestTs = tsToIsoOrNull(
        (args["earliest_ts"] as string | null) ?? null,
      );
      const latestTs = tsToIsoOrNull(
        (args["latest_ts"] as string | null) ?? null,
      );

      bySync.set(syncId, {
        syncId,
        platform,
        installId,
        channelIds: channels,
        trigger,
        startedAt,
        completedAt,
        messageCount: Number.isFinite(messageCount) ? messageCount : 0,
        earliestTs,
        latestTs,
        status,
        receipt: {
          hash,
          source: "conversation-sync-projection",
          owner: "channel-adapter",
          classification: "internal",
        },
      });
    }

    let rows = Array.from(bySync.values());
    if (channelId) {
      rows = rows.filter((r) => r.channelIds.includes(channelId));
    }
    // Most recent first — drives both the per-channel panel and the
    // parent /channels "Recent syncs" mini-panel ordering.
    rows.sort((a, b) => (a.startedAt < b.startedAt ? 1 : -1));
    return rows;
  }, []);
}

/**
 * W3-B (2026-05-07) — Recent ``policy_applied`` events scoped to a tenant
 * + policy name.
 *
 * Used by ``RateLimitStatusPanel`` to surface throttle events on
 * ``/channels/[id]`` for WhatsApp, but the shape is generic — any panel
 * that wants to show recent gate emissions for a specific policy
 * (e.g. PII redaction, warmup gate) can read this. Mirrors
 * ``getConversationSyncs`` shape: SQL fold over ledger entries where
 * ``kind == 'execute'`` and ``payload.tool == 'emit_policy_applied'`` and
 * ``payload.args.policy_name == $2``.
 *
 * Schema-evolution doctrine: reads existing ``policy_applied`` kind, no
 * new entry kinds. Tenant-scoped on company_id; sorted most-recent-first.
 *
 * Returns ``[]`` when no entries match — the panel surfaces an honest
 * "no throttling events recorded" empty state.
 */
export async function getPolicyAppliedEvents(
  companyId: string,
  policyName: string,
  opts: { limit?: number } = {},
): Promise<PolicyAppliedEvent[]> {
  const limit = Math.max(1, Math.min(opts.limit ?? 50, 500));
  return tryPg(async () => {
    const sql = `
      SELECT seq,
             ts,
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_policy_applied'
         AND payload->'args'->>'policy_name' = $2
       ORDER BY seq DESC
       LIMIT $3
    `;
    const res = await pgQuery<{
      seq: string | number;
      ts: Date | string;
      args: Record<string, unknown> | null;
      hash_hex: string | null;
    }>(sql, [companyId, policyName, limit]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): PolicyAppliedEvent => {
      const args = (r.args ?? {}) as Record<string, unknown>;
      const ts = tsToIsoOrNull(r.ts) ?? new Date(0).toISOString();
      const hash = (r.hash_hex ?? "").slice(0, 12);
      const appliesToRaw = args["applies_to"];
      const appliesTo: Record<string, unknown> =
        appliesToRaw &&
        typeof appliesToRaw === "object" &&
        !Array.isArray(appliesToRaw)
          ? (appliesToRaw as Record<string, unknown>)
          : {};
      const botPhone =
        typeof args["bot_phone"] === "string"
          ? (args["bot_phone"] as string)
          : typeof appliesTo["bot_phone"] === "string"
            ? (appliesTo["bot_phone"] as string)
            : null;
      return {
        hash,
        ts,
        policyName: String(args["policy_name"] ?? policyName),
        rule: String(args["rule"] ?? ""),
        rationale:
          typeof args["rationale"] === "string"
            ? (args["rationale"] as string)
            : "",
        appliesTo,
        botPhone,
        outcome:
          typeof args["outcome"] === "string"
            ? (args["outcome"] as string)
            : "applied",
        receipt: {
          hash,
          source: "policy-applied-projection",
          owner: "system",
          classification: "internal",
        },
      };
    });
  }, []);
}

/**
 * Phase D3 — per-channel `chat_received` projection with optional
 * ``history_sync_id`` filter.
 *
 * Returns the most-recent ``limit`` chat_received rows for ``channelId``,
 * optionally restricted to those carrying ``history_sync_id ==
 * historySyncId``. Drives the channel detail page's chat history view; the
 * sync history panel's click-through threads a sync's id through this
 * filter so the operator sees exactly the messages folded by that session.
 *
 * Mirrors ``getConversations`` shape (ConversationMessage) so the existing
 * row renderer can be reused without churn.
 */
export async function getChatReceivedForChannel(
  companyId: string,
  channelId: string,
  opts: {
    historySyncId?: string;
    limit?: number;
  } = {},
): Promise<ConversationMessage[]> {
  const limit = Math.max(1, Math.min(opts.limit ?? 100, 500));
  const historySyncId = opts.historySyncId ?? null;
  return tryPg(async () => {
    const params: unknown[] = [companyId, channelId];
    let historyClause = "";
    if (historySyncId) {
      params.push(historySyncId);
      historyClause = `AND payload->'args'->>'history_sync_id' = $3`;
    }
    const sql = `
      SELECT ts,
             payload->'args'->>'channel_id'    AS channel_id,
             payload->'args'->>'sender_person' AS sender_person,
             payload->'args'->>'text'          AS text,
             payload->'args'->>'classification' AS classification,
             encode(hash, 'hex')                AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_chat_received',
           'channel_adapter.emit_chat_received'
         )
         AND payload->'args'->>'channel_id' = $2
         ${historyClause}
       ORDER BY seq DESC
       LIMIT ${limit}
    `;
    const res = await pgQuery<{
      ts: Date | string;
      channel_id: string | null;
      sender_person: string | null;
      text: string | null;
      classification: string | null;
      hash_hex: string;
    }>(sql, params);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): ConversationMessage => {
      const ts =
        r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString();
      const author = r.sender_person
        ? `person:${r.sender_person.slice(0, 8)}`
        : "unknown";
      const channel = r.channel_id ?? channelId;
      const classification = r.classification ?? "internal";
      return {
        ts,
        channel,
        author,
        text: r.text ?? "",
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: channel,
          owner: author,
          classification,
        },
      };
    });
  }, []);
}

/**
 * Proposed business definitions.
 *
 * Live source: `emit_business_def_proposed` (Tier-2 wizard) folded with any
 * `emit_business_def_confirmed` so confirmed terms drop out of the proposal
 * list. Returns `[]` when no proposals exist; the onboarding wizard surfaces
 * an "the worm is still listening" empty state in that case.
 */
export async function getProposedBusinessDefs(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<BusinessDefProposal[]> {
  return tryPg(async () => {
    const sql = `
      WITH proposed AS (
        SELECT DISTINCT ON (lower(payload->'args'->>'term'))
          payload->'args'->>'term'                 AS term,
          payload->'args'->>'proposed_definition'  AS proposed_definition,
          payload->'args'->>'source_hash'          AS source_hash,
          encode(hash, 'hex')                      AS hash_hex,
          seq
        FROM ledger
        WHERE company_id = $1
          AND kind = 'execute'
          AND payload->>'tool' = 'emit_business_def_proposed'
          AND payload->'args'->>'term' IS NOT NULL
        ORDER BY lower(payload->'args'->>'term'), seq DESC
      ),
      confirmed AS (
        SELECT DISTINCT lower(payload->'args'->>'term') AS term_l
          FROM ledger
         WHERE company_id = $1
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_business_def_confirmed'
      )
      SELECT p.term, p.proposed_definition, p.source_hash, p.hash_hex
        FROM proposed p
       WHERE lower(p.term) NOT IN (SELECT term_l FROM confirmed)
       ORDER BY p.term
    `;
    const res = await pgQuery<{
      term: string;
      proposed_definition: string | null;
      source_hash: string | null;
      hash_hex: string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) {
      warnOnce(
        "business-defs-empty",
        "no business_def_proposed entries; returning empty list",
      );
      return [];
    }

    return res.rows.map((r): BusinessDefProposal => ({
      term: r.term,
      proposedDefinition:
        r.proposed_definition ?? `(definition pending for ${r.term})`,
      sourceHash:
        r.source_hash ?? r.hash_hex.slice(0, 12),
    }));
  }, []);
}

/**
 * Ontology seeds — these live in static YAML files under
 * `packages/ontology-seed/` (loaded by the Python `wormbase_ontology_seed`
 * package) rather than the ledger. There's no projection event, so we keep
 * this on the curated fixture; that fixture is hand-aligned with the seed
 * pack the worm-core warmup uses.
 */
export async function getOntologySeeds(
  _companyId: string = DEFAULT_COMPANY_ID
): Promise<OntologySeed[]> {
  warnOnce(
    "ontology-seeds-static",
    "ontology seeds come from static YAML, not the ledger; using fixtures",
  );
  return ONTOLOGY_SEEDS;
}

/**
 * PII patterns.
 *
 * Live source: `emit_pii_pattern_added` (added by the policy pack). Returns
 * `[]` when no such entries exist — the dashboard surfaces an honest "no
 * PII patterns active yet" empty state instead of pretending the default
 * pack is loaded.
 */
export async function getPiiPatterns(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<PiiPattern[]> {
  return tryPg(async () => {
    const sql = `
      SELECT DISTINCT ON (payload->'args'->>'pattern_id')
        payload->'args'->>'pattern_id'  AS pattern_id,
        payload->'args'->>'label'       AS label,
        payload->'args'->>'regex'       AS regex,
        payload->'args'->>'enabled'     AS enabled
      FROM ledger
      WHERE company_id = $1
        AND kind = 'execute'
        AND payload->>'tool' = 'emit_pii_pattern_added'
        AND payload->'args'->>'pattern_id' IS NOT NULL
      ORDER BY payload->'args'->>'pattern_id', seq DESC
    `;
    const res = await pgQuery<{
      pattern_id: string;
      label: string | null;
      regex: string | null;
      enabled: string | null;
    }>(sql, [companyId]);

    if (res.rows.length === 0) {
      warnOnce(
        "pii-patterns-empty",
        "no pii_pattern_added entries; returning empty list",
      );
      return [];
    }

    return res.rows.map((r): PiiPattern => ({
      patternId: r.pattern_id,
      label: r.label ?? r.pattern_id,
      regex: r.regex ?? ".*",
      enabled: r.enabled === "true" || r.enabled === "1",
    }));
  }, []);
}

/**
 * Conversations — last N chat_received rows across all channels for the
 * tenant. Each row becomes a single ConversationMessage. The channel name
 * is rendered as the raw channel_id today; once `emit_channel_registered`
 * is wired upstream the resolver folds in the human-readable channel name
 * from that projection.
 */
export async function getConversations(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<ConversationMessage[]> {
  return tryPg(async () => {
    const sql = `
      SELECT ts,
             payload->'args'->>'channel_id'    AS channel_id,
             payload->'args'->>'sender_person' AS sender_person,
             payload->'args'->>'text'          AS text,
             payload->'args'->>'classification' AS classification,
             encode(hash, 'hex')                AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_chat_received',
           'channel_adapter.emit_chat_received'
         )
       ORDER BY seq DESC
       LIMIT 50
    `;
    const res = await pgQuery<{
      ts: Date | string;
      channel_id: string | null;
      sender_person: string | null;
      text: string | null;
      classification: string | null;
      hash_hex: string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): ConversationMessage => {
      const ts = r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString();
      const author = r.sender_person ? `person:${r.sender_person.slice(0, 8)}` : "unknown";
      const channel = r.channel_id ?? "(channel)";
      const classification = r.classification ?? "internal";
      return {
        ts,
        channel,
        author,
        text: r.text ?? "",
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: channel,
          owner: author,
          classification,
        },
      };
    });
  }, []);
}

/**
 * Tasks.
 *
 * No `emit_task_proposed` / `emit_task_status` tool exists upstream yet —
 * the worm-core does not currently surface task entries. Until those
 * tools land we return an empty list so the /activity surface renders an
 * honest empty state instead of fixture rows. A future subagent should:
 *   1. add `emit_task_proposed` + `emit_task_status` tools to worm-core,
 *   2. update this query to fold them into TaskRow shape.
 */
export async function getTasks(
  _companyId: string = DEFAULT_COMPANY_ID
): Promise<TaskRow[]> {
  warnOnce(
    "tasks-no-upstream",
    "no emit_task_proposed entries upstream; tasks panel empty until wired",
  );
  return [];
}

/**
 * Insights.
 *
 * Same story as tasks — no `emit_insight_proposed` tool exists upstream.
 * Return an empty list so the surface stays honest about what's wired.
 */
export async function getInsights(
  _companyId: string = DEFAULT_COMPANY_ID
): Promise<InsightCard[]> {
  warnOnce(
    "insights-no-upstream",
    "no emit_insight_proposed entries upstream; insights panel empty until wired",
  );
  return [];
}

// ─── Step 3c: process retrieval ──────────────────────────────────────────
//
// Read folds for the four payloads written by
// `apps/worm-core/src/wormbase_core/process_extractor.py`:
//   * emit_decision_recorded     → /decisions
//   * emit_process_map_proposed  → /processes
//   * emit_system_map_node       → /system-map
//   * emit_recurring_question    → /decisions sidebar (and future surfaces)
//
// Live-only: there's no fixture fallback for these — they're brand-new
// surfaces specifically for showing what the worm has extracted from the
// conversation lake during a demo run. Empty-ledger ⇒ empty page (with a
// helpful "no decisions extracted yet" hint rendered by the page).

interface DecisionArgs {
  decision_id: string;
  decision_text: string;
  decision_at: string;
  channel_id: string;
  decided_by_persons?: string[];
  evidence_message_ids?: string[];
  confidence?: number | string;
}

export async function getDecisions(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<DecisionRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT DISTINCT ON (payload->'args'->>'decision_id')
             payload->'args' AS args,
             ts,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_decision_recorded'
         AND payload->'args'->>'decision_id' IS NOT NULL
       ORDER BY payload->'args'->>'decision_id', seq DESC
    `;
    const res = await pgQuery<{
      args: DecisionArgs;
      ts: Date | string;
      hash_hex: string;
    }>(sql, [companyId]);

    const rows = res.rows.map((r): DecisionRow => {
      const a = r.args ?? ({ decision_id: "" } as DecisionArgs);
      const conf =
        typeof a.confidence === "number"
          ? a.confidence
          : typeof a.confidence === "string"
            ? Number(a.confidence)
            : 0.5;
      return {
        decisionId: a.decision_id,
        decisionText: a.decision_text ?? "(no text)",
        decisionAt: a.decision_at ?? (
          r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString()
        ),
        channelId: a.channel_id ?? "(unknown)",
        decidedByPersons: Array.isArray(a.decided_by_persons)
          ? a.decided_by_persons : [],
        evidenceMessageIds: Array.isArray(a.evidence_message_ids)
          ? a.evidence_message_ids : [],
        confidence: Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : 0.5,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: a.channel_id ?? "process-extractor",
          owner: "worm",
          classification: "internal",
        },
      };
    });
    // Newest decisions first.
    rows.sort((a, b) => b.decisionAt.localeCompare(a.decisionAt));
    return rows;
  }, []);
}

interface ProcessMapArgs {
  process_id: string;
  process_name?: string;
  steps?: Array<{
    order?: number;
    actor?: string;
    action?: string;
    source_message_id?: string;
  }>;
  domain?: string;
  confidence?: number | string;
}

export async function getProcessMaps(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<ProcessMapRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT DISTINCT ON (payload->'args'->>'process_id')
             payload->'args' AS args,
             ts,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_process_map_proposed'
         AND payload->'args'->>'process_id' IS NOT NULL
       ORDER BY payload->'args'->>'process_id', seq DESC
    `;
    const res = await pgQuery<{
      args: ProcessMapArgs;
      ts: Date | string;
      hash_hex: string;
    }>(sql, [companyId]);

    return res.rows.map((r): ProcessMapRow => {
      const a = r.args ?? ({ process_id: "" } as ProcessMapArgs);
      const steps: ProcessStep[] = Array.isArray(a.steps)
        ? a.steps.map((s, i) => ({
            order: typeof s.order === "number" ? s.order : i + 1,
            actor: s.actor ?? "",
            action: s.action ?? "",
            sourceMessageId: s.source_message_id ?? "",
          }))
        : [];
      const conf =
        typeof a.confidence === "number"
          ? a.confidence
          : typeof a.confidence === "string"
            ? Number(a.confidence)
            : 0.5;
      const proposedAt =
        r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString();
      return {
        processId: a.process_id,
        processName: a.process_name ?? "process",
        steps,
        domain: a.domain ?? "general",
        confidence: Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : 0.5,
        proposedAt,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "process-extractor",
          owner: "worm",
          classification: "internal",
        },
      };
    });
  }, []);
}

interface SystemMapArgs {
  node_kind?: "person" | "channel" | "role";
  node_id: string;
  edges?: Array<{ kind?: string; target_id?: string; weight?: number | string }>;
}

export async function getSystemMap(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<SystemMapPayload> {
  return tryPg(async () => {
    // Collapse to the latest node_kind+node_id pair so a node's edges
    // reflect the most recent flush.
    const sql = `
      SELECT DISTINCT ON (
               payload->'args'->>'node_kind',
               payload->'args'->>'node_id'
             )
             payload->'args' AS args,
             ts,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_system_map_node'
       ORDER BY payload->'args'->>'node_kind',
                payload->'args'->>'node_id',
                seq DESC
    `;
    const res = await pgQuery<{
      args: SystemMapArgs;
      ts: Date | string;
      hash_hex: string;
    }>(sql, [companyId]);

    const nodes: SystemMapNode[] = res.rows.map((r) => {
      const a = r.args ?? ({ node_id: "" } as SystemMapArgs);
      const edges: SystemMapEdge[] = Array.isArray(a.edges)
        ? a.edges.map((e) => ({
            kind: e.kind ?? "edge",
            targetId: e.target_id ?? "",
            weight:
              typeof e.weight === "number"
                ? e.weight
                : typeof e.weight === "string"
                  ? Number(e.weight) || 0
                  : 0,
          }))
        : [];
      return {
        nodeKind: (a.node_kind ?? "person") as SystemMapNode["nodeKind"],
        nodeId: a.node_id,
        edges,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "process-extractor",
          owner: "worm",
          classification: "internal",
        },
      };
    });

    const generatedAt = res.rows.length
      ? res.rows[0].ts instanceof Date
        ? res.rows[0].ts.toISOString()
        : new Date(res.rows[0].ts).toISOString()
      : null;
    return { nodes, generatedAt };
  }, { nodes: [], generatedAt: null });
}

interface RecurringQuestionArgs {
  question_id: string;
  normalized_question?: string;
  asked_by_persons?: string[];
  occurrences?: number | string;
  first_seen_at?: string;
  last_seen_at?: string;
  suggested_automation?: string | null;
}

export async function getRecurringQuestions(
  companyId: string = DEFAULT_COMPANY_ID
): Promise<RecurringQuestionRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT DISTINCT ON (payload->'args'->>'question_id')
             payload->'args' AS args,
             encode(hash, 'hex') AS hash_hex
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_recurring_question'
         AND payload->'args'->>'question_id' IS NOT NULL
       ORDER BY payload->'args'->>'question_id', seq DESC
    `;
    const res = await pgQuery<{
      args: RecurringQuestionArgs;
      hash_hex: string;
    }>(sql, [companyId]);

    const rows = res.rows.map((r): RecurringQuestionRow => {
      const a = r.args ?? ({ question_id: "" } as RecurringQuestionArgs);
      const occRaw =
        typeof a.occurrences === "number"
          ? a.occurrences
          : typeof a.occurrences === "string"
            ? Number(a.occurrences)
            : 0;
      return {
        questionId: a.question_id,
        normalizedQuestion: a.normalized_question ?? "(unknown question)",
        askedByPersons: Array.isArray(a.asked_by_persons)
          ? a.asked_by_persons : [],
        occurrences: Number.isFinite(occRaw) && occRaw > 0 ? occRaw : 1,
        firstSeenAt: a.first_seen_at ?? "",
        lastSeenAt: a.last_seen_at ?? "",
        suggestedAutomation: a.suggested_automation ?? null,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "process-extractor",
          owner: "worm",
          classification: "internal",
        },
      };
    });
    rows.sort((a, b) => b.occurrences - a.occurrences);
    return rows;
  }, []);
}

// ─── Writes ──────────────────────────────────────────────────────────────

/**
 * Construct a synthetic Receipt for a write that hasn't yet been forwarded
 * to worm-core. Used by the write-audit toast so the user sees an immediate
 * confirmation; the real Receipt arrives via the SSE trace stream within the
 * 400ms Q1 budget.
 *
 * The hash is the first 12 chars of a deterministic content hash of the
 * write payload — same payload, same hash. This is the contract the QA
 * agent's contract test pins.
 */
export function syntheticReceipt(opts: {
  kind: string;
  source: string;
  owner: string;
  classification: string;
  payload: Record<string, unknown>;
}): Receipt & { ts: string } {
  const seed = JSON.stringify({ k: opts.kind, p: opts.payload });
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  }
  const hash = h.toString(16).padStart(12, "0").slice(0, 12);
  return {
    hash,
    source: opts.source,
    owner: opts.owner,
    classification: opts.classification,
    ts: new Date().toISOString(),
  };
}

export async function upsertChannelTalkativeness(
  _companyId: string,
  channelId: string,
  talkativeness: Talkativeness
): Promise<Receipt & { ts: string }> {
  return syntheticReceipt({
    kind: "policy_applied",
    source: "channel-policy-v1",
    owner: "ricardo",
    classification: "internal",
    payload: { channelId, talkativeness, policy_id: "channel_talkativeness_v1" },
  });
}

export async function confirmBusinessDef(
  _companyId: string,
  term: string
): Promise<Receipt & { ts: string }> {
  return syntheticReceipt({
    kind: "concept_confirmed",
    source: "onboarding · tier 2",
    owner: "ricardo",
    classification: "internal",
    payload: { term },
  });
}

export async function rejectBusinessDef(
  _companyId: string,
  term: string
): Promise<Receipt & { ts: string }> {
  return syntheticReceipt({
    kind: "concept_rejected",
    source: "onboarding · tier 2",
    owner: "ricardo",
    classification: "internal",
    payload: { term },
  });
}

export async function setPiiPattern(
  _companyId: string,
  patternId: string,
  enabled: boolean
): Promise<Receipt & { ts: string }> {
  return syntheticReceipt({
    kind: "policy_applied",
    source: "policy-pack-v1",
    owner: "ricardo",
    classification: "pii",
    payload: { patternId, enabled, policy_id: "pii_redaction" },
  });
}

/**
 * Domain owner assignment write.
 *
 * Tries the live PEVR cycle (propose → execute → verify → resolve) against
 * the ledger when Postgres is reachable; falls back to a synthetic receipt
 * otherwise. The execute entry uses the canonical
 * `emit_domain_owner_assigned` tool name so the read-side `getDomains()`
 * picks the new owner up on the next poll (W2.C live-polling effect).
 */
export async function assignDomainOwner(
  companyId: string,
  domainId: string,
  personId: string
): Promise<Receipt & { ts: string }> {
  const synthetic = syntheticReceipt({
    kind: "domain_assigned",
    source: "domains",
    owner: "ricardo",
    classification: "internal",
    payload: { domainId, personId },
  });
  await tryPgWrite(async () => {
    const sql = `
      INSERT INTO ledger (company_id, kind, ts, payload)
      VALUES ($1, 'execute', now(), $2::jsonb)
    `;
    await pgQuery(sql, [
      companyId,
      JSON.stringify({
        tool: "emit_domain_owner_assigned",
        actor: "dashboard",
        summary: `Domain ${domainId} owner → ${personId}`,
        args: {
          id: domainId,
          domain_id: domainId,
          owner_person_id: personId,
          classification: "internal",
        },
      }),
    ]);
  });
  return synthetic;
}

/**
 * Policy classification re-emit. Writes an `emit_policy_applied` execute
 * entry with the new classification; the read-side picks up the latest one
 * (DISTINCT ON in `getPolicies`). Falls back to a synthetic receipt when
 * Postgres is unreachable so the dashboard's optimistic UI still gets a
 * receipt to display.
 */
export async function applyPolicyClassification(
  companyId: string,
  policyId: string,
  classification: string
): Promise<Receipt & { ts: string }> {
  const synthetic = syntheticReceipt({
    kind: "policy_applied",
    source: "policy-pack-v1",
    owner: "dashboard",
    classification,
    payload: { policy_id: policyId, classification },
  });
  await tryPgWrite(async () => {
    const sql = `
      INSERT INTO ledger (company_id, kind, ts, payload)
      VALUES ($1, 'execute', now(), $2::jsonb)
    `;
    await pgQuery(sql, [
      companyId,
      JSON.stringify({
        tool: "emit_policy_applied",
        actor: "dashboard",
        summary: `Policy ${policyId} classification → ${classification}`,
        args: {
          policy_id: policyId,
          policy_name: policyId,
          classification,
        },
      }),
    ]);
  });
  return synthetic;
}

/**
 * Best-effort write helper: if Postgres is reachable, run the writer; if
 * not (or if it throws), swallow and continue. The synthetic receipt has
 * already been generated by the caller — the optimistic UI is the user's
 * confirmation, the live entry is the audience-visible "live ledger"
 * effect when the demo backend is up.
 */
export async function tryPgWrite(write: () => Promise<void>): Promise<void> {
  if (!postgresEnabled()) return;
  const pool = await getPool();
  if (!pool) return;
  try {
    await write();
  } catch (err) {
    warnOnce(
      `write:${(err as Error).name}`,
      `Postgres write failed: ${(err as Error).message}`,
    );
  }
}

export async function proposeSource(
  _companyId: string,
  uri: string,
  owner: string,
  classification: string,
  credentialRef?: string | null
): Promise<Receipt & { ts: string }> {
  /**
   * ``credentialRef`` (additive 2026-06-10, default ``undefined`` =
   * ``null`` on the wire): the operator-provisioned broker slot key
   * that the worm-core ``LedgerSourceHandleProvider`` will hand to
   * :meth:`CredentialBroker.hold_data_account` at sampling time. Only
   * meaningful for opaque-secret connector kinds (stripe / salesforce /
   * hubspot / gsheets); URI-shaped kinds ignore it. The dashboard
   * ``CredentialRefInput`` component captures this from the operator
   * when an opaque-secret kind is configured.
   *
   * The receipt currently captures the credential_ref alongside the
   * other proposal payload fields. When the dashboard route is
   * upgraded to call ``SourceBuilder.connect()`` end-to-end (rather
   * than synthesising a receipt), the credential_ref will thread
   * directly into ``SourceConnectedPayload.credential_ref`` — same
   * shape the worm-core source_builder already accepts.
   */
  const payload: Record<string, unknown> = {
    uri,
    owner,
    classification,
    flow: "dashboard_form",
  };
  if (credentialRef) {
    payload.credential_ref = credentialRef;
  }
  return syntheticReceipt({
    kind: "source_proposed",
    source: uri,
    owner,
    classification,
    payload,
  });
}

export async function setOntologySeed(
  _companyId: string,
  concept: string,
  enabled: boolean
): Promise<Receipt & { ts: string }> {
  return syntheticReceipt({
    kind: enabled ? "concept_confirmed" : "concept_rejected",
    source: "ontology-seed",
    owner: "ricardo",
    classification: "internal",
    payload: { concept, enabled },
  });
}

// ─── Step 2 (proactivity hook): time-to-aha gauge ───────────────────────────
//
// Returns the six canonical onboarding milestones, derived live from the
// ledger via a single SQL query. Falls back to all-null milestones (NOT
// fixtures) when Postgres is offline — the panel renders "pending" nodes
// gray so the demo audience sees the actual real-time progress.
//
// Milestone derivations:
//   installAt           — first ``emit_memory_written`` whose
//                         args.content == "company_warmup_completed"
//   firstSourceAt       — first ``emit_source_proposed``
//   firstConceptAt      — first ``concept_confirmed`` execute, or first
//                         ``emit_memory_written`` tagged "domain_owner_assigned"
//   firstGoldAt         — first ``emit_source_golded`` or ``emit_kpi_proposed``
//   firstProcessMapAt   — first ``emit_process_map_proposed`` or
//                         ``emit_recurring_question``
//   firstExperimentAt   — first ``heuristic_experiment`` execute (the
//                         autoresearch-loop primitive)

const _EMPTY_MILESTONES: OnboardingMilestones = {
  installAt: null,
  firstSourceAt: null,
  firstConceptAt: null,
  firstGoldAt: null,
  firstProcessMapAt: null,
  firstExperimentAt: null,
};

function _isoOrNull(v: Date | string | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "string") {
    // Postgres returns "YYYY-MM-DD HH:MM:SS+TZ"; normalise to ISO-8601.
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
  }
  return null;
}

export async function getOnboardingMilestones(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<OnboardingMilestones> {
  return tryPg(async () => {
    const sql = `
      SELECT
        MIN(CASE
          WHEN payload->>'tool' = 'emit_memory_written'
            AND payload->'args'->>'content' = 'company_warmup_completed'
          THEN ts END) AS install_at,
        MIN(CASE
          WHEN payload->>'tool' = 'emit_source_proposed'
          THEN ts END) AS first_source_at,
        MIN(CASE
          WHEN kind = 'execute'
            AND (
              payload->>'tool' = 'concept_confirmed'
              OR (
                payload->>'tool' = 'emit_memory_written'
                AND payload->'args'->>'content' = 'domain_owner_assigned'
              )
            )
          THEN ts END) AS first_concept_at,
        MIN(CASE
          WHEN payload->>'tool' IN ('emit_source_golded', 'emit_kpi_proposed')
          THEN ts END) AS first_gold_at,
        MIN(CASE
          WHEN payload->>'tool' IN (
            'emit_process_map_proposed',
            'emit_recurring_question'
          )
          THEN ts END) AS first_process_map_at,
        MIN(CASE
          WHEN payload->>'tool' = 'emit_heuristic_experiment'
          THEN ts END) AS first_experiment_at
      FROM ledger
      WHERE company_id = $1
        AND kind = 'execute'
    `;
    const res = await pgQuery<{
      install_at: Date | string | null;
      first_source_at: Date | string | null;
      first_concept_at: Date | string | null;
      first_gold_at: Date | string | null;
      first_process_map_at: Date | string | null;
      first_experiment_at: Date | string | null;
    }>(sql, [companyId]);
    if (res.rows.length === 0) return _EMPTY_MILESTONES;
    const row = res.rows[0];
    return {
      installAt: _isoOrNull(row.install_at),
      firstSourceAt: _isoOrNull(row.first_source_at),
      firstConceptAt: _isoOrNull(row.first_concept_at),
      firstGoldAt: _isoOrNull(row.first_gold_at),
      firstProcessMapAt: _isoOrNull(row.first_process_map_at),
      firstExperimentAt: _isoOrNull(row.first_experiment_at),
    };
  }, _EMPTY_MILESTONES);
}

// ─── Step 5: user structure + per-user autoresearch ─────────────────────
//
// Read folds for the eight new payloads written by
// `apps/worm-core/src/wormbase_core/autoresearch_loop.py` plus the
// `emit_person_registered` / `emit_position_assigned` writes from the
// onboarding wizard. Live-only — no fixture fallback (the /research tab
// renders an explicit empty state when no experiments have been run yet).
//
//   * getPositionsRegistry            → /api/positions, /research roster
//   * getResearchOverview             → /research per-tenant card
//   * getExperimentsForUser           → /research per-user table
//   * getHeadlineMetricsHistory       → /research sparkline series

interface PersonRegisteredArgs {
  person_id: string;
  name?: string;
  email?: string;
  role?: string;
  registered_at?: string;
}

interface PositionAssignedArgs {
  person_id: string;
  position: string;
  at?: string;
  assigned_by_person_id?: string;
}

interface ExperimentProposedArgs {
  experiment_id: string;
  for_person_id: string;
  position: string;
  headline_metric: string;
  proposed_change?: Record<string, unknown>;
  expected_delta?: number | string;
  proposed_at?: string;
}

interface ExperimentRunArgs {
  experiment_id: string;
  started_at?: string;
  finished_at?: string;
  log?: Record<string, unknown>;
}

interface ExperimentResolvedArgs {
  experiment_id: string;
  outcome?: ExperimentOutcome;
  observed_delta?: number | string;
  rationale?: string;
  resolved_at?: string;
}

interface MetricObservedArgs {
  metric_id: string;
  position: string;
  value?: number | string;
  observed_at?: string;
}

function _toNumber(v: unknown, fallback = 0): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }
  return fallback;
}

/**
 * Joined Person × Position registry per tenant.
 *
 * The latest emit_position_assigned for each person wins; person details
 * come from emit_person_registered (falls back to the person uuid if no
 * registration row was ever written).
 */
export async function getPositionsRegistry(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<PositionRegistryRow[]> {
  return tryPg(async () => {
    const sql = `
      WITH latest_position AS (
        SELECT DISTINCT ON (payload->'args'->>'person_id')
               payload->'args'                AS args,
               ts,
               encode(hash, 'hex')            AS hash_hex,
               seq
          FROM ledger
         WHERE company_id = $1
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_position_assigned'
           AND payload->'args'->>'person_id' IS NOT NULL
         ORDER BY payload->'args'->>'person_id', seq DESC
      ),
      person_details AS (
        SELECT DISTINCT ON (payload->'args'->>'person_id')
               payload->'args' AS args,
               seq
          FROM ledger
         WHERE company_id = $1
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_person_registered'
           AND payload->'args'->>'person_id' IS NOT NULL
         ORDER BY payload->'args'->>'person_id', seq DESC
      )
      SELECT lp.args   AS position_args,
             lp.ts     AS position_ts,
             lp.hash_hex,
             pd.args   AS person_args
        FROM latest_position lp
   LEFT JOIN person_details pd
          ON pd.args->>'person_id' = lp.args->>'person_id'
       ORDER BY lp.args->>'person_id'
    `;
    const res = await pgQuery<{
      position_args: PositionAssignedArgs;
      position_ts: Date | string;
      hash_hex: string;
      person_args: PersonRegisteredArgs | null;
    }>(sql, [companyId]);

    return res.rows.map((r): PositionRegistryRow => {
      const pos = r.position_args ?? { person_id: "", position: "" };
      const person = r.person_args ?? null;
      const personId = pos.person_id;
      const displayName =
        person?.name ?? person?.email ?? `person:${personId.slice(0, 8)}`;
      const assignedAt =
        pos.at ??
        (r.position_ts instanceof Date
          ? r.position_ts.toISOString()
          : new Date(r.position_ts).toISOString());
      return {
        personId,
        displayName,
        position: pos.position,
        email: person?.email ?? null,
        role: person?.role ?? "member",
        assignedAt,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "positions-projection",
          owner: personId,
          classification: "internal",
        },
      };
    });
  }, []);
}

/**
 * Folded experiment rows.
 *
 * Each experiment_id collects propose + (optional) run + (optional)
 * resolved into a single ExperimentRow. Optionally filter by person_id
 * (for the /research per-user view).
 */
export async function getExperimentsForUser(
  companyId: string = DEFAULT_COMPANY_ID,
  personId?: string,
  limit = 100,
): Promise<ExperimentRow[]> {
  const fallback: ExperimentRow[] = [];
  return tryPg(async () => {
    const params: unknown[] = [companyId];
    let personFilter = "";
    if (personId) {
      params.push(personId);
      personFilter = `AND payload->'args'->>'for_person_id' = $${params.length}`;
    }
    const proposedSql = `
      SELECT DISTINCT ON (payload->'args'->>'experiment_id')
             payload->'args' AS args,
             ts,
             encode(hash, 'hex') AS hash_hex,
             seq
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_experiment_proposed'
         AND payload->'args'->>'experiment_id' IS NOT NULL
         ${personFilter}
       ORDER BY payload->'args'->>'experiment_id', seq DESC
    `;
    const proposedRes = await pgQuery<{
      args: ExperimentProposedArgs;
      ts: Date | string;
      hash_hex: string;
      seq: number | string;
    }>(proposedSql, params);

    if (proposedRes.rows.length === 0) return fallback;

    const ids = proposedRes.rows.map((r) => r.args.experiment_id);
    const idsParam = ids;
    const runSql = `
      SELECT DISTINCT ON (payload->'args'->>'experiment_id')
             payload->'args' AS args
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_experiment_run'
         AND payload->'args'->>'experiment_id' = ANY($2::text[])
       ORDER BY payload->'args'->>'experiment_id', seq DESC
    `;
    const resolvedSql = `
      SELECT DISTINCT ON (payload->'args'->>'experiment_id')
             payload->'args' AS args
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_experiment_resolved'
         AND payload->'args'->>'experiment_id' = ANY($2::text[])
       ORDER BY payload->'args'->>'experiment_id', seq DESC
    `;
    const [runRes, resolvedRes] = await Promise.all([
      pgQuery<{ args: ExperimentRunArgs }>(runSql, [companyId, idsParam]),
      pgQuery<{ args: ExperimentResolvedArgs }>(resolvedSql, [companyId, idsParam]),
    ]);

    const runs = new Map<string, ExperimentRunArgs>();
    for (const r of runRes.rows) runs.set(r.args.experiment_id, r.args);
    const resolved = new Map<string, ExperimentResolvedArgs>();
    for (const r of resolvedRes.rows) resolved.set(r.args.experiment_id, r.args);

    const rows: ExperimentRow[] = proposedRes.rows.map((r) => {
      const a = r.args;
      const run = runs.get(a.experiment_id) ?? null;
      const res = resolved.get(a.experiment_id) ?? null;
      const proposedAt =
        a.proposed_at ??
        (r.ts instanceof Date
          ? r.ts.toISOString()
          : new Date(r.ts).toISOString());
      const outcome: ExperimentOutcome | null =
        res?.outcome === "keep" || res?.outcome === "discard"
          ? res.outcome
          : null;
      return {
        experimentId: a.experiment_id,
        forPersonId: a.for_person_id,
        position: a.position,
        headlineMetric: a.headline_metric,
        proposedChange: (a.proposed_change ?? {}) as Record<string, unknown>,
        expectedDelta: _toNumber(a.expected_delta, 0),
        proposedAt,
        runLog: (run?.log ?? null) as Record<string, unknown> | null,
        startedAt: run?.started_at ?? null,
        finishedAt: run?.finished_at ?? null,
        outcome,
        observedDelta: res ? _toNumber(res.observed_delta, 0) : null,
        rationale: res?.rationale ?? null,
        resolvedAt: res?.resolved_at ?? null,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "autoresearch_loop",
          owner: a.for_person_id,
          classification: "internal",
        },
      };
    });
    rows.sort((x, y) => y.proposedAt.localeCompare(x.proposedAt));
    return rows.slice(0, Math.max(1, limit));
  }, fallback);
}

/**
 * Tenant-wide research overview.
 *
 * Aggregates experiment counts + win rate; computes "top movers" by
 * summing observed_delta per (position, metric) for kept experiments.
 */
export async function getResearchOverview(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<ResearchOverview> {
  const empty: ResearchOverview = {
    totalExperiments: 0,
    totalKept: 0,
    totalDiscarded: 0,
    winRate: null,
    topMovers: [],
    latestExperiments: [],
  };
  return tryPg(async () => {
    const all = await getExperimentsForUser(companyId, undefined, 200);
    if (all.length === 0) return empty;
    const totalExperiments = all.length;
    const totalKept = all.filter((e) => e.outcome === "keep").length;
    const totalDiscarded = all.filter((e) => e.outcome === "discard").length;
    const decided = totalKept + totalDiscarded;
    const winRate = decided > 0 ? totalKept / decided : null;

    const moverAgg = new Map<string, PositionMover>();
    for (const e of all) {
      const key = `${e.position}::${e.headlineMetric}`;
      const cur = moverAgg.get(key) ?? {
        position: e.position,
        metricId: e.headlineMetric,
        delta: 0,
        experimentsKept: 0,
        experimentsDiscarded: 0,
      };
      if (e.outcome === "keep") {
        cur.experimentsKept += 1;
        if (e.observedDelta !== null) cur.delta += e.observedDelta;
      } else if (e.outcome === "discard") {
        cur.experimentsDiscarded += 1;
      }
      moverAgg.set(key, cur);
    }
    const topMovers = Array.from(moverAgg.values())
      .filter((m) => m.experimentsKept > 0)
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, 5);

    return {
      totalExperiments,
      totalKept,
      totalDiscarded,
      winRate,
      topMovers,
      latestExperiments: all.slice(0, 10),
    };
  }, empty);
}

/**
 * Time-series of headline metric samples for one position.
 *
 * Used by the per-user sparkline on /research. Caller picks the
 * metric_id (defaults to the canonical headline metric for the
 * position, derived in worm-core).
 */
export async function getHeadlineMetricsHistory(
  companyId: string = DEFAULT_COMPANY_ID,
  position: string,
  metricId?: string,
  limit = 50,
): Promise<HeadlineMetricSeries> {
  const fallback: HeadlineMetricSeries = {
    position,
    metricId: metricId ?? "(unknown)",
    points: [],
  };
  return tryPg(async () => {
    const params: unknown[] = [companyId, position];
    let metricFilter = "";
    if (metricId) {
      params.push(metricId);
      metricFilter = `AND payload->'args'->>'metric_id' = $${params.length}`;
    }
    const sql = `
      SELECT payload->'args' AS args, ts
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_metric_observed'
         AND payload->'args'->>'position' = $2
         ${metricFilter}
       ORDER BY seq ASC
       LIMIT ${Math.max(1, Math.min(500, limit))}
    `;
    const res = await pgQuery<{
      args: MetricObservedArgs;
      ts: Date | string;
    }>(sql, params);

    if (res.rows.length === 0) return fallback;

    const points: MetricSamplePoint[] = res.rows.map((r) => ({
      observedAt:
        r.args.observed_at ??
        (r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString()),
      value: _toNumber(r.args.value, 0),
    }));
    return {
      position,
      metricId: metricId ?? res.rows[0].args.metric_id ?? fallback.metricId,
      points,
    };
  }, fallback);
}

// ---------------------------------------------------------------------------
// Composite score + per-scope keep-rate (Demo-day P1).
//
// Both folds run TS-side over the ledger row stream returned from Postgres.
// Mirrors `apps/worm-core/src/wormbase_core/projections/composite_score.py`
// and `keep_rate.py`. Replay determinism: the same ledger rows return the
// same series byte-for-byte (modulo ts ordering, which is sorted on read).
// ---------------------------------------------------------------------------

const COMPOSITE_DEFAULT_WEIGHTS = {
  gate_precision: 0.25,
  propose_keep_ratio: 0.25,
  ramp_delta: 0.25,
  reactivity_confirm_rate: 0.25,
} as const;

const COMPOSITE_RAMP_DELTA_CAP = 30;
const COMPOSITE_NEUTRAL_RATIO = 0.5;
const KEEP_RATE_SYNTHETIC_THRESHOLD = 3;

interface CompositeRow {
  seq: number;
  kind: string;
  ts: string;
  payload: { tool?: string; args?: Record<string, unknown>; [k: string]: unknown };
}

async function _fetchCompositeRows(companyId: string): Promise<CompositeRow[]> {
  const sql = `
    SELECT seq, kind, ts, payload
      FROM ledger
     WHERE company_id = $1
     ORDER BY seq ASC
  `;
  const res = await pgQuery<{
    seq: number | string;
    kind: string;
    ts: Date | string;
    payload: CompositeRow["payload"];
  }>(sql, [companyId]);
  return res.rows.map((r) => ({
    seq: typeof r.seq === "string" ? parseInt(r.seq, 10) : r.seq,
    kind: r.kind,
    ts: r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString(),
    payload: r.payload ?? {},
  }));
}

function _isExecuteWithTool(row: CompositeRow, tool: string): boolean {
  return row.kind === "execute" && row.payload?.tool === tool;
}

function _gatePrecision(rowsInWindow: CompositeRow[]): number {
  const allowed = rowsInWindow.filter(
    (r) => r.kind === "gate_fired" && r.payload?.outcome === "allowed",
  );
  if (allowed.length === 0) return COMPOSITE_NEUTRAL_RATIO;
  const kept = new Set<string>();
  const discarded = new Set<string>();
  for (const r of rowsInWindow) {
    if (!_isExecuteWithTool(r, "emit_experiment_resolved")) continue;
    const args = (r.payload?.args ?? {}) as Record<string, unknown>;
    const eid = String(args.experiment_id ?? "");
    if (!eid) continue;
    if (args.outcome === "keep") kept.add(eid);
    else if (args.outcome === "discard") discarded.add(eid);
  }
  let upheld = 0;
  let rejected = 0;
  for (const g of allowed) {
    const subj = String(g.payload?.subject_ref ?? "");
    if (kept.has(subj)) upheld += 1;
    else if (discarded.has(subj)) rejected += 1;
  }
  const total = upheld + rejected;
  return total === 0 ? COMPOSITE_NEUTRAL_RATIO : upheld / total;
}

function _proposeKeepRatio(rowsInWindow: CompositeRow[]): number {
  let kept = 0;
  let discarded = 0;
  for (const r of rowsInWindow) {
    if (!_isExecuteWithTool(r, "emit_experiment_resolved")) continue;
    const outcome = (r.payload?.args as Record<string, unknown>)?.outcome;
    if (outcome === "keep") kept += 1;
    else if (outcome === "discard") discarded += 1;
  }
  const total = kept + discarded;
  return total === 0 ? COMPOSITE_NEUTRAL_RATIO : kept / total;
}

function _rampDelta(rowsInWindow: CompositeRow[]): number {
  let inc = 0;
  for (const r of rowsInWindow) {
    if (r.kind === "chat_received") inc += 1;
    else if (_isExecuteWithTool(r, "emit_memory_written")) inc += 1;
    else if (_isExecuteWithTool(r, "emit_kpi_proposed")) inc += 1;
  }
  if (inc <= 0) return 0;
  return Math.min(1, inc / COMPOSITE_RAMP_DELTA_CAP);
}

function _reactivityConfirmRate(rowsInWindow: CompositeRow[]): number {
  const proposed = new Set<string>();
  const confirmed = new Set<string>();
  for (const r of rowsInWindow) {
    if (_isExecuteWithTool(r, "emit_reactivity_proposed")) {
      const rid = String(
        (r.payload?.args as Record<string, unknown>)?.reactivity_id ?? "",
      );
      if (rid) proposed.add(rid);
    } else if (_isExecuteWithTool(r, "emit_reactivity_confirmed")) {
      const rid = String(
        (r.payload?.args as Record<string, unknown>)?.reactivity_id ?? "",
      );
      if (rid) confirmed.add(rid);
    }
  }
  if (proposed.size === 0) return COMPOSITE_NEUTRAL_RATIO;
  let intersect = 0;
  for (const rid of proposed) if (confirmed.has(rid)) intersect += 1;
  return intersect / proposed.size;
}

function _topContributorReactivity(rowsInWindow: CompositeRow[]): string {
  const counts = new Map<string, number>();
  for (const r of rowsInWindow) {
    if (!_isExecuteWithTool(r, "emit_reactivity_fired")) continue;
    const rid = String(
      (r.payload?.args as Record<string, unknown>)?.reactivity_id ?? "",
    );
    if (rid) counts.set(rid, (counts.get(rid) ?? 0) + 1);
  }
  if (counts.size === 0) return "";
  return [...counts.entries()].sort((a, b) =>
    b[1] !== a[1] ? b[1] - a[1] : a[0].localeCompare(b[0]),
  )[0][0];
}

function _resolveCompositeWeights(rows: CompositeRow[]): {
  gate_precision: number;
  propose_keep_ratio: number;
  ramp_delta: number;
  reactivity_confirm_rate: number;
} {
  let latest: Partial<Record<keyof typeof COMPOSITE_DEFAULT_WEIGHTS, number>> | null = null;
  for (const r of rows) {
    if (!_isExecuteWithTool(r, "emit_composite_score_weights")) continue;
    const args = (r.payload?.args ?? {}) as Record<string, unknown>;
    const partial: Partial<Record<keyof typeof COMPOSITE_DEFAULT_WEIGHTS, number>> = {};
    for (const k of Object.keys(COMPOSITE_DEFAULT_WEIGHTS) as Array<
      keyof typeof COMPOSITE_DEFAULT_WEIGHTS
    >) {
      if (typeof args[k] === "number") partial[k] = args[k] as number;
    }
    if (Object.keys(partial).length > 0) latest = partial;
  }
  const merged = { ...COMPOSITE_DEFAULT_WEIGHTS, ...(latest ?? {}) };
  const total = merged.gate_precision + merged.propose_keep_ratio + merged.ramp_delta + merged.reactivity_confirm_rate;
  if (total <= 0) return { ...COMPOSITE_DEFAULT_WEIGHTS };
  return {
    gate_precision: merged.gate_precision / total,
    propose_keep_ratio: merged.propose_keep_ratio / total,
    ramp_delta: merged.ramp_delta / total,
    reactivity_confirm_rate: merged.reactivity_confirm_rate / total,
  };
}

/**
 * Composite-score series for /research. Returns ≥`points` entries (default 9)
 * sampled at uniform seq strides across the tenant's ledger.
 *
 * Returns an empty `points: []` array when Postgres is unreachable or the
 * ledger is empty (no fixture fallback per CLAUDE.md ¶9 — render the empty
 * state honestly).
 */
export async function getCompositeScoreSeries(
  companyId: string = DEFAULT_COMPANY_ID,
  pointCount = 9,
  windowDays = 7,
): Promise<CompositeScoreSeries> {
  const empty: CompositeScoreSeries = {
    tenantId: companyId,
    points: [],
    windowDays,
    weights: { ...COMPOSITE_DEFAULT_WEIGHTS },
  };
  return tryPg(async () => {
    const rows = await _fetchCompositeRows(companyId);
    if (rows.length === 0) return empty;
    const seqs = rows.map((r) => r.seq);
    const lo = Math.min(...seqs);
    const hi = Math.max(...seqs);
    const want = Math.max(2, pointCount);

    let sampled: number[];
    if (hi === lo) {
      sampled = [hi];
    } else {
      const step = (hi - lo) / (want - 1);
      const set = new Set<number>();
      for (let i = 0; i < want; i += 1) {
        set.add(Math.round(lo + i * step));
      }
      // Pad if rounding collapsed adjacent strides.
      if (set.size < want) {
        for (let s = hi; s >= lo; s -= 1) {
          if (!set.has(s)) {
            set.add(s);
            if (set.size >= want) break;
          }
        }
      }
      sampled = [...set].sort((a, b) => a - b);
    }

    const points: CompositeScorePoint[] = sampled.map((height) => {
      const inScope = rows.filter((r) => r.seq <= height);
      const anchor = new Date(inScope[inScope.length - 1].ts).getTime();
      const cutoff = anchor - windowDays * 86_400_000;
      const inWindow = inScope.filter((r) => new Date(r.ts).getTime() >= cutoff);
      const components = {
        gate_precision: _gatePrecision(inWindow),
        propose_keep_ratio: _proposeKeepRatio(inWindow),
        ramp_delta: _rampDelta(inWindow),
        reactivity_confirm_rate: _reactivityConfirmRate(inWindow),
      };
      const weights = _resolveCompositeWeights(rows.filter((r) => r.seq <= height));
      const score = Math.max(
        0,
        Math.min(
          1,
          components.gate_precision * weights.gate_precision +
            components.propose_keep_ratio * weights.propose_keep_ratio +
            components.ramp_delta * weights.ramp_delta +
            components.reactivity_confirm_rate * weights.reactivity_confirm_rate,
        ),
      );
      const seqsInWindow = inWindow.map((r) => r.seq);
      return {
        ledgerHeight: height,
        ts: new Date(anchor).toISOString(),
        score,
        components,
        topContributorReactivityId: _topContributorReactivity(inWindow),
        contributingSeqLo: seqsInWindow.length > 0 ? Math.min(...seqsInWindow) : height,
        contributingSeqHi: seqsInWindow.length > 0 ? Math.max(...seqsInWindow) : height,
      };
    });

    return {
      tenantId: companyId,
      points,
      windowDays,
      weights: _resolveCompositeWeights(rows),
    };
  }, empty);
}

/**
 * Per-scope per-day keep-rate samples for /research.
 *
 * Reads `metrics_keep_rate_published` ledger entries first (the publisher
 * is authoritative). When fewer rows are present than requested days * 3
 * scopes, the gap is *not* fabricated — empty days simply omit the
 * (scope, day) pair and the chart renders the gap honestly.
 */
export async function getKeepRateSeries(
  companyId: string = DEFAULT_COMPANY_ID,
  days = 7,
): Promise<KeepRateSample[]> {
  const fallback: KeepRateSample[] = [];
  return tryPg(async () => {
    const sql = `
      SELECT payload->'args' AS args
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_metrics_keep_rate_published'
       ORDER BY seq ASC
    `;
    const res = await pgQuery<{
      args: {
        scope?: string;
        day?: string;
        kept?: number | string;
        total?: number | string;
        ratio?: number | string;
      };
    }>(sql, [companyId]);
    if (res.rows.length === 0) return fallback;

    // De-dup on (scope, day) — keep the latest publication per natural key.
    const byKey = new Map<string, KeepRateSample>();
    for (const r of res.rows) {
      const a = r.args ?? {};
      const scope = (a.scope ?? "").toString();
      const day = (a.day ?? "").toString();
      if (!scope || !day) continue;
      if (!(["person", "team", "company"] as const).includes(scope as KeepRateScope)) {
        continue;
      }
      const total = _toNumber(a.total, 0);
      const kept = _toNumber(a.kept, 0);
      const ratio = _toNumber(a.ratio, total > 0 ? kept / total : 0);
      byKey.set(`${scope}:${day}`, {
        scope: scope as KeepRateScope,
        day,
        kept,
        total,
        ratio,
        synthetic: total < KEEP_RATE_SYNTHETIC_THRESHOLD,
      });
    }
    const all = [...byKey.values()];
    // Filter to the trailing `days` days.
    const cutoff = new Date();
    cutoff.setUTCHours(0, 0, 0, 0);
    cutoff.setUTCDate(cutoff.getUTCDate() - (days - 1));
    const cutoffIso = cutoff.toISOString().slice(0, 10);
    return all
      .filter((r) => r.day >= cutoffIso)
      .sort((a, b) => (a.day === b.day ? a.scope.localeCompare(b.scope) : a.day.localeCompare(b.day)));
  }, fallback);
}

/**
 * Onboarding write: register the installer + assign their position.
 *
 * Best-effort live writes via tryPgWrite; the synthetic receipt is the
 * confirmation the optimistic UI shows. Two ledger writes land if
 * Postgres is reachable: emit_person_registered + emit_position_assigned.
 *
 * Status: kept intentionally even though no production caller references
 * it today (the OAuth `/api/v1/installs` flow is the canonical install
 * write since the 2026-04-26 reconciliation). The companion
 * `emit_person_registered` entry kind is still folded by
 * {@link getPositionsRegistry} for back-compat with any pre-OAuth
 * ledger projection. Until that read fold is retired we keep the
 * write helper around so a back-fill / migration can reuse the same
 * shape — deleting the function and not the read fold would create an
 * asymmetric kind that nothing produces but everything still expects.
 */
export async function registerInstaller(
  companyId: string,
  payload: {
    personId: string;
    name: string;
    email?: string | null;
    position: string;
  },
): Promise<Receipt & { ts: string }> {
  const synthetic = syntheticReceipt({
    kind: "person_registered",
    source: "onboarding · tier 1",
    owner: payload.personId,
    classification: "internal",
    payload: {
      person_id: payload.personId,
      name: payload.name,
      position: payload.position,
    },
  });
  await tryPgWrite(async () => {
    const insertSql = `
      INSERT INTO ledger (company_id, kind, ts, payload)
      VALUES ($1, 'execute', now(), $2::jsonb)
    `;
    await pgQuery(insertSql, [
      companyId,
      JSON.stringify({
        tool: "emit_person_registered",
        actor: "dashboard",
        summary: `Installer registered: ${payload.name}`,
        args: {
          person_id: payload.personId,
          name: payload.name,
          email: payload.email ?? null,
          role: "admin",
          registered_at: new Date().toISOString(),
        },
      }),
    ]);
    await pgQuery(insertSql, [
      companyId,
      JSON.stringify({
        tool: "emit_position_assigned",
        actor: "dashboard",
        summary: `Installer position: ${payload.position}`,
        args: {
          person_id: payload.personId,
          position: payload.position,
          at: new Date().toISOString(),
        },
      }),
    ]);
  });
  return synthetic;
}

/**
 * Best-effort write: resolve an in-flight experiment (approve / discard).
 *
 * The /research per-user view exposes "approve" + "reject" buttons so
 * the operator can override the autoresearch outcome.
 */
export async function resolveExperimentManually(
  companyId: string,
  experimentId: string,
  outcome: ExperimentOutcome,
  rationale?: string,
): Promise<Receipt & { ts: string }> {
  const synthetic = syntheticReceipt({
    kind: "experiment_resolved",
    source: "research-tab",
    owner: "operator",
    classification: "internal",
    payload: { experimentId, outcome },
  });
  await tryPgWrite(async () => {
    const sql = `
      INSERT INTO ledger (company_id, kind, ts, payload)
      VALUES ($1, 'execute', now(), $2::jsonb)
    `;
    await pgQuery(sql, [
      companyId,
      JSON.stringify({
        tool: "emit_experiment_resolved",
        actor: "dashboard",
        summary: `Experiment ${experimentId} → ${outcome} (manual)`,
        args: {
          experiment_id: experimentId,
          outcome,
          observed_delta: 0,
          rationale: rationale ?? `manual ${outcome} from /research`,
          resolved_at: new Date().toISOString(),
        },
      }),
    ]);
  });
  return synthetic;
}

// ===========================================================================
// === Data products + notebooks (Block F of the production-dashboard PRD) ===
// ===========================================================================

/** Fold helper: walks emit_data_product_* execute entries → DataProductRow. */
const DATA_PRODUCT_FOLD_SQL = `
  SELECT seq, ts,
         payload->>'tool' AS tool,
         payload->'args' AS args,
         encode(hash, 'hex') AS hash_hex
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_data_product_proposed',
       'emit_data_product_generated',
       'emit_data_product_consumed',
       'emit_data_product_archived'
     )
   ORDER BY seq ASC
`;

interface DataProductFoldRow extends Record<string, unknown> {
  seq: number;
  ts: string;
  tool: string;
  args: Record<string, unknown>;
  hash_hex: string;
}

interface FoldedDataProductState {
  dataProductId: string;
  tenantId: string;
  name: string;
  kind: string;
  status: string;
  requestedByPersonId: string;
  domainId: string | null;
  generatedAt: string | null;
  contentHash: string | null;
  contentsUri: string | null;
  /** Free-form parameters payload from emit_data_product_proposed.
   *
   * For process_map data products (P10), this carries the
   * nodes/edges/window/confidence shape the worm built from chatter.
   * For other kinds it may carry filters or template vars. The fold
   * keeps it raw so consumers can pull out kind-specific fields
   * without a typed branch in the projection. */
  parameters: Record<string, unknown>;
  /** Lifecycle timestamps for the proposed step.
   *
   * /system-map's process-map lens orders proposals by ``proposedAt``;
   * we surface it from the fold so the typed row carries it without
   * re-querying. */
  proposedAt: string | null;
  lastHash: string;
}

function foldDataProductRows(
  companyId: string,
  rows: DataProductFoldRow[],
): {
  products: Map<string, FoldedDataProductState>;
  runs: DataProductRunRow[];
  consumption: DataProductConsumptionRow[];
} {
  const products = new Map<string, FoldedDataProductState>();
  const runs: DataProductRunRow[] = [];
  const consumption: DataProductConsumptionRow[] = [];

  for (const row of rows) {
    const args = row.args || {};
    const dpId = String(args["data_product_id"] ?? "");
    if (!dpId) continue;
    if (row.tool === "emit_data_product_proposed") {
      const rawParams = args["parameters"];
      const parameters: Record<string, unknown> =
        rawParams && typeof rawParams === "object" && !Array.isArray(rawParams)
          ? (rawParams as Record<string, unknown>)
          : {};
      products.set(dpId, {
        dataProductId: dpId,
        tenantId: companyId,
        name: String(args["name"] ?? ""),
        kind: String(args["kind"] ?? "report"),
        status: "proposed",
        requestedByPersonId: String(args["requested_by_person_id"] ?? ""),
        domainId: args["domain_id"] ? String(args["domain_id"]) : null,
        generatedAt: null,
        contentHash: null,
        contentsUri: null,
        parameters,
        proposedAt: row.ts,
        lastHash: row.hash_hex,
      });
    } else if (row.tool === "emit_data_product_generated") {
      runs.push({
        runId: `${dpId}-${row.seq}`,
        dataProductId: dpId,
        tenantId: companyId,
        generatedBy: String(args["generated_by"] ?? "worm"),
        ts: row.ts,
        sourceHashes: Array.isArray(args["source_hashes"])
          ? (args["source_hashes"] as string[]).slice()
          : [],
        contentHash: String(args["content_hash"] ?? ""),
        durationMs: Number(args["duration_ms"] ?? 0),
      });
      const existing = products.get(dpId);
      if (existing) {
        existing.status = "generated";
        existing.generatedAt = row.ts;
        existing.contentHash = String(args["content_hash"] ?? "");
        existing.contentsUri = String(args["contents_uri"] ?? "");
        existing.lastHash = row.hash_hex;
      }
    } else if (row.tool === "emit_data_product_consumed") {
      consumption.push({
        consumptionId: `${dpId}-${row.seq}`,
        dataProductId: dpId,
        tenantId: companyId,
        personId: String(args["consumed_by_person_id"] ?? ""),
        surface: String(args["surface"] ?? "dashboard"),
        channel: args["channel"] ? String(args["channel"]) : null,
        ts: row.ts,
      });
    } else if (row.tool === "emit_data_product_archived") {
      const existing = products.get(dpId);
      if (existing) {
        existing.status = "archived";
        existing.lastHash = row.hash_hex;
      }
    }
  }
  return { products, runs, consumption };
}

function projectDataProductRow(s: FoldedDataProductState): DataProductRow {
  return {
    dataProductId: s.dataProductId,
    tenantId: s.tenantId,
    name: s.name,
    kind: s.kind,
    status: s.status,
    requestedByPersonId: s.requestedByPersonId,
    domainId: s.domainId,
    generatedAt: s.generatedAt,
    contentHash: s.contentHash,
    contentsUri: s.contentsUri,
    receipt: {
      hash: s.lastHash.slice(0, 12),
      source: "ledger",
      owner: s.requestedByPersonId,
      classification: "internal",
    },
  };
}

export interface DataProductFilters {
  /** Restrict to products requested by this Person. */
  requestedBy?: string;
  /** Restrict to products in this domain. */
  domainId?: string;
  /** Restrict to a single kind (chart / table / report). */
  kind?: string;
  /** Restrict to a single status. */
  status?: string;
}

export async function getDataProducts(
  companyId: string = DEFAULT_COMPANY_ID,
  filters: DataProductFilters = {},
): Promise<DataProductRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<DataProductFoldRow>(DATA_PRODUCT_FOLD_SQL, [
      companyId,
    ]);
    const folded = foldDataProductRows(companyId, res.rows);
    let arr = Array.from(folded.products.values()).map(projectDataProductRow);
    if (filters.requestedBy) {
      arr = arr.filter((r) => r.requestedByPersonId === filters.requestedBy);
    }
    if (filters.domainId) {
      arr = arr.filter((r) => r.domainId === filters.domainId);
    }
    if (filters.kind) {
      arr = arr.filter((r) => r.kind === filters.kind);
    }
    if (filters.status) {
      arr = arr.filter((r) => r.status === filters.status);
    }
    arr.sort((a, b) => a.dataProductId.localeCompare(b.dataProductId));
    return arr;
  }, []);
}

export async function getDataProductById(
  companyId: string,
  dataProductId: string,
): Promise<DataProductRow | null> {
  return tryPg(async () => {
    const res = await pgQuery<DataProductFoldRow>(DATA_PRODUCT_FOLD_SQL, [
      companyId,
    ]);
    const folded = foldDataProductRows(companyId, res.rows);
    const state = folded.products.get(dataProductId);
    return state ? projectDataProductRow(state) : null;
  }, null);
}

export async function getDataProductRuns(
  companyId: string,
  dataProductId: string,
): Promise<DataProductRunRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<DataProductFoldRow>(DATA_PRODUCT_FOLD_SQL, [
      companyId,
    ]);
    const folded = foldDataProductRows(companyId, res.rows);
    return folded.runs.filter((r) => r.dataProductId === dataProductId);
  }, []);
}

export async function getDataProductConsumption(
  companyId: string,
  filters: { dataProductId?: string; personId?: string } = {},
): Promise<DataProductConsumptionRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<DataProductFoldRow>(DATA_PRODUCT_FOLD_SQL, [
      companyId,
    ]);
    const folded = foldDataProductRows(companyId, res.rows);
    let arr = folded.consumption;
    if (filters.dataProductId) {
      arr = arr.filter((c) => c.dataProductId === filters.dataProductId);
    }
    if (filters.personId) {
      arr = arr.filter((c) => c.personId === filters.personId);
    }
    return arr;
  }, []);
}

/**
 * Project the subset of data products whose ``kind === 'process_map'``
 * into the ``ProcessMapDataProductRow`` shape used by /system-map's
 * "Conversation Process Maps" lens (P10).
 *
 * The payload (nodes / edges / window) lives in ``parameters`` per spec
 * §7 P10 — the gold artifact body, not the data-product metadata.
 * Empty parameters are mapped to an empty payload so the lens can
 * render an honest empty state without throwing.
 */
function projectProcessMapRow(
  s: FoldedDataProductState,
): import("./ledger-client.types").ProcessMapDataProductRow {
  const params = s.parameters || {};
  const nodesRaw = Array.isArray(params["nodes"]) ? params["nodes"] : [];
  const edgesRaw = Array.isArray(params["edges"]) ? params["edges"] : [];
  return {
    dataProductId: s.dataProductId,
    tenantId: s.tenantId,
    name: s.name,
    status: s.status,
    domainId: s.domainId,
    proposedAt: s.proposedAt,
    payload: {
      nodes: nodesRaw.map((n) => {
        const obj = (n ?? {}) as Record<string, unknown>;
        return {
          actorPersonId: String(obj["actor_person_id"] ?? ""),
          roleInMap: String(obj["role_in_map"] ?? "asker"),
        };
      }),
      edges: edgesRaw.map((e) => {
        const obj = (e ?? {}) as Record<string, unknown>;
        return {
          fromPersonId: String(obj["from"] ?? ""),
          toPersonId: String(obj["to"] ?? ""),
          topic: String(obj["topic"] ?? ""),
          frequency: Number(obj["frequency"] ?? 0),
          firstSeen: String(obj["first_seen"] ?? ""),
          lastSeen: String(obj["last_seen"] ?? ""),
        };
      }),
      windowStart: String(params["window_start"] ?? ""),
      windowEnd: String(params["window_end"] ?? ""),
      confidence: Number(params["confidence"] ?? 0),
    },
    receipt: {
      hash: s.lastHash.slice(0, 12),
      source: "ledger",
      owner: s.requestedByPersonId,
      classification: "internal",
    },
  };
}

/**
 * Lists ``kind="process_map"`` data products for the company (P10).
 *
 * Distinct from ``getProcessMaps`` (which folds the legacy
 * ``emit_process_map_proposed`` rows into Step-3c
 * actor/action/order shapes). The P10 process maps are
 * conversation-derived gold artifacts — node/edge/window structure
 * carried in ``parameters`` — and surface on /system-map's "Conversation
 * Process Maps" lens, not on /processes.
 *
 * Returns most-recent-first (descending by ``proposedAt``). The
 * implementation reuses ``DATA_PRODUCT_FOLD_SQL`` so process_map rows
 * are byte-equivalent to other data products at the ledger level —
 * they only diverge at projection time.
 */
export async function getProcessMapDataProducts(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<import("./ledger-client.types").ProcessMapDataProductRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<DataProductFoldRow>(DATA_PRODUCT_FOLD_SQL, [
      companyId,
    ]);
    const folded = foldDataProductRows(companyId, res.rows);
    const arr = Array.from(folded.products.values())
      .filter((s) => s.kind === "process_map")
      .map(projectProcessMapRow);
    arr.sort((a, b) => {
      const aT = a.proposedAt ? Date.parse(a.proposedAt) : 0;
      const bT = b.proposedAt ? Date.parse(b.proposedAt) : 0;
      return bT - aT;
    });
    return arr;
  }, []);
}

// ---------------------------------------------------------------------------
// Notebooks
// ---------------------------------------------------------------------------

const NOTEBOOK_FOLD_SQL = `
  SELECT seq, ts,
         payload->>'tool' AS tool,
         payload->'args' AS args,
         encode(hash, 'hex') AS hash_hex
    FROM ledger
   WHERE company_id = $1
     AND kind = 'execute'
     AND payload->>'tool' IN (
       'emit_notebook_proposed',
       'emit_notebook_run',
       'emit_notebook_published',
       'emit_notebook_archived'
     )
   ORDER BY seq ASC
`;

interface NotebookFoldRow extends Record<string, unknown> {
  seq: number;
  ts: string;
  tool: string;
  args: Record<string, unknown>;
  hash_hex: string;
}

interface FoldedNotebookState {
  notebookId: string;
  tenantId: string;
  name: string;
  kernel: string;
  status: string;
  ownerPersonId: string | null;
  domainId: string | null;
  latestRunId: string | null;
  latestPublishedRunId: string | null;
  version: string | null;
  cells: NotebookCell[];
  lastHash: string;
}

function foldNotebookRows(
  companyId: string,
  rows: NotebookFoldRow[],
): { notebooks: Map<string, FoldedNotebookState>; runs: NotebookRunRow[] } {
  const notebooks = new Map<string, FoldedNotebookState>();
  const runs: NotebookRunRow[] = [];

  for (const row of rows) {
    const args = row.args || {};
    const nbId = String(args["notebook_id"] ?? "");
    if (!nbId) continue;
    if (row.tool === "emit_notebook_proposed") {
      notebooks.set(nbId, {
        notebookId: nbId,
        tenantId: companyId,
        name: String(args["name"] ?? ""),
        kernel: String(args["kernel"] ?? "python_local"),
        status: "proposed",
        ownerPersonId: args["proposed_by_person_id"]
          ? String(args["proposed_by_person_id"])
          : null,
        domainId: args["domain_id"] ? String(args["domain_id"]) : null,
        latestRunId: null,
        latestPublishedRunId: null,
        version: null,
        cells: Array.isArray(args["cells"])
          ? ((args["cells"] as Array<Record<string, unknown>>).map(
              (c): NotebookCell => ({
                kind: (String(c["kind"] ?? "code") as NotebookCell["kind"]),
                source: String(c["source"] ?? ""),
                language: c["language"] ? String(c["language"]) : undefined,
              }),
            ))
          : [],
        lastHash: row.hash_hex,
      });
    } else if (row.tool === "emit_notebook_run") {
      const runId = String(args["run_id"] ?? `${nbId}-${row.seq}`);
      runs.push({
        runId,
        notebookId: nbId,
        tenantId: companyId,
        status: String(args["status"] ?? "ok"),
        ts: row.ts,
        runBy: String(args["run_by"] ?? "worm"),
        kernelStateHash: String(args["kernel_state_hash"] ?? ""),
        durationMs: Number(args["duration_ms"] ?? 0),
        cellOutputs: Array.isArray(args["cell_outputs"])
          ? (args["cell_outputs"] as Array<Record<string, unknown>>)
          : undefined,
        cellHashes: Array.isArray(args["cell_hashes"])
          ? (args["cell_hashes"] as string[])
          : undefined,
      });
      const existing = notebooks.get(nbId);
      if (existing) {
        existing.status = "run";
        existing.latestRunId = runId;
        existing.lastHash = row.hash_hex;
      }
    } else if (row.tool === "emit_notebook_published") {
      const existing = notebooks.get(nbId);
      if (existing) {
        existing.status = "published";
        existing.latestPublishedRunId = String(args["run_id"] ?? "");
        existing.version = String(args["version"] ?? "1");
        existing.ownerPersonId = String(
          args["owner_person_id"] ?? existing.ownerPersonId ?? "",
        );
        existing.lastHash = row.hash_hex;
      }
    } else if (row.tool === "emit_notebook_archived") {
      const existing = notebooks.get(nbId);
      if (existing) {
        existing.status = "archived";
        existing.lastHash = row.hash_hex;
      }
    }
  }
  return { notebooks, runs };
}

function projectNotebookRow(s: FoldedNotebookState): NotebookRow {
  return {
    notebookId: s.notebookId,
    tenantId: s.tenantId,
    name: s.name,
    kernel: s.kernel,
    status: s.status,
    ownerPersonId: s.ownerPersonId,
    domainId: s.domainId,
    latestRunId: s.latestRunId,
    latestPublishedRunId: s.latestPublishedRunId,
    version: s.version,
    cells: s.cells,
    receipt: {
      hash: s.lastHash.slice(0, 12),
      source: "ledger",
      owner: s.ownerPersonId ?? "worm",
      classification: "internal",
    },
  };
}

export interface NotebookFilters {
  ownerPersonId?: string;
  domainId?: string;
  status?: string;
}

export async function getNotebooks(
  companyId: string = DEFAULT_COMPANY_ID,
  filters: NotebookFilters = {},
): Promise<NotebookRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<NotebookFoldRow>(NOTEBOOK_FOLD_SQL, [companyId]);
    const folded = foldNotebookRows(companyId, res.rows);
    let arr = Array.from(folded.notebooks.values()).map(projectNotebookRow);
    if (filters.ownerPersonId) {
      arr = arr.filter((n) => n.ownerPersonId === filters.ownerPersonId);
    }
    if (filters.domainId) {
      arr = arr.filter((n) => n.domainId === filters.domainId);
    }
    if (filters.status) {
      arr = arr.filter((n) => n.status === filters.status);
    }
    arr.sort((a, b) => a.notebookId.localeCompare(b.notebookId));
    return arr;
  }, []);
}

export async function getNotebookById(
  companyId: string,
  notebookId: string,
): Promise<NotebookRow | null> {
  return tryPg(async () => {
    const res = await pgQuery<NotebookFoldRow>(NOTEBOOK_FOLD_SQL, [companyId]);
    const folded = foldNotebookRows(companyId, res.rows);
    const state = folded.notebooks.get(notebookId);
    return state ? projectNotebookRow(state) : null;
  }, null);
}

export async function getNotebookRuns(
  companyId: string,
  notebookId: string,
): Promise<NotebookRunRow[]> {
  return tryPg(async () => {
    const res = await pgQuery<NotebookFoldRow>(NOTEBOOK_FOLD_SQL, [companyId]);
    const folded = foldNotebookRows(companyId, res.rows);
    return folded.runs.filter((r) => r.notebookId === notebookId);
  }, []);
}

// ─── WS5 S1 (+ Phase 3 Task 3A): Worm activity since you logged off ─────
//
// Counts of relevant ledger entries since a "last seen" timestamp, grouped
// by tool family. Powers the WormActivityTile on /dashboard — the first
// daily moment of value for any returning user.
//
// Phase 3 Task 3A (per the 2026-04-27 P2.1 validation gap audit) extended
// the family set with five gold-artifact-producing surfaces the original
// WS5 S1 cut omitted:
//
//   - drift                — `emit_source_drift_detected` (lake-maintainer)
//   - experiments          — `emit_experiment_resolved`   (research-loop)
//   - recurring_questions  — `emit_recurring_question`    (process-extractor)
//   - position_proposals   — `emit_position_proposed`     (identity-tracker)
//   - topics               — `emit_topic_proposed`        (process-extractor 2B)
//
// All five read from existing entry kinds and existing projection folds —
// no new entry kinds and no new projections were added for this tile.

export type WormActivityFamily =
  | "chat"
  | "files"
  | "kpis"
  | "decisions"
  | "sources"
  | "proactivity"
  | "artifacts"
  | "drift"
  | "experiments"
  | "recurring_questions"
  | "position_proposals"
  | "topics";

export interface WormActivitySummary {
  /** ISO timestamp the count window started at. `null` ⇒ "since install". */
  sinceTs: string | null;
  /** Total count across all families. */
  total: number;
  /** Per-family count. Zero entries are still present so the UI can show
   *  a stable family ordering rather than collapsing absent rows. */
  byFamily: Record<WormActivityFamily, number>;
}

const _ACTIVITY_FAMILY_TOOLS: Record<WormActivityFamily, string[]> = {
  chat: ["channel_adapter.emit_chat_received", "emit_chat_received"],
  files: ["channel_adapter.emit_file_received", "emit_file_received"],
  kpis: ["emit_kpi_proposed"],
  decisions: ["emit_decision_recorded"],
  sources: ["emit_source_proposed"],
  proactivity: ["emit_proactive_offer"],
  artifacts: ["emit_data_product_generated", "emit_notebook_published"],
  drift: ["emit_source_drift_detected"],
  experiments: ["emit_experiment_resolved"],
  recurring_questions: ["emit_recurring_question"],
  position_proposals: ["emit_position_proposed"],
  topics: ["emit_topic_proposed"],
};

function _emptyActivitySummary(sinceTs: string | null): WormActivitySummary {
  return {
    sinceTs,
    total: 0,
    byFamily: {
      chat: 0,
      files: 0,
      kpis: 0,
      decisions: 0,
      sources: 0,
      proactivity: 0,
      artifacts: 0,
      drift: 0,
      experiments: 0,
      recurring_questions: 0,
      position_proposals: 0,
      topics: 0,
    },
  };
}

/**
 * Count ledger entries since `sinceTs`, grouped by tool family.
 *
 * `sinceTs` is the current Person's "last seen" timestamp. For first-time
 * visits (no last-seen) the caller passes `null` — the helper then counts
 * since install (no `ts` filter).
 */
export async function getWormActivitySummary(
  companyId: string = DEFAULT_COMPANY_ID,
  sinceTs: string | null = null,
): Promise<WormActivitySummary> {
  return tryPg(async () => {
    const allTools: string[] = [];
    for (const tools of Object.values(_ACTIVITY_FAMILY_TOOLS)) {
      for (const t of tools) allTools.push(t);
    }
    const params: unknown[] = [companyId, allTools];
    let tsClause = "";
    if (sinceTs) {
      params.push(sinceTs);
      tsClause = `AND ts >= $3::timestamptz`;
    }
    const sql = `
      SELECT payload->>'tool' AS tool, COUNT(*)::int AS n
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = ANY($2::text[])
         ${tsClause}
       GROUP BY payload->>'tool'
    `;
    const res = await pgQuery<{ tool: string | null; n: number }>(sql, params);
    const summary = _emptyActivitySummary(sinceTs);
    for (const row of res.rows) {
      const tool = row.tool ?? "";
      const n = typeof row.n === "number" ? row.n : Number(row.n) || 0;
      for (const [family, tools] of Object.entries(_ACTIVITY_FAMILY_TOOLS) as [
        WormActivityFamily,
        string[],
      ][]) {
        if (tools.includes(tool)) {
          summary.byFamily[family] += n;
          summary.total += n;
          break;
        }
      }
    }
    return summary;
  }, _emptyActivitySummary(sinceTs));
}

// ─── WS5 S2: Surface the worm's first hello-message ─────────────────────
//
// The most photo-friendly demo beat is when the worm posts "hi I'm here"
// in the channel. Today that beat is OFF-screen. SlackWelcomeMoment surfaces
// it as a small editorial quote-card on /dashboard.

export interface FirstWormMessage {
  channelId: string;
  channelName: string;
  text: string;
  ts: string;
}

/**
 * The first `emit_chat_sent` entry whose `sender_handle` (or `sender_person`
 * fallback) reads as the worm. Returns `null` when the worm has not yet
 * spoken — the dashboard then hides the card rather than rendering a stub.
 */
export async function getFirstWormMessage(
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<FirstWormMessage | null> {
  return tryPg(async () => {
    const sql = `
      SELECT ts,
             payload->'args'->>'channel_id'      AS channel_id,
             payload->'args'->>'channel_name'    AS channel_name,
             payload->'args'->>'text'            AS text,
             payload->'args'->>'sender_handle'   AS sender_handle,
             payload->'args'->>'sender_person'   AS sender_person
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_chat_sent',
           'channel_adapter.emit_chat_sent'
         )
         AND (
           payload->'args'->>'sender_handle' ILIKE '%wormbase%'
           OR payload->'args'->>'sender_handle' ILIKE '%worm%'
           OR payload->'args'->>'sender_person' = 'worm'
         )
       ORDER BY seq ASC
       LIMIT 1
    `;
    const res = await pgQuery<{
      ts: Date | string;
      channel_id: string | null;
      channel_name: string | null;
      text: string | null;
      sender_handle: string | null;
      sender_person: string | null;
    }>(sql, [companyId]);
    if (res.rows.length === 0) return null;
    const r = res.rows[0];
    const ts = r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString();
    return {
      channelId: r.channel_id ?? "",
      channelName: r.channel_name ?? r.channel_id ?? "(channel)",
      text: r.text ?? "",
      ts,
    };
  }, null);
}

// ─── WS5 S3: Topics across conversations ────────────────────────────────
//
// Silver-conversations: cluster `emit_chat_received` entries into per-channel
// topic cards. v1 uses naive (channel × top-keyword) clustering; the keyword
// extraction is intentionally simple (whitespace tokenize + small stopword
// allowlist + frequency rank) and runs entirely server-side. v2 will hand
// this off to the projection-builder service the architecture audit calls
// for.

export interface Topic {
  topicId: string;
  label: string;
  channelId: string;
  channelName: string;
  messageCount: number;
  topPersons: string[];
  latestExcerpt: string;
  latestTs: string;
}

const _TOPIC_STOPWORDS = new Set<string>([
  "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "in",
  "on", "at", "to", "for", "by", "with", "from", "as", "is", "it", "be",
  "are", "was", "were", "this", "that", "these", "those", "i", "me", "my",
  "we", "our", "you", "your", "they", "them", "their", "he", "she", "his",
  "her", "do", "does", "did", "have", "has", "had", "not", "no", "yes",
  "so", "can", "will", "would", "should", "could", "may", "might", "just",
  "about", "what", "when", "who", "how", "why", "which", "than", "any",
  "some", "all", "out", "up", "down", "into", "over", "after", "before",
  "again", "us", "im", "ive", "youre", "thats", "lets", "got", "get", "see",
  "think", "know", "going", "now", "ok", "okay", "yeah", "hi", "hey",
  "thanks", "thank", "please",
]);

interface TopicRawRow extends Record<string, unknown> {
  channel_id: string | null;
  channel_name: string | null;
  text: string | null;
  sender_person: string | null;
  ts: Date | string;
}

function _extractTopKeyword(texts: string[]): string {
  const counts = new Map<string, number>();
  for (const text of texts) {
    if (!text) continue;
    const tokens = text
      .toLowerCase()
      .replace(/[^a-z0-9\s'-]/g, " ")
      .split(/\s+/)
      .filter((t) => t.length >= 4 && !_TOPIC_STOPWORDS.has(t));
    for (const t of tokens) {
      counts.set(t, (counts.get(t) ?? 0) + 1);
    }
  }
  if (counts.size === 0) return "general";
  let best = "";
  let bestN = -1;
  for (const [w, n] of counts) {
    if (n > bestN) {
      best = w;
      bestN = n;
    }
  }
  return best || "general";
}

/**
 * Top topics across the company's conversation lake.
 *
 * v1 clustering: one topic per (channel, top-keyword) pair. Each topic
 * carries the channel name, message count, top participants, latest
 * excerpt, and latest timestamp. Returns at most `limit` topics, sorted
 * by message count descending.
 *
 * W4-A — when ``platform`` is provided, the result is filtered to topics
 * whose underlying ``chat_received`` channel id is platform-shaped. The
 * canonical ``ChatReceivedPayload`` schema does not carry a ``platform``
 * field today (per the schema-evolution doctrine, additive-only;
 * KIND_REGISTRY stays at 83), so the filter is inferred from
 * ``channel_id`` shape — WhatsApp jids end in ``@s.whatsapp.net`` /
 * ``@g.us``; Slack channel ids do not. The filter is pushed into SQL so
 * the LIMIT 1000 scan stays platform-scoped instead of mixing platforms
 * and discarding most rows client-side. When ``platform`` is undefined
 * the read is byte-identical to pre-filter behaviour.
 */
export async function getTopics(
  companyId: string = DEFAULT_COMPANY_ID,
  limit = 20,
  platform?: PlatformSlug,
): Promise<Topic[]> {
  return tryPg(async () => {
    let platformClause = "";
    if (platform === "whatsapp") {
      platformClause =
        " AND (payload->'args'->>'channel_id' LIKE '%@s.whatsapp.net'" +
        "       OR payload->'args'->>'channel_id' LIKE '%@g.us')";
    } else if (platform === "slack") {
      platformClause =
        " AND payload->'args'->>'channel_id' NOT LIKE '%@s.whatsapp.net'" +
        "  AND payload->'args'->>'channel_id' NOT LIKE '%@g.us'";
    }
    const sql = `
      SELECT payload->'args'->>'channel_id'      AS channel_id,
             payload->'args'->>'channel_name'    AS channel_name,
             payload->'args'->>'text'            AS text,
             payload->'args'->>'sender_person'   AS sender_person,
             ts
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_chat_received',
           'channel_adapter.emit_chat_received'
         )${platformClause}
       ORDER BY seq DESC
       LIMIT 1000
    `;
    const res = await pgQuery<TopicRawRow>(sql, [companyId]);
    if (res.rows.length === 0) return [];

    // Group by channel.
    const byChannel = new Map<string, TopicRawRow[]>();
    for (const r of res.rows) {
      const ch = r.channel_id ?? "(channel)";
      const arr = byChannel.get(ch) ?? [];
      arr.push(r);
      byChannel.set(ch, arr);
    }

    const topics: Topic[] = [];
    for (const [channelId, rows] of byChannel) {
      const channelName = rows[0]?.channel_name ?? channelId;
      const texts = rows.map((r) => r.text ?? "");
      const label = _extractTopKeyword(texts);

      // Top participants by message count.
      const partCounts = new Map<string, number>();
      for (const r of rows) {
        const p = r.sender_person ?? "unknown";
        partCounts.set(p, (partCounts.get(p) ?? 0) + 1);
      }
      const topPersons = Array.from(partCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([p]) => p);

      // Latest excerpt + ts. Rows came back DESC by seq so [0] is newest.
      const latest = rows[0];
      const latestTs =
        latest.ts instanceof Date
          ? latest.ts.toISOString()
          : new Date(latest.ts).toISOString();
      const rawText = latest.text ?? "";
      const latestExcerpt =
        rawText.length > 140 ? rawText.slice(0, 137) + "..." : rawText;

      topics.push({
        topicId: `${channelId}:${label}`,
        label,
        channelId,
        channelName,
        messageCount: rows.length,
        topPersons,
        latestExcerpt,
        latestTs,
      });
    }

    topics.sort((a, b) => b.messageCount - a.messageCount);
    return topics.slice(0, limit);
  }, []);
}

// ─── Block J — MCP integration (worm-as-MCP-server) ──────────────────────

/**
 * Recent inbound MCP calls, read straight from ``projection_mcp_calls``.
 *
 * Live source: ``record_mcp_call`` in
 * ``apps/worm-core/src/wormbase_core/write_actions.py`` (commit 98f5c40).
 * The projection-builder folds each ``execute(emit_mcp_call_received)``
 * entry into one row of ``projection_mcp_calls``; we read it directly.
 *
 * Returns ``[]`` (NOT a fixture) when the MCP server hasn't been called
 * yet — the dashboard renders an honest empty state with copy that
 * names the trigger flow ("connect Claude Desktop, run a tool").
 *
 * Args are NEVER returned in raw form; ``args_hash`` is the only field
 * exposed (sha256 hex of the redacted payload), per §8.3 privacy
 * nuance of the MCP integration spec.
 */
export async function getMcpCalls(
  companyId: string = DEFAULT_COMPANY_ID,
  limit = 50,
): Promise<McpCallRow[]> {
  return tryPg(async () => {
    const sql = `
      SELECT mcp_call_id,
             tenant_id,
             caller_person_id,
             tool_name,
             args_hash,
             client_ua,
             started_at,
             outcome,
             latency_ms
        FROM projection_mcp_calls
       WHERE tenant_id = $1
       ORDER BY started_at DESC
       LIMIT $2
    `;
    const res = await pgQuery<{
      mcp_call_id: string;
      tenant_id: string;
      caller_person_id: string | null;
      tool_name: string;
      args_hash: string;
      client_ua: string | null;
      started_at: Date | string;
      outcome: string;
      latency_ms: number | string;
    }>(sql, [companyId, limit]);

    if (res.rows.length === 0) return [];

    return res.rows.map((r): McpCallRow => {
      const startedIso =
        r.started_at instanceof Date
          ? r.started_at.toISOString()
          : new Date(r.started_at).toISOString();
      const latencyNum =
        typeof r.latency_ms === "number"
          ? r.latency_ms
          : Number(r.latency_ms);
      return {
        mcpCallId: r.mcp_call_id,
        tenantId: r.tenant_id,
        callerPersonId: r.caller_person_id,
        toolName: r.tool_name,
        argsHash: r.args_hash,
        clientUa: r.client_ua,
        startedAt: startedIso,
        outcome: r.outcome as McpCallOutcome,
        latencyMs: Number.isFinite(latencyNum) ? latencyNum : 0,
        receipt: {
          // First 12 chars of the args_hash double as the visual receipt
          // hash; classification clamps at "internal" — audit rows are
          // more sensitive than the data they audit (spec §8.3).
          hash: r.args_hash.slice(0, 12),
          source: "mcp",
          owner: r.caller_person_id ?? "mcp-anonymous",
          classification: "internal",
        },
      };
    });
  }, []);
}

/**
 * Local MCP server catalog — what tools / resources / prompts are
 * registered on the worm-core side.
 *
 * Source: the worm-core MCP server's ``/mcp/catalog`` endpoint (or
 * equivalent). When the endpoint is unreachable (server not running,
 * port not configured, sister-agent J3 not yet shipped), returns
 * ``{available: false, entries: []}`` so the panel can render an
 * honest "MCP server not yet running" empty state.
 *
 * TODO: when the worm-core MCP server exposes a catalog endpoint
 * (J3-ish — sister agent's territory), wire the URL here. For now the
 * accessor returns the unavailable shape; the page renders the empty
 * state honestly.
 */
export async function getMcpCatalog(
  _companyId: string = DEFAULT_COMPANY_ID,
): Promise<McpCatalog> {
  const url = process.env.WORMBASE_MCP_CATALOG_URL;
  if (!url) {
    // No catalog endpoint configured — render the honest empty state.
    return { available: false, entries: [] };
  }
  try {
    const res = await fetch(url, {
      // Server-component fetch; opt out of Next's default cache so
      // catalog updates show up on next page render rather than a stale
      // 1-hour build.
      cache: "no-store",
    });
    if (!res.ok) {
      warnOnce(
        `mcp-catalog-status:${res.status}`,
        `MCP catalog endpoint returned ${res.status}; rendering empty state`,
      );
      return { available: false, entries: [] };
    }
    const body = (await res.json()) as McpCatalog;
    if (
      typeof body !== "object" ||
      body === null ||
      !Array.isArray(body.entries)
    ) {
      warnOnce(
        "mcp-catalog-shape",
        "MCP catalog endpoint returned an unexpected shape; rendering empty state",
      );
      return { available: false, entries: [] };
    }
    return { available: true, entries: body.entries };
  } catch (err) {
    const e = err as Error;
    warnOnce(
      `mcp-catalog-fetch:${e.name}`,
      `MCP catalog fetch failed (${e.message.slice(0, 60)}); rendering empty state`,
    );
    return { available: false, entries: [] };
  }
}

// ---------------------------------------------------------------------------
// W5.A5 — reactivities + resource conversations + audience-scoped research
// ---------------------------------------------------------------------------

/**
 * Build a fetch URL for a worm-core endpoint. Uses the same env-driven
 * base as ``lib/server/worm-core-write.ts``; if the token isn't set we
 * still attempt the call (read-side may be unauthenticated upstream)
 * but defer authentication errors to the response handler.
 */
function _wormCoreBase(): string {
  const raw =
    process.env.WORMBASE_LEDGER_API_BASE ?? "http://worm-core:8910";
  return raw.replace(/\/+$/, "");
}

function _wormCoreHeaders(tenantSlug = "baseworm"): HeadersInit {
  const token = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Tenant-Slug": tenantSlug,
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function _wormCoreGet<T>(
  path: string,
  fallback: T,
  tenantSlug = "baseworm",
): Promise<T> {
  const url = `${_wormCoreBase()}${path}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: _wormCoreHeaders(tenantSlug),
      cache: "no-store",
    });
    if (!res.ok) {
      warnOnce(
        `worm-core-get:${res.status}:${path.slice(0, 32)}`,
        `worm-core GET ${path} returned ${res.status}; rendering empty state`,
      );
      return fallback;
    }
    return (await res.json()) as T;
  } catch (err) {
    const e = err as Error;
    warnOnce(
      `worm-core-get-fetch:${e.name}:${path.slice(0, 32)}`,
      `worm-core GET ${path} failed (${e.message.slice(0, 60)}); rendering empty state`,
    );
    return fallback;
  }
}

/**
 * List the registered reactivities from the worm-core registry.
 *
 * Returns ``[]`` honestly when the registry isn't reachable (worm-core
 * unavailable, or no registry attached) so the dashboard renders an
 * honest empty state. The /reactivities tab pivots on ``state`` (active /
 * proposed / disabled) for the three sections.
 */
export async function getReactivities(
  _companyId: string = DEFAULT_COMPANY_ID,
  tenantSlug = "baseworm",
): Promise<Reactivity[]> {
  const body = await _wormCoreGet<{ reactivities?: Reactivity[] }>(
    "/api/v1/reactivities",
    { reactivities: [] },
    tenantSlug,
  );
  return Array.isArray(body.reactivities) ? body.reactivities : [];
}

/**
 * Last N fires of one reactivity. Newest-first.
 */
export async function getReactivityFires(
  reactivityId: string,
  limit = 50,
  _companyId: string = DEFAULT_COMPANY_ID,
  tenantSlug = "baseworm",
): Promise<ReactivityFire[]> {
  const safeLimit = Math.max(1, Math.min(500, Math.floor(limit)));
  const path =
    `/api/v1/reactivities/${encodeURIComponent(reactivityId)}/fires?limit=${safeLimit}`;
  const body = await _wormCoreGet<{ fires?: ReactivityFire[] }>(
    path,
    { fires: [] },
    tenantSlug,
  );
  return Array.isArray(body.fires) ? body.fires : [];
}

/**
 * Active resource conversations where this Person is the owner. Folded
 * by worm-core from ``emit_resource_conversation_*`` entries; resolved
 * conversations are filtered out so the card shows only what's pending.
 */
export async function getResourceConversationsForOwner(
  personId: string,
  _companyId: string = DEFAULT_COMPANY_ID,
  tenantSlug = "baseworm",
): Promise<ResourceConversation[]> {
  const path =
    `/api/v1/people/${encodeURIComponent(personId)}/resource-conversations`;
  const body = await _wormCoreGet<{ conversations?: ResourceConversation[] }>(
    path,
    { conversations: [] },
    tenantSlug,
  );
  return Array.isArray(body.conversations) ? body.conversations : [];
}

/**
 * Filter experiments by audience scope.
 *
 * Wraps ``getExperimentsForUser`` and filters on the
 * ``proposed_change.audience`` payload field (W5.A4). Unknown values
 * fall through as ``person:<id>`` for migration-safety.
 *
 *   * ``mine``    — experiments scoped to ``person:<currentPersonId>``
 *   * ``team``    — experiments scoped to ``team:<…>`` for any of this
 *                   Person's team grants. With no team-membership
 *                   resolver yet wired, this folds to ``team:*``.
 *   * ``company`` — experiments scoped to ``company`` (org-wide).
 *
 * Always returns ``[]`` when no experiments match — never a fixture.
 */
export async function getExperimentsByAudience(
  audience: ResearchAudience,
  currentPersonId: string,
  companyId: string = DEFAULT_COMPANY_ID,
): Promise<ExperimentRow[]> {
  const all = await getExperimentsForUser(companyId, undefined, 200);
  if (all.length === 0) return [];

  const audienceFor = (e: ExperimentRow): string => {
    const change = (e.proposedChange ?? {}) as Record<string, unknown>;
    const raw = change.audience;
    if (typeof raw === "string" && raw.length > 0) return raw;
    return `person:${e.forPersonId}`;
  };

  if (audience === "mine") {
    const wanted = `person:${currentPersonId}`;
    return all.filter((e) => audienceFor(e) === wanted);
  }
  if (audience === "team") {
    return all.filter((e) => audienceFor(e).startsWith("team:"));
  }
  // company
  return all.filter((e) => audienceFor(e) === "company");
}

/**
 * Demo-day P9 — per-scope ``experiment_lesson`` rows for /research.
 *
 * Reads ``emit_experiment_lesson`` ledger entries; folds the canonical
 * post-application state per ``prior_keep_id`` (latest seq wins so
 * ``applied_at`` stamps overwrite the original ``None`` extraction). Returns
 * the trailing-N entries per scope, newest-first; up to ``limit`` per
 * scope.
 *
 * Returns ``[]`` when no lessons exist — never a fixture. Empty state
 * surfaces an honest "the worm has not learnt yet" message in the card.
 */
export async function getExperimentLessons(
  companyId: string = DEFAULT_COMPANY_ID,
  scope?: LessonScope,
  limit = 5,
): Promise<ExperimentLessonRow[]> {
  const fallback: ExperimentLessonRow[] = [];
  return tryPg(async () => {
    const params: unknown[] = [companyId];
    let scopeFilter = "";
    if (scope) {
      params.push(scope);
      scopeFilter = `AND payload->'args'->>'scope' = $${params.length}`;
    }
    const sql = `
      SELECT payload->'args' AS args,
             ts,
             encode(hash, 'hex') AS hash_hex,
             seq
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_experiment_lesson'
         ${scopeFilter}
       ORDER BY seq ASC
    `;
    const res = await pgQuery<{
      args: {
        prior_keep_id?: string;
        scope?: string;
        lesson_text?: string;
        lesson_features?: Record<string, string>;
        applied_to_proposer?: string;
        applied_at?: number | null;
        proposed_by?: string;
        extracted_at?: string;
      };
      ts: Date | string;
      hash_hex: string;
      seq: number | string;
    }>(sql, params);
    if (res.rows.length === 0) return fallback;

    // Latest entry per prior_keep_id wins (every applied_at stamp re-writes
    // the lesson).
    const byPrior = new Map<string, ExperimentLessonRow>();
    for (const r of res.rows) {
      const a = r.args ?? {};
      const prior = (a.prior_keep_id ?? "").toString();
      const sc = (a.scope ?? "").toString();
      if (!prior || !sc) continue;
      if (!(["person", "team", "company"] as const).includes(sc as LessonScope)) {
        continue;
      }
      const seq = _toNumber(r.seq, 0);
      const extractedAt =
        (a.extracted_at as string | undefined) ??
        (r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString());
      const row: ExperimentLessonRow = {
        priorKeepId: prior,
        scope: sc as LessonScope,
        lessonText: (a.lesson_text ?? "").toString(),
        lessonFeatures: (a.lesson_features ?? {}) as Record<string, string>,
        appliedToProposer: (a.applied_to_proposer ?? "autoresearch_loop").toString(),
        appliedAt:
          a.applied_at === null || a.applied_at === undefined
            ? null
            : _toNumber(a.applied_at, 0),
        proposedBy: (a.proposed_by ?? "autoresearch_loop").toString(),
        extractedAt,
        ledgerSeq: seq,
        receipt: {
          hash: r.hash_hex.slice(0, 12),
          source: "autoresearch_loop · learn",
          owner: (a.proposed_by ?? "autoresearch_loop").toString(),
          classification: "internal",
        },
      };
      const existing = byPrior.get(prior);
      if (!existing || seq > existing.ledgerSeq) {
        byPrior.set(prior, row);
      }
    }
    const all = [...byPrior.values()];
    all.sort((a, b) => b.ledgerSeq - a.ledgerSeq);
    return all.slice(0, Math.max(1, limit));
  }, fallback);
}

/**
 * Convenience: get the last N lessons across every scope, grouped.
 *
 * The /research LessonsCard renders three columns (Mine / Team / Company);
 * this returns each column's list pre-trimmed to ``limit``.
 */
export async function getExperimentLessonsByScope(
  companyId: string = DEFAULT_COMPANY_ID,
  limit = 5,
): Promise<{ person: ExperimentLessonRow[]; team: ExperimentLessonRow[]; company: ExperimentLessonRow[] }> {
  const [person, team, company] = await Promise.all([
    getExperimentLessons(companyId, "person", limit),
    getExperimentLessons(companyId, "team", limit),
    getExperimentLessons(companyId, "company", limit),
  ]);
  return { person, team, company };
}

// ---------------------------------------------------------------------------
// Demo-day P12 — First-Knowing surface on /research.
//
// Altman Q1: "What does the worm know that the org's CDO doesn't, with the
// ledger entry where it knew it first?" Surfaces phenomena the worm has
// detected (proposed) whose corresponding ``*_confirmed`` ledger entry has
// not yet landed.
//
// Folds three signals:
//   * ``emit_phenomenon_gap_detected`` execute rows (richest — carry
//     ``referenced_in_seq`` + ``confidence`` + ``novelty_key``)
//   * raw ``person_proposed`` and ``reactivity_proposed`` propose rows whose
//     ``proposed_by`` is a worm/agent identity
//   * a chatter-context window of ±3 ``chat_received`` rows around each
//     ``referenced_in_seq``
//
// Returns ``[]`` honestly when no first-knowings exist (CLAUDE.md ¶9). Mirrors
// the Python projection at
// ``apps/worm-core/src/wormbase_core/projections/first_knowings.py``; we
// re-implement the fold in TypeScript so the dashboard can read it directly
// off the singleton Postgres pool without round-tripping to worm-core.
// ---------------------------------------------------------------------------

const FIRST_KNOWING_RECENCY_HOURS: Record<FirstKnowingRecency, number | null> = {
  "1h": 1,
  "24h": 24,
  "7d": 24 * 7,
  all: null,
};

/**
 * Loose UUID heuristic — same shape as the canonical 36-char hyphenated form.
 * Used to decide whether ``proposed_by`` looks like a real Person id (UUID)
 * vs an agent label like ``"worm"`` or ``"phenomenon_gap_detector"``.
 */
function looksLikeUuid(s: string): boolean {
  if (s.length !== 36) return false;
  for (const c of s) {
    if (c === "-") continue;
    if (!/[0-9A-Fa-f]/.test(c)) return false;
  }
  return true;
}

const HUMAN_PROPOSER_DENYLIST = new Set(["admin", "human", "system"]);

function isWormProposer(proposedBy: string): boolean {
  if (!proposedBy) return false;
  if (HUMAN_PROPOSER_DENYLIST.has(proposedBy)) return false;
  if (looksLikeUuid(proposedBy)) return false;
  return true;
}

function gapKindToFirstKnowingKind(gapKind: string): FirstKnowingPhenomenonKind {
  if (gapKind === "kpi") return "kpi_gap";
  if (gapKind === "domain") return "domain_gap";
  if (gapKind === "process") return "process_gap";
  if (gapKind === "reactivity") return "reactivity_gap";
  return "kpi_gap";
}

function summarizePhenomenonGap(
  gapKind: string,
  suggested: Record<string, unknown>,
  confidence: number,
): string {
  const conf = confidence.toFixed(2);
  if (gapKind === "kpi") {
    const label =
      (suggested.label as string | undefined) ??
      (suggested.name as string | undefined) ??
      (suggested.kpi_label as string | undefined) ??
      "an unknown KPI";
    return `KPI gap detected: ${label} (confidence ${conf})`;
  }
  if (gapKind === "domain") {
    const label =
      (suggested.name as string | undefined) ??
      (suggested.domain as string | undefined) ??
      "an unknown domain";
    return `Domain gap detected: ${label} (confidence ${conf})`;
  }
  if (gapKind === "process") {
    const label =
      (suggested.label as string | undefined) ??
      (suggested.topic as string | undefined) ??
      "a recurring workflow";
    return `Process gap detected: ${label} (confidence ${conf})`;
  }
  if (gapKind === "reactivity") {
    const label =
      (suggested.name as string | undefined) ??
      (suggested.predicate as string | undefined) ??
      "an unobserved trigger";
    return `Reactivity gap detected: ${label} (confidence ${conf})`;
  }
  return `Phenomenon gap (${gapKind}) detected (confidence ${conf})`;
}

interface FirstKnowingsOptions {
  /** ``kind`` filter chip; ``undefined`` returns every kind. */
  kinds?: ReadonlyArray<FirstKnowingPhenomenonKind>;
  /** ``scope`` filter chip; ``undefined`` returns every scope. */
  scope?: FirstKnowingScope;
  /** ``recency`` filter chip; defaults to ``"all"``. */
  recency?: FirstKnowingRecency;
  /** Trim to N rows after filtering. Defaults to 50 (PRD §7 P12). */
  limit?: number;
}

export async function getFirstKnowings(
  companyId: string = DEFAULT_COMPANY_ID,
  options: FirstKnowingsOptions = {},
): Promise<FirstKnowingRow[]> {
  const fallback: FirstKnowingRow[] = [];
  const recency: FirstKnowingRecency = options.recency ?? "all";
  const limit = Math.max(1, options.limit ?? 50);

  return tryPg(async () => {
    // Pull every relevant row in a single round-trip; the projection is a
    // small in-memory fold afterwards.
    //
    // We tolerate two payload-naming conventions for phenomenon_gap_detected:
    //   * ``args.gap_kind`` — Pydantic field name in worm-core
    //   * ``args.kind``     — Pydantic alias used when serialising
    const sql = `
      WITH base AS (
        SELECT seq,
               ts,
               kind,
               payload,
               encode(hash, 'hex') AS hash_hex
          FROM ledger
         WHERE company_id = $1
           AND (
             kind IN ('propose', 'chat_received')
             OR (
               kind = 'execute'
               AND payload->>'tool' IN (
                 'emit_phenomenon_gap_detected',
                 'emit_phenomenon_gap_resolved',
                 'emit_person_confirmed',
                 'emit_person_archived',
                 'emit_kpi_confirmed',
                 'emit_reactivity_confirmed',
                 'emit_reactivity_disabled',
                 'emit_domain_confirmed',
                 'emit_data_product_confirmed',
                 'emit_data_product_published',
                 'emit_chat_received',
                 'channel_adapter.emit_chat_received',
                 'emit_person_proposed',
                 'emit_reactivity_proposed'
               )
             )
           )
         ORDER BY seq ASC
    )
    SELECT seq, ts, kind, payload, hash_hex FROM base
    `;
    const res = await pgQuery<{
      seq: number | string;
      ts: Date | string;
      kind: string;
      payload: Record<string, unknown>;
      hash_hex: string;
    }>(sql, [companyId]);

    if (res.rows.length === 0) return fallback;

    interface NormalizedRow {
      seq: number;
      ts: string;
      kind: string;
      payload: Record<string, unknown>;
      hashHex: string;
    }
    const rows: NormalizedRow[] = res.rows.map((r) => ({
      seq: _toNumber(r.seq, 0),
      ts: r.ts instanceof Date ? r.ts.toISOString() : new Date(r.ts).toISOString(),
      kind: r.kind,
      payload: r.payload ?? {},
      hashHex: r.hash_hex,
    }));

    // Pass 1 — confirmation index + chat_received index.
    const confirmedRefs = new Set<string>();
    const archivedRefs = new Set<string>();
    const chatBySeq = new Map<number, NormalizedRow>();
    const sortedChatSeqs: number[] = [];

    for (const row of rows) {
      if (row.kind === "chat_received") {
        chatBySeq.set(row.seq, row);
        sortedChatSeqs.push(row.seq);
        continue;
      }
      if (row.kind !== "execute") continue;
      const tool = row.payload.tool as string | undefined;
      const args = (row.payload.args as Record<string, unknown> | undefined) ?? {};
      if (
        tool === "emit_chat_received" ||
        tool === "channel_adapter.emit_chat_received"
      ) {
        chatBySeq.set(row.seq, row);
        sortedChatSeqs.push(row.seq);
        continue;
      }
      if (tool === "emit_person_confirmed") {
        const pid = String(args.person_id ?? "");
        if (pid) confirmedRefs.add(pid);
      } else if (tool === "emit_kpi_confirmed") {
        const kid = String(args.kpi_id ?? "");
        if (kid) confirmedRefs.add(kid);
      } else if (
        tool === "emit_reactivity_confirmed" ||
        tool === "emit_reactivity_disabled"
      ) {
        const rid = String(args.reactivity_id ?? "");
        if (rid) confirmedRefs.add(rid);
      } else if (tool === "emit_domain_confirmed") {
        const did = String(args.domain_id ?? "");
        if (did) confirmedRefs.add(did);
      } else if (
        tool === "emit_data_product_confirmed" ||
        tool === "emit_data_product_published"
      ) {
        const dpid = String(args.data_product_id ?? args.artifact_id ?? "");
        if (dpid) confirmedRefs.add(dpid);
      } else if (tool === "emit_phenomenon_gap_resolved") {
        const nk = String(args.novelty_key ?? "");
        if (nk) confirmedRefs.add(`phenomenon_gap:${nk}`);
      } else if (tool === "emit_person_archived") {
        const pid = String(args.person_id ?? "");
        if (pid) archivedRefs.add(pid);
      }
    }
    sortedChatSeqs.sort((a, b) => a - b);

    // Helper — resolve a propose row's matching execute payload (PEVR forward scan).
    const findExecuteArgs = (
      proposeSeq: number,
      targetKind: string,
    ): Record<string, unknown> => {
      const wanted = `emit_${targetKind}`;
      for (const r of rows) {
        if (r.seq <= proposeSeq) continue;
        if (r.seq > proposeSeq + 8) break;
        if (r.kind !== "execute") continue;
        if (r.payload.tool !== wanted) continue;
        return (r.payload.args as Record<string, unknown> | undefined) ?? {};
      }
      return {};
    };

    // Pass 2 — collect candidates.
    const seenKeys = new Set<string>();
    const out: FirstKnowingRow[] = [];

    // (a) phenomenon_gap_detected execute rows.
    for (const row of rows) {
      if (row.kind !== "execute") continue;
      if (row.payload.tool !== "emit_phenomenon_gap_detected") continue;
      const args = (row.payload.args as Record<string, unknown> | undefined) ?? {};
      const gapKind = String(args.gap_kind ?? args.kind ?? "");
      if (!gapKind) continue;
      const noveltyKey = String(args.novelty_key ?? "");
      const refId = noveltyKey
        ? `phenomenon_gap:${noveltyKey}`
        : `phenomenon_gap:${row.seq}`;
      const dedupKey = `phenomenon_gap_detected::${refId}`;
      if (seenKeys.has(dedupKey)) continue;
      if (confirmedRefs.has(refId)) continue;
      seenKeys.add(dedupKey);

      const confidence = _toNumber(args.confidence, 0);
      const refInSeq = _toNumber(args.referenced_in_seq, 0);
      const suggested =
        (args.suggested_proposal as Record<string, unknown> | undefined) ?? {};

      out.push({
        kind: gapKindToFirstKnowingKind(gapKind),
        summary: summarizePhenomenonGap(gapKind, suggested, confidence),
        firstDetectedSeq: row.seq,
        firstDetectedTs: row.ts,
        refId,
        referencedInSeq: refInSeq,
        confidence,
        noveltyKey,
        proposedBy: "phenomenon_gap_detector",
        targetKind: "phenomenon_gap_detected",
        scope: "company",
        chatterContext: [],
        receipt: {
          hash: row.hashHex.slice(0, 12),
          source: "phenomenon_gap_detector",
          owner: "phenomenon_gap_detector",
          classification: "internal",
        },
      });
    }

    // (b) raw person_proposed / reactivity_proposed — proposed_by a worm.
    for (const row of rows) {
      if (row.kind !== "propose") continue;
      const targetKind = String(row.payload.target_kind ?? "");
      const refId = String(row.payload.ref_id ?? "");
      const proposedBy = String(row.payload.proposed_by ?? "");
      if (!refId || !targetKind) continue;
      if (!isWormProposer(proposedBy)) continue;
      let kind: FirstKnowingPhenomenonKind;
      if (targetKind === "person_proposed") kind = "person_gap";
      else if (targetKind === "reactivity_proposed") kind = "reactivity_gap";
      else continue;
      if (confirmedRefs.has(refId) || archivedRefs.has(refId)) continue;
      const dedupKey = `${targetKind}::${refId}`;
      if (seenKeys.has(dedupKey)) continue;
      seenKeys.add(dedupKey);

      const args = findExecuteArgs(row.seq, targetKind);
      let summary: string;
      let scope: FirstKnowingScope;
      if (targetKind === "person_proposed") {
        const name = String(args.name ?? "an unidentified Person");
        const platform = String(args.platform ?? "unknown platform");
        summary = `Person gap: '${name}' on ${platform} not yet confirmed`;
        scope = "mine";
      } else {
        const label = String(
          args.name ?? args.predicate ?? "an unnamed Reactivity",
        );
        summary = `Reactivity gap: '${label}' proposed but not confirmed`;
        const audience = String(args.audience ?? "");
        if (audience.startsWith("person:")) scope = "mine";
        else if (audience.startsWith("team:")) scope = "team";
        else scope = "company";
      }

      out.push({
        kind,
        summary,
        firstDetectedSeq: row.seq,
        firstDetectedTs: row.ts,
        refId,
        referencedInSeq: 0,
        confidence: null,
        noveltyKey: "",
        proposedBy,
        targetKind,
        scope,
        chatterContext: [],
        receipt: {
          hash: row.hashHex.slice(0, 12),
          source: proposedBy,
          owner: proposedBy,
          classification: "internal",
        },
      });
    }

    // Filter chips.
    const wantedKinds = new Set<FirstKnowingPhenomenonKind>(
      options.kinds && options.kinds.length > 0
        ? options.kinds
        : ["kpi_gap", "domain_gap", "process_gap", "reactivity_gap", "person_gap"],
    );
    const recencyHours = FIRST_KNOWING_RECENCY_HOURS[recency];
    const cutoffTs =
      recencyHours === null ? null : Date.now() - recencyHours * 3600 * 1000;
    const filtered = out.filter((r) => {
      if (!wantedKinds.has(r.kind)) return false;
      if (options.scope && r.scope !== options.scope) return false;
      if (cutoffTs !== null && new Date(r.firstDetectedTs).getTime() < cutoffTs) {
        return false;
      }
      return true;
    });

    // Newest seq first.
    filtered.sort((a, b) => b.firstDetectedSeq - a.firstDetectedSeq);

    // Attach chatter context for each unique referencedInSeq.
    const ctxByAnchor = new Map<number, FirstKnowingChatRow[]>();
    const findAnchorPos = (anchor: number): number => {
      // Linear scan is fine — sortedChatSeqs is at most ~1000 in demo runs.
      for (let i = 0; i < sortedChatSeqs.length; i++) {
        if (sortedChatSeqs[i] === anchor) return i;
        if (sortedChatSeqs[i] > anchor) return i;
      }
      return -1;
    };
    for (const row of filtered) {
      const anchor = row.referencedInSeq;
      if (anchor <= 0) continue;
      if (ctxByAnchor.has(anchor)) {
        row.chatterContext = ctxByAnchor.get(anchor)!;
        continue;
      }
      const pos = findAnchorPos(anchor);
      let window: FirstKnowingChatRow[] = [];
      if (pos >= 0) {
        const lo = Math.max(0, pos - 3);
        const hi = Math.min(sortedChatSeqs.length, pos + 4);
        window = sortedChatSeqs.slice(lo, hi).map((s) => {
          const cr = chatBySeq.get(s);
          if (!cr) {
            return {
              seq: s,
              ts: "",
              channelId: "",
              senderPerson: "",
              text: "",
              isAnchor: s === anchor,
            };
          }
          const args =
            (cr.payload.args as Record<string, unknown> | undefined) ??
            (cr.payload as Record<string, unknown>);
          const channelId = String(args.channel_id ?? "");
          const senderPerson = String(args.sender_person ?? "");
          const text = String(args.text ?? "");
          return {
            seq: s,
            ts: cr.ts,
            channelId,
            senderPerson,
            text,
            isAnchor: s === anchor,
          };
        });
      }
      ctxByAnchor.set(anchor, window);
      row.chatterContext = window;
    }

    return filtered.slice(0, limit);
  }, fallback);
}

// ─── W4-C: /dashboard digest tile per-platform line ─────────────────────
//
// Activity rollup adds a per-platform breakdown for the digest tile on
// /dashboard. The brief: render an inline editorial line like
//
//   "Last 24h · 12 Slack messages · 4 WhatsApp DMs · 1 process map proposed · 0 KPI proposals"
//
// Counts are time-windowed (default 24h). Per-platform message counts come
// from grouping ``emit_chat_received`` entries by the platform inferred from
// the entry's ``channel_id`` shape — the same predicate the chat-presence
// reactivity uses on the Python side. Process-map and KPI counts are
// platform-agnostic — they aggregate across all chatter and dashboard-form
// origins.
//
// Schema-evolution doctrine pin: NO new entry kinds, NO new projections.
// Pure SQL aggregate against the already-canonical ``emit_chat_received`` /
// ``emit_process_map_proposed`` / ``emit_kpi_proposed`` tools.
//
// Capability honesty: when the ledger is silent across all four counters
// the renderer surfaces a "No activity in the last <window>" line per
// CLAUDE.md §9 — never a fabricated row of zeros.

export interface ActivityRollupPlatformLine {
  /** Platform slug from ``platform-status.ts`` (e.g. "slack", "whatsapp"). */
  platform: PlatformSlug;
  /** Number of chat_received entries inferred to this platform. */
  count: number;
  /**
   * Editorial unit label — "messages" for channel-shaped platforms,
   * "DMs" for WhatsApp (which is DM-first). The renderer uses this to
   * render the right noun without re-deriving it from the platform slug.
   */
  unitLabel: string;
}

export interface ActivityRollup {
  /**
   * Lookback window (seconds) the rollup was computed against. Mirrors
   * the ``windowSeconds`` opts passed in; 24h (86_400s) by default.
   */
  windowSeconds: number;
  /** Total chat_received entries across every recognized platform. */
  totalMessages: number;
  /**
   * Per-platform breakdown. Only platforms with non-zero counts are
   * present; a Slack-only deployment with zero WhatsApp activity returns
   * exactly one entry (Slack), which keeps the digest line byte-identical
   * to the pre-W4-C rendering for that case (capability-honest).
   * Sorted by count DESC; ties broken by the canonical PLATFORMS order
   * (Slack first, then preview platforms, then coming_soon).
   */
  perPlatform: ActivityRollupPlatformLine[];
  /** Process-map proposals in the window (platform-agnostic). */
  processMaps: number;
  /** KPI proposals in the window (platform-agnostic). */
  kpiProposals: number;
  /**
   * True when every counter is zero — the digest renderer uses this for
   * the honest "No activity in the last <window>" empty state instead of
   * fabricating a row of zeros.
   */
  isSilent: boolean;
}

export interface GetActivityRollupOpts {
  /**
   * Lookback window in seconds. Default 86_400 (24h). Bounded to
   * [60, 30 * 86_400] server-side so callers can't accidentally trigger
   * a full-table scan.
   */
  windowSeconds?: number;
}

const _DEFAULT_ROLLUP_WINDOW_S = 24 * 60 * 60;
const _MIN_ROLLUP_WINDOW_S = 60;
const _MAX_ROLLUP_WINDOW_S = 30 * 24 * 60 * 60;

function _emptyRollup(windowSeconds: number): ActivityRollup {
  return {
    windowSeconds,
    totalMessages: 0,
    perPlatform: [],
    processMaps: 0,
    kpiProposals: 0,
    isSilent: true,
  };
}

/** Editorial unit label per platform (canonical-honest noun for the line). */
function _unitLabelForPlatform(platform: PlatformSlug): string {
  // WhatsApp on the worm's wire is DM-first (channel = jid). Slack and
  // future channel-shaped platforms render "messages" generically.
  return platform === "whatsapp" ? "DMs" : "messages";
}

/**
 * Read the last-`windowSeconds` activity rollup for the digest tile on
 * /dashboard. Per-platform message counts come from ``emit_chat_received``
 * entries grouped by platform-shape inference on ``channel_id`` (reuses
 * W4-A's exported ``inferPlatformFromChannelId`` helper). Process-map and
 * KPI counts are platform-agnostic.
 *
 * Returns an honest empty rollup (``isSilent=true``, empty
 * ``perPlatform``) when the ledger is unavailable, when no rows fall in
 * the window, or when Postgres is disabled. The renderer surfaces the
 * empty line per CLAUDE.md §9 — never a row of zeros.
 */
export async function getActivityRollup(
  companyId: string = DEFAULT_COMPANY_ID,
  opts: GetActivityRollupOpts = {},
): Promise<ActivityRollup> {
  const requested = opts.windowSeconds ?? _DEFAULT_ROLLUP_WINDOW_S;
  const windowSeconds = Math.min(
    _MAX_ROLLUP_WINDOW_S,
    Math.max(_MIN_ROLLUP_WINDOW_S, requested),
  );

  return tryPg(async () => {
    // One SQL pass per kind. Three small aggregates is cheaper than one
    // CTE with NULL-padded columns and easier to read.
    const chatSql = `
      SELECT payload->'args'->>'channel_id' AS channel_id, COUNT(*)::int AS n
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' IN (
           'emit_chat_received',
           'channel_adapter.emit_chat_received'
         )
         AND ts >= NOW() - ($2 || ' seconds')::interval
       GROUP BY payload->'args'->>'channel_id'
    `;
    const procSql = `
      SELECT COUNT(*)::int AS n
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_process_map_proposed'
         AND ts >= NOW() - ($2 || ' seconds')::interval
    `;
    const kpiSql = `
      SELECT COUNT(*)::int AS n
        FROM ledger
       WHERE company_id = $1
         AND kind = 'execute'
         AND payload->>'tool' = 'emit_kpi_proposed'
         AND ts >= NOW() - ($2 || ' seconds')::interval
    `;
    const params = [companyId, String(windowSeconds)];
    const [chatRes, procRes, kpiRes] = await Promise.all([
      pgQuery<{ channel_id: string | null; n: number }>(chatSql, params),
      pgQuery<{ n: number }>(procSql, params),
      pgQuery<{ n: number }>(kpiSql, params),
    ]);

    // Group chat counts by inferred platform.
    const byPlatform = new Map<PlatformSlug, number>();
    let totalMessages = 0;
    for (const row of chatRes.rows) {
      const platform = inferPlatformFromChannelId(row.channel_id);
      const n = typeof row.n === "number" ? row.n : Number(row.n) || 0;
      totalMessages += n;
      if (!platform) continue; // unknown shape — count toward total but no badge
      byPlatform.set(platform, (byPlatform.get(platform) ?? 0) + n);
    }

    // Sort by count DESC; ties broken by canonical PLATFORMS order
    // (Slack first, preview next, coming_soon last). Zero-count
    // platforms are OMITTED — the digest line stays byte-identical for
    // Slack-only deployments where WhatsApp count is 0 (per the brief's
    // "Slack rendering on /dashboard byte-identical when WhatsApp count
    // is 0" hard constraint).
    const platformOrder: PlatformSlug[] = [
      "slack",
      "whatsapp",
      "discord",
      "teams",
      "signal",
    ];
    const perPlatform: ActivityRollupPlatformLine[] = Array.from(
      byPlatform.entries(),
    )
      .filter(([, count]) => count > 0)
      .sort(([aSlug, aN], [bSlug, bN]) => {
        if (bN !== aN) return bN - aN;
        return platformOrder.indexOf(aSlug) - platformOrder.indexOf(bSlug);
      })
      .map(([platform, count]) => ({
        platform,
        count,
        unitLabel: _unitLabelForPlatform(platform),
      }));

    const processMaps = procRes.rows[0]?.n ?? 0;
    const kpiProposals = kpiRes.rows[0]?.n ?? 0;
    const isSilent =
      totalMessages === 0 && processMaps === 0 && kpiProposals === 0;

    return {
      windowSeconds,
      totalMessages,
      perPlatform,
      processMaps,
      kpiProposals,
      isSilent,
    };
  }, _emptyRollup(windowSeconds));
}
