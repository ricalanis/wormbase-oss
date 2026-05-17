/**
 * /lake/overview read-side accessors — Lake-Side Overview tab (2026-05-16).
 *
 * Aggregates lightweight state + recent-activity gauges across the 8
 * lake-side compounding axes. The overview surface is the natural
 * landing page after the 8 individual axis tabs shipped — admins need
 * one screen that answers "what's happening in the lake right now"
 * without drilling into 8 separate pages.
 *
 * Three accessors:
 *
 *   * ``getLakeAxisStates`` — one row per axis, with proposed /
 *     affirmed / rejected counts. Honors the 3-pattern affirmative
 *     state doctrine (per 2026-06-09-l2-shipped.md): L3/L4/L5/L6/L7/L8
 *     use ``confirmed``, L1 uses ``promoted``, L2 uses ``acknowledged``.
 *
 *   * ``getLakeChains`` — static const-return of the 7 cross-axis
 *     chains. The shape is doctrine, not data. Includes one
 *     bidirectional chain (L4 ↔ L2) added by the L4↦L2 chain wave +
 *     reverse-arc polish bundle.
 *
 *   * ``getRecentLakeActivity`` — last N entries across all 8
 *     projections, merged in app code and sorted by ts DESC. Drill-in
 *     URLs reuse the producer-side deep-link primary-key filters from
 *     ``bdee480`` where the page supports it; otherwise links to the
 *     bare axis page.
 *
 * Postgres-first strategy: when DATABASE_URL is unset, every accessor
 * returns the honest empty shape (0/0/0 axis cards + [] activity). We
 * never substitute fixtures (per CLAUDE.md §9).
 *
 * Multi-tenant safe — every SQL filters by ``company_id``.
 */

import { pgQuery } from "./ledger-client";

// ─── Public types ─────────────────────────────────────────────────────────

/** Axis label — one of the 8 lake-side compounding axes. */
export type LakeAxisLabel =
  | "L1"
  | "L2"
  | "L3"
  | "L4"
  | "L5"
  | "L6"
  | "L7"
  | "L8";

/** Affirmative state name per the 3-pattern doctrine. */
export type AffirmativeStateLabel =
  | "confirmed"
  | "promoted"
  | "acknowledged";

/** One row in the axis-state grid on /lake/overview. */
export interface AxisStateRow {
  /** Axis label, e.g. ``"L5"``. */
  axis: LakeAxisLabel;
  /** Descriptive axis name surfaced on the card, e.g. ``"Fingerprinting"``. */
  axisName: string;
  /** Deep-link to the axis's detail page. */
  axisHref: string;
  /** Count of rows currently in the ``proposed`` state. */
  proposedCount: number;
  /** Count of rows currently in the per-axis affirmative state
   *  (``confirmed`` / ``promoted`` / ``acknowledged``). */
  affirmedCount: number;
  /** Label for the affirmative state — drives the badge prose. */
  affirmativeStateLabel: AffirmativeStateLabel;
  /** Count of rows currently in the ``rejected`` state. */
  rejectedCount: number;
}

/** One row in the cross-axis chain panel on /lake/overview. */
export interface CrossAxisChainRow {
  /** Forward label, e.g. ``"L5 → L7"`` or ``"L4 ↔ L2"``. */
  forward: string;
  /** One-line description of the chain semantics. */
  description: string;
  /** Producer page href (axis that emits the upstream evidence). */
  producerPage: string;
  /** Consumer page href (axis that reads the evidence). */
  consumerPage: string;
  /** True when both directions surface (L4 ↔ L2). */
  isBidirectional: boolean;
}

/** One row in the recent-activity stream on /lake/overview. */
export interface RecentActivityRow {
  /** Timestamp the state last changed (UTC). */
  ts: Date;
  /** Axis label, e.g. ``"L5"``. */
  axis: LakeAxisLabel;
  /** Action verb — derived from row's state per axis. e.g.
   *  ``"confirmed"`` / ``"promoted"`` / ``"acknowledged"`` /
   *  ``"proposed"`` / ``"rejected"``. */
  action: string;
  /** Brief target description, e.g. ``"semantic_type email on users.email"``. */
  description: string;
  /** Drill-in URL using producer-side deep-link param when the axis's
   *  page supports it; falls back to the bare axis page. */
  href: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function postgresEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL ?? process.env.WORMBASE_LEDGER_DSN);
}

