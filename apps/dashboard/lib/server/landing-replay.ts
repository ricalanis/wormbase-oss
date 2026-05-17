/**
 * Landing-page wire-replay helper (Phase 4 Task 4B).
 *
 * Above-the-fold visitors REPLAY a recorded tenant session in-browser
 * and see hash-receipted outputs. Click "replay" again — same hashes.
 * This file is the SSR side of that surface: it reads a fixed
 * ``until_ts`` window of ledger entries from the canonical demo tenant
 * (``baseworm``) and renders them as a Slack-thread-style stream of
 * messages with hash receipts.
 *
 * Determinism contract (institutional-AI thesis):
 *
 *   - Same ``until_ts`` + same ledger state → identical payload.
 *   - Two consecutive calls (with no intervening writes) yield byte-
 *     equal payload, including identical hashShorts and terminalHashHex.
 *
 * This helper deliberately does **not** use ``Ledger.replay()`` or
 * ``wormbase-tools replay_snapshot``: those compute KPI-state digests,
 * which is the wrong product for a thread-style preview. We instead read
 * canonical chat / kpi / source ledger entries directly and surface them
 * as messages, retaining each row's stored hash as the receipt. The hash
 * chain is the same one ``Ledger.replay()`` verifies — the surface is
 * different, the substrate is one.
 *
 * Demo-tenant choice
 * ==================
 * ``baseworm`` is the canonical sim-seeded tenant exercised by
 * ``make seed`` and the rest of the dashboard's surfaces. It carries
 * real ``emit_chat_received`` / ``emit_chat_sent`` traffic from the
 * sim-harness personas. The 1B.G ``--demo-tenants`` carousel tenants
 * (wormbase-saas-demo, etc.) are signup-stub-only — they exist for the
 * magic-link flow but carry no chat traffic, so they're not the right
 * fit for a thread preview.
 *
 * Fixture-fallback path
 * =====================
 * When Postgres is unreachable or baseworm has no chat traffic yet
 * (fresh dev tree before ``make seed``), we synthesise a deterministic
 * payload from a fixed prelude derived from the demo-fixture
 * ``TRACE_ENTRIES``. The synthesised hashes are the demo-fixture hash
 * column verbatim — same row, same hash, same receipt. The fallback
 * is hash-stable across re-runs by construction.
 */
import {
  pgQuery,
  DEFAULT_COMPANY_ID,
} from "../ledger-client";
import { TRACE_ENTRIES } from "../demo-fixture";
import { findTenantBySlug } from "../tenants";

/**
 * Slug of the demo tenant whose ledger drives the landing replay.
 *
 * ``baseworm`` is the canonical sim-seeded tenant. Changing this is a
 * breaking change for the landing-page hash receipt — visitors who took
 * a screenshot of the previous receipt would see a different hash on
 * their next visit.
 */
export const LANDING_REPLAY_DEMO_SLUG = "baseworm" as const;

/**
 * Fixed timestamp anchor for the replay window. Aligned with the
 * demo-fixture ``T0`` so the SSR fold lands on the same set of entries
 * the dashboard's other surfaces were built against.
 */
export const LANDING_REPLAY_UNTIL_TS = "2026-04-30T09:00:00Z" as const;

/** Maximum number of entries to surface in the hero thread. */
const LANDING_REPLAY_LIMIT = 6;

export type LandingReplayRole = "actor" | "worm" | "system";
export type LandingReplayStop = "ok" | "end_of_data";

export interface LandingReplayEntry {
  /** Stable id derived from the ledger row's ``seq`` (or fixture index). */
  id: string;
  /** RFC 3339 timestamp of the originating ledger entry. */
  ts: string;
  /** Display name (e.g. "Bob", "WormBase"). */
  who: string;
  /** Role bucket — drives the row's left-border colour in the viewer. */
  role: LandingReplayRole;
  /** Body text rendered as the message. */
  body: string;
  /** Underlying ledger kind (``chat_received``, ``chat_sent``, ``kpi_resolved``…). */
  kind: string;
  /** First 12 hex chars of the row's full SHA-256 hash. */
  hashShort: string;
}

export interface LandingReplay {
  tenantSlug: string;
  companyId: string;
  untilTs: string;
  /** First 12 hex chars of the terminal entry's hash. */
  terminalHashHex: string;
  entries: LandingReplayEntry[];
  stop: LandingReplayStop;
}