function toInt(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return Number.isFinite(v) ? Math.trunc(v) : 0;
  const parsed = Number.parseInt(v, 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toDate(v: string | Date | null | undefined): Date {
  if (v instanceof Date) return v;
  if (!v) return new Date(0);
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? new Date(0) : d;
}

// ─── Per-axis static metadata ─────────────────────────────────────────────

interface AxisDescriptor {
  axis: LakeAxisLabel;
  axisName: string;
  axisHref: string;
  projectionTable: string;
  /** PK column on the projection — used for the recent-activity SELECT. */
  idColumn: string;
  affirmativeStateLabel: AffirmativeStateLabel;
  /** Producer-side deep-link URL param name on the axis's page.
   *  ``null`` when the axis page does not yet honor a primary-key
   *  filter (drill-in falls back to the bare page). */
  producerParam: string | null;
  /** Per-axis row → description renderer for the activity stream.
   *  Receives the raw row payload (snake_case from Postgres). */
  describe: (row: Record<string, unknown>) => string;
}

/** Compact identifier helper for activity row descriptions. */
function _truncId(v: unknown, n = 8): string {
  const s = String(v ?? "");
  if (s.length <= n) return s;
  return `${s.slice(0, n)}…`;
}

/** The 8 lake-side axes, with per-axis projection metadata. Static
 *  doctrine — not configuration. */
const AXES: AxisDescriptor[] = [
  {
    axis: "L1",
    axisName: "Source candidates",
    axisHref: "/lake/source-candidates",
    projectionTable: "projection_source_candidates",
    idColumn: "candidate_id",
    affirmativeStateLabel: "promoted",
    producerParam: "candidate_id",
    describe: (r) => {
      const kind = String(r.proposed_kind ?? "");
      const ident = String(r.proposed_identifier ?? "");
      return ident ? `${kind} candidate ${ident}` : `${kind} candidate`;
    },
  },
  {
    axis: "L2",
    axisName: "Catalog drift",
    axisHref: "/lake/catalog-drift",
    projectionTable: "projection_catalog_drifts",
    idColumn: "drift_id",
    affirmativeStateLabel: "acknowledged",
    producerParam: "drift_id",
    describe: (r) => {
      const kind = String(r.drift_kind ?? "");
      const table = String(r.table_id ?? "");
      const col = r.column as string | null;
      const target = col ? `${table}.${col}` : table;
      return target ? `${kind} on ${target}` : kind;
    },
  },
  {
    axis: "L3",
    axisName: "Lineage",
    axisHref: "/lake/lineage",
    projectionTable: "projection_lineage_edges",
    idColumn: "edge_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "edge_id",
    describe: (r) => {
      const src = String(r.src_table_id ?? "");
      const tgt = String(r.tgt_table_id ?? "");
      return src && tgt ? `${src} → ${tgt}` : "lineage edge";
    },
  },
  {
    axis: "L4",
    axisName: "Schema-impact",
    axisHref: "/lake/schema-impact",
    projectionTable: "projection_schema_impacts",
    idColumn: "impact_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "impact_id",
    describe: (r) => {
      const kind = String(r.impact_kind ?? "");
      const tgt = String(r.tgt_table_id ?? "");
      const col = r.tgt_column as string | null;
      const target = col ? `${tgt}.${col}` : tgt;
      return target ? `${kind} on ${target}` : kind;
    },
  },
  {
    axis: "L5",
    axisName: "Fingerprinting",
    axisHref: "/lake/semantic-types",
    projectionTable: "projection_semantic_types",
    idColumn: "type_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "type_id",
    describe: (r) => {
      const sem = String(r.semantic_type ?? "");
      const table = String(r.table_id ?? "");
      const col = r.column as string | null;
      const target = col ? `${table}.${col}` : table;
      return target ? `semantic_type ${sem} on ${target}` : `semantic_type ${sem}`;
    },
  },
  {
    axis: "L6",
    axisName: "Column classification",
    axisHref: "/lake/column-classification",
    projectionTable: "projection_column_classifications",
    idColumn: "classification_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "classification_id",
    describe: (r) => {
      const level = String(r.classification_level ?? "");
      const table = String(r.table_id ?? "");
      const col = r.column as string | null;
      const target = col ? `${table}.${col}` : table;
      return target ? `${level} on ${target}` : level;
    },
  },
  {
    axis: "L7",
    axisName: "Quality checks",
    axisHref: "/lake/quality",
    projectionTable: "projection_quality_checks",
    idColumn: "check_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "check_id",
    describe: (r) => {
      const kind = String(r.check_kind ?? "");
      const table = String(r.table_id ?? "");
      const col = r.column as string | null;
      const target = col ? `${table}.${col}` : table;
      return target ? `${kind} on ${target}` : kind;
    },
  },
  {
    axis: "L8",
    axisName: "Entity stitching",
    axisHref: "/lake/entity-stitches",
    projectionTable: "projection_entity_stitches",
    idColumn: "stitch_id",
    affirmativeStateLabel: "confirmed",
    producerParam: "stitch_id",
    describe: (r) => {
      const a = String(r.src_table_a ?? "");
      const b = String(r.src_table_b ?? "");
      const kind = String(r.entity_kind ?? "");
      return a && b ? `${kind} stitch ${a} ↔ ${b}` : `${kind} stitch`;
    },
  },
];

/** Map a row's ``state`` into the action verb shown in the activity
 *  stream. Honors the 3-pattern affirmative-state doctrine: ``confirmed``
 *  / ``promoted`` / ``acknowledged`` are kept verbatim; other states
 *  (``proposed`` / ``rejected``) carry through. */
function stateToAction(state: string): string {
  return state;
}

// ─── Public accessors ────────────────────────────────────────────────────

/**
 * Resolve per-axis state counts (proposed / affirmed / rejected) across
 * the 8 lake-side compounding axes for a tenant. One ``AxisStateRow``
 * per axis, in canonical L1..L8 reading order. The grid component
 * may re-order for layout.
 *
 * Postgres-first: 8 parallel ``SELECT state, COUNT(*) FROM
 * projection_X WHERE company_id = $1 GROUP BY state`` queries. Honest
 * empty (0/0/0 per axis) when DATABASE_URL is unset OR any individual
 * query throws — the page renders a non-misleading grid in either case.
 *
 * Multi-tenant safe — every SQL is parameterized + filtered by
 * company_id.
 */
export async function getLakeAxisStates(
  companyId: string,
): Promise<AxisStateRow[]> {
  const emptyRows: AxisStateRow[] = AXES.map((a) => ({
    axis: a.axis,
    axisName: a.axisName,
    axisHref: a.axisHref,
    proposedCount: 0,
    affirmedCount: 0,
    affirmativeStateLabel: a.affirmativeStateLabel,
    rejectedCount: 0,
  }));

  if (!postgresEnabled()) return emptyRows;

  const queries = AXES.map(async (axis) => {
    const sql = `
      SELECT state, COUNT(*)::int AS n
      FROM ${axis.projectionTable}
      WHERE company_id = $1
      GROUP BY state
    `;
    try {
      const res = await pgQuery<{ state: string; n: number | string }>(sql, [
        companyId,
      ]);
      let proposed = 0;
      let affirmed = 0;
      let rejected = 0;
      for (const row of res.rows) {
        const n = toInt(row.n);
        if (row.state === "proposed") proposed = n;
        else if (row.state === axis.affirmativeStateLabel) affirmed = n;
        else if (row.state === "rejected") rejected = n;
      }
      return {
        axis: axis.axis,
        axisName: axis.axisName,
        axisHref: axis.axisHref,
        proposedCount: proposed,
        affirmedCount: affirmed,
        affirmativeStateLabel: axis.affirmativeStateLabel,
        rejectedCount: rejected,
      } satisfies AxisStateRow;
    } catch {
      return {
        axis: axis.axis,
        axisName: axis.axisName,
        axisHref: axis.axisHref,
        proposedCount: 0,
        affirmedCount: 0,
        affirmativeStateLabel: axis.affirmativeStateLabel,
        rejectedCount: 0,
      } satisfies AxisStateRow;
    }
  });

  return Promise.all(queries);
}

/**
 * The 7 cross-axis chains forming the lake-side compounding spine.
 *
 * Static doctrine — not data. Returns a fresh array so callers can
 * filter/sort without mutating module-level state.
 *
 * The 7 chains (6 forward + 1 bidirectional):
 *
 *   * L4 → L3 — lineage-edge dependency drives impact (canonical
 *     producer/consumer chain; first cross-axis trace navigation
 *     in the lake stack).
 *   * L6 → L5 — semantic-type anchor for column classification.
 *   * L8 → L5 — semantic-type anchor for entity stitching.
 *   * L5 → L7 — semantic-type drives quality check kind.
 *   * L6 → L4 — governance classification elevates impact severity.
 *   * L5 → L4 — semantic-type elevates impact severity.
 *   * L4 ↔ L2 — bidirectional: acknowledged drift elevates impact
 *     (Half A); impact count surfaces on drift rows (Half B).
 */
export function getLakeChains(): CrossAxisChainRow[] {
  return [
    {
      forward: "L4 → L3",
      description:
        "Lineage-edge dependency drives impact (canonical producer/consumer chain).",
      producerPage: "/lake/lineage",
      consumerPage: "/lake/schema-impact",
      isBidirectional: false,
    },
    {
      forward: "L6 → L5",
      description: "Semantic-type anchor for column classification.",
      producerPage: "/lake/semantic-types",
      consumerPage: "/lake/column-classification",
      isBidirectional: false,
    },
    {
      forward: "L8 → L5",
      description: "Semantic-type anchor for entity stitching.",
      producerPage: "/lake/semantic-types",
      consumerPage: "/lake/entity-stitches",
      isBidirectional: false,
    },
    {
      forward: "L5 → L7",
      description: "Semantic-type drives quality check kind.",
      producerPage: "/lake/semantic-types",
      consumerPage: "/lake/quality",
      isBidirectional: false,
    },
    {
      forward: "L6 → L4",
      description: "Governance classification elevates impact severity.",
      producerPage: "/lake/column-classification",
      consumerPage: "/lake/schema-impact",
      isBidirectional: false,
    },
    {
      forward: "L5 → L4",
      description: "Semantic-type elevates impact severity.",
      producerPage: "/lake/semantic-types",
      consumerPage: "/lake/schema-impact",
      isBidirectional: false,
    },
    {
      forward: "L4 ↔ L2",
      description:
        "Acknowledged drift elevates impact (Half A); impact count surfaces on drift rows (Half B).",
      producerPage: "/lake/catalog-drift",
      consumerPage: "/lake/schema-impact",
      isBidirectional: true,
    },
  ];
}

/**
 * Resolve the most-recent ``limit`` projection state-changes across
 * all 8 lake-side axes for a tenant, merged + sorted by
 * ``state_changed_at`` DESC. The default ``limit`` is 20.
 *
 * Strategy: 8 parallel per-axis ``SELECT ... ORDER BY state_changed_at
 * DESC LIMIT $2`` queries against each projection; merge in app code;
 * sort + truncate. Each axis's row → description mapping is encoded in
 * the per-axis ``describe`` lambda above so the activity stream surface
 * stays generic.
 *
 * Drill-in URLs use the producer-side deep-link primary-key URL param
 * across all 8 axes (L1 candidate_id, L2 drift_id, L3 edge_id,
 * L4 impact_id, L5 type_id, L6 classification_id, L7 check_id,
 * L8 stitch_id). The original 4 producer-side filters shipped in
 * ``bdee480`` (L2/L3/L5/L6); the remaining 4 (L1/L4/L7/L8) shipped
 * in the 2026-05-16 close-out bundle.
 *
 * Honest empty when DATABASE_URL is unset / queries throw / no
 * activity yet — the page renders an empty-state panel.
 *
 * Multi-tenant safe — every SQL is parameterized + filtered by
 * company_id.
 */
export async function getRecentLakeActivity(
  companyId: string,
  limit = 20,
): Promise<RecentActivityRow[]> {
  if (!postgresEnabled()) return [];
  const cappedLimit = Math.max(1, Math.min(limit, 200));

  const perAxisQueries = AXES.map(async (axis) => {
    // Select the columns this axis's ``describe`` lambda + the
    // primary-key drill-in need. SELECT * keeps things uniform across
    // 8 projection shapes without losing future fields.
    const sql = `
      SELECT *
      FROM ${axis.projectionTable}
      WHERE company_id = $1
      ORDER BY state_changed_at DESC, ${axis.idColumn} ASC
      LIMIT $2
    `;
    try {
      const res = await pgQuery<Record<string, unknown>>(sql, [
        companyId,
        cappedLimit,
      ]);
      return res.rows.map((raw) => {
        const ts = toDate(
          (raw.state_changed_at ?? null) as string | Date | null,
        );
        const state = String(raw.state ?? "");
        const id = String(raw[axis.idColumn] ?? "");
        const href = axis.producerParam && id
          ? `${axis.axisHref}?${axis.producerParam}=${encodeURIComponent(id)}`
          : axis.axisHref;
        return {
          ts,
          axis: axis.axis,
          action: stateToAction(state),
          description: axis.describe(raw),
          href,
        } satisfies RecentActivityRow;
      });
    } catch {
      return [] as RecentActivityRow[];
    }
  });

  const perAxisRows = await Promise.all(perAxisQueries);
  const merged = perAxisRows.flat();
  merged.sort((a, b) => b.ts.getTime() - a.ts.getTime());
  return merged.slice(0, cappedLimit);
}

// ─── Re-export for tests ──────────────────────────────────────────────────

export const __test__ = {
  postgresEnabled,
  toInt,
  toDate,
  AXES,
  stateToAction,
  _truncId,
};