interface ReplayRow extends Record<string, unknown> {
  seq: number | string;
  ts: Date | string;
  kind: string;
  tool: string | null;
  args: Record<string, unknown> | null;
  hash_hex: string;
}

/**
 * Read a deterministic, hash-stable replay payload for the landing hero.
 *
 * No auth required: the landing page is pre-signup, and the demo tenant's
 * data is curated for public showcase. Two consecutive calls with no
 * intervening writes produce byte-equal payload.
 */
export async function getLandingReplay(): Promise<LandingReplay> {
  const tenant =
    findTenantBySlug(LANDING_REPLAY_DEMO_SLUG) ?? {
      slug: LANDING_REPLAY_DEMO_SLUG,
      companyId: DEFAULT_COMPANY_ID,
      displayName: "Baseworm",
    };

  if (!postgresEnabled()) {
    return synthesiseFromFixture(tenant.companyId);
  }

  try {
    const rows = await fetchReplayRows(tenant.companyId);
    if (rows.length === 0) {
      return synthesiseFromFixture(tenant.companyId);
    }
    const entries = rows.map(rowToEntry);
    const terminalHashHex = rows[rows.length - 1].hash_hex.slice(0, 12);
    return {
      tenantSlug: tenant.slug,
      companyId: tenant.companyId,
      untilTs: LANDING_REPLAY_UNTIL_TS,
      terminalHashHex,
      entries,
      stop: "end_of_data",
    };
  } catch {
    // Postgres is reachable in principle (DATABASE_URL is set) but the
    // query failed — fall through to the deterministic fixture path so
    // the landing page still renders the institutional-AI thesis.
    return synthesiseFromFixture(tenant.companyId);
  }
}

function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

/**
 * Read up to ``LANDING_REPLAY_LIMIT`` chat / kpi-resolution entries from
 * the canonical demo tenant, ordered chronologically. We bias the SQL to
 * the entries that read well as a Slack thread:
 *
 *   - ``emit_chat_received``  → role=actor (a real persona's message)
 *   - ``emit_chat_sent``      → role=worm  (the agent's reply)
 *   - ``emit_kpi_resolved``   → role=worm  (a hash-receipted KPI answer)
 *   - ``emit_source_profiled``→ role=worm  (bronze cascade complete)
 *
 * The four kinds are the institutional-AI demo-day arc: drop a file →
 * bronze cascade → KPI propose → answer with hash. Surfacing them at the
 * thread level lets a visitor *see* the loop close.
 */
async function fetchReplayRows(companyId: string): Promise<ReplayRow[]> {
  const sql = `
    SELECT seq,
           ts,
           kind,
           payload->>'tool' AS tool,
           payload->'args'  AS args,
           encode(hash, 'hex') AS hash_hex
      FROM ledger
     WHERE company_id = $1
       AND ts <= $2::timestamptz
       AND kind = 'execute'
       AND payload->>'tool' IN (
         'channel_adapter.emit_chat_received',
         'emit_chat_received',
         'channel_adapter.emit_chat_sent',
         'emit_chat_sent',
         'emit_kpi_resolved',
         'emit_source_profiled'
       )
     ORDER BY seq ASC
     LIMIT $3
  `;
  const res = await pgQuery<ReplayRow>(sql, [
    companyId,
    LANDING_REPLAY_UNTIL_TS,
    LANDING_REPLAY_LIMIT,
  ]);
  return res.rows;
}

function rowToEntry(row: ReplayRow): LandingReplayEntry {
  const tool = row.tool ?? "";
  const args = (row.args ?? {}) as Record<string, unknown>;
  const ts =
    row.ts instanceof Date ? row.ts.toISOString() : new Date(row.ts).toISOString();
  const kind =
    typeof tool === "string" && tool.includes("emit_")
      ? tool.replace(/^.*emit_/, "")
      : row.kind;

  let role: LandingReplayRole = "system";
  let who = "system";
  let body = "(no body)";

  const text = typeof args.text === "string" ? args.text : null;
  const sender = typeof args.sender_person === "string" ? args.sender_person : null;
  const senderName =
    typeof args.sender_name === "string"
      ? args.sender_name
      : sender
        ? `person:${sender.slice(0, 8)}`
        : null;

  if (tool.includes("emit_chat_received")) {
    role = "actor";
    who = senderName ?? "someone";
    body = text ?? "(message)";
  } else if (tool.includes("emit_chat_sent")) {
    role = "worm";
    who = "WormBase";
    body = text ?? "(reply)";
  } else if (tool.endsWith("emit_kpi_resolved")) {
    role = "worm";
    who = "WormBase";
    const kpi =
      typeof args.kpi_id === "string"
        ? args.kpi_id
        : typeof args.name === "string"
          ? args.name
          : "kpi";
    const value =
      typeof args.value === "number" || typeof args.value === "string"
        ? args.value
        : "(value)";
    body = `KPI ${kpi} resolved: ${value}`;
  } else if (tool.endsWith("emit_source_profiled")) {
    role = "worm";
    who = "WormBase";
    const uri =
      typeof args.uri === "string"
        ? args.uri
        : typeof args.source_id === "string"
          ? args.source_id
          : "(source)";
    body = `Profile complete: ${uri}`;
  }

  return {
    id: `e_${String(row.seq).padStart(4, "0")}`,
    ts,
    who,
    role,
    body,
    kind,
    hashShort: row.hash_hex.slice(0, 12),
  };
}

/**
 * Deterministic fallback derived from the demo-fixture ``TRACE_ENTRIES``.
 *
 * This is *not* a demo seam: the fixture entries are the same ones the
 * dashboard's other surfaces fall back to when the ledger is empty, and
 * every entry carries a precomputed hash from ``mkHash`` in
 * ``demo-fixture.ts``. The replay viewer surfaces those hashes verbatim.
 *
 * The picked subset is the canonical "drop file → bronze cascade → KPI
 * resolve" arc, which is the institutional-AI loop shown in 60 seconds.
 */
function synthesiseFromFixture(companyId: string): LandingReplay {
  // Pick the canonical arc:
  //   1. source_proposed (Bob drops the file)
  //   2. source_confirmed
  //   3. source_connected
  //   4. source_profiled
  //   5. kpi_proposed
  //   6. kpi_resolved
  // The fixture happens to expose all six in TRACE_ENTRIES; the picker
  // deduplicates by kind to land on six rows.
  const wanted: ReadonlyArray<{
    kind: string;
    role: LandingReplayRole;
    who: string;
    bodyFrom: (summary: string) => string;
  }> = [
    {
      kind: "source_proposed",
      role: "actor",
      who: "Bob",
      bodyFrom: (s) => `@worm ${s.replace(/^Source proposed:\s*/, "here is ")}`,
    },
    {
      kind: "source_confirmed",
      role: "worm",
      who: "WormBase",
      bodyFrom: (s) => s.replace(/accepted$/, "accepted; bronze cascade started."),
    },
    {
      kind: "source_connected",
      role: "worm",
      who: "WormBase",
      bodyFrom: (s) => s,
    },
    {
      kind: "source_profiled",
      role: "worm",
      who: "WormBase",
      bodyFrom: (s) => s,
    },
    {
      kind: "kpi_proposed",
      role: "worm",
      who: "WormBase",
      bodyFrom: (s) => s,
    },
    {
      kind: "kpi_resolved",
      role: "worm",
      who: "WormBase",
      bodyFrom: (s) => s,
    },
  ];

  const seen = new Set<string>();
  const entries: LandingReplayEntry[] = [];
  for (const entry of TRACE_ENTRIES) {
    if (entries.length >= LANDING_REPLAY_LIMIT) break;
    const slot = wanted.find(
      (w) => w.kind === entry.kind && !seen.has(w.kind),
    );
    if (!slot) continue;
    seen.add(slot.kind);
    const summary =
      typeof entry.payload?.summary === "string" ? entry.payload.summary : "";
    entries.push({
      id: entry.id,
      ts: entry.ts,
      who: slot.who,
      role: slot.role,
      body: slot.bodyFrom(summary),
      kind: entry.kind,
      hashShort: entry.hash.slice(0, 12),
    });
  }
  // Re-order by ts ascending (TRACE_ENTRIES iterates newest-first in some
  // call sites; the canonical arc reads chronologically).
  entries.sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  const terminal = entries[entries.length - 1];
  return {
    tenantSlug: LANDING_REPLAY_DEMO_SLUG,
    companyId,
    untilTs: LANDING_REPLAY_UNTIL_TS,
    terminalHashHex: terminal ? terminal.hashShort : "0".repeat(12),
    entries,
    stop: "end_of_data",
  };
}
