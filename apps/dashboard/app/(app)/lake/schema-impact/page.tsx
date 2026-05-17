/**
 * /lake/schema-impact — L4 Sub-wave D (2026-06-02).
 *
 * Admin-only audit page for the L4 schema-evolution-impact inference
 * axis. This is the FIRST lake-side axis to consume another axis's
 * output (L3's confirmed lineage edges), and the FIRST dashboard surface
 * to render a cross-axis trace link (rows that came from L3 carry a
 * "view L3 edge" link to /lake/lineage).
 *
 * Sections (mirrors /lake/lineage + /lake/quality):
 *
 *   1. Strategy status banner — three rows (lineage_edge / dbt_test /
 *      type_coercion) via shared :class:`CapabilityBadges`.
 *
 *   2. L3-dependency note — explicit panel when L3 is enabled but has
 *      zero confirmed edges (handoff concern #9). Surfaced honestly so
 *      operators don't wonder why ``lineage_edge`` is wired but quiet.
 *
 *   3. Pending Proposals — candidate impacts with Confirm/Reject
 *      actions for admins; read-only for everyone else. Group-by
 *      toggle (source / impact_kind / target_table / strategy) per
 *      spec §4.1.
 *
 *   4. Confirmed Impacts — table view of approved impacts; expanding
 *      a row shows the strategy config + evidence + reasoning.
 *
 *   5. Rejected Impacts (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * Empty-state copy points operators at the env knob to enable L4.
 *   * Cross-axis trace linking — when ``upstream_lineage_edge_id`` is
 *     set on the row, the strategy cell renders a "view L3 edge"
 *     link to ``/lake/lineage?edge_id=<id>`` (first cross-axis
 *     dashboard nav in the lake stack).
 *   * Re-trigger affordance warns about
 *     ``WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS`` dedup.
 *   * ``getCurrentPerson(companyId)`` threads the caller's identity
 *     for admin gating (no placeholders).
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import { SchemaImpactProposalsTable } from "../../../../components/lake/SchemaImpactProposalsTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getConfirmedSchemaImpacts,
  getL3DependencyState,
  getL5DependencyState,
  getL6DependencyState,
  getProposedSchemaImpacts,
  getRejectedSchemaImpacts,
  getSchemaImpactStrategyStatus,
  type SchemaImpactFilter,
  type SchemaImpactRow,
  type SchemaImpactStrategyStatus,
} from "../../../../lib/schema-impact";
import { confirmSchemaImpact, rejectSchemaImpact } from "./actions";

/**
 * Per-page filter URL params (2026-05-16). Honored by the page
 * boundary + every accessor call below.
 *
 * Filter sources:
 *   * ``upstream_lineage_edge_id``    — R1 reverse arc (from /lake/lineage)
 *   * ``upstream_classification_id``  — R5 reverse arc (from /lake/column-classification)
 *   * ``upstream_semantic_type_id``   — R6 reverse arc (from /lake/semantic-types)
 *   * ``source_id`` + ``src_table`` [+ ``src_column``] — L4↦L2 Half B
 *     composite (from /lake/catalog-drift)
 *
 * Multiple params compose with AND. Honest empty when no rows match.
 */
type SchemaImpactSearchParams = {
  upstream_lineage_edge_id?: string;
  upstream_classification_id?: string;
  upstream_semantic_type_id?: string;
  source_id?: string;
  src_table?: string;
  src_column?: string;
  /** Producer-side primary-key deep-link (2026-05-16 — Lake-Side
   *  Overview activity-stream drill-in). Narrows to the single impact
   *  identified by ``impact_id``. */
  impact_id?: string;
};

/** Helper: pluck the first param if it is an array (Next.js can pass
 *  arrays when a key repeats). Returns ``undefined`` when absent. */
function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

/** Build a :class:`SchemaImpactFilter` from a Next.js searchParams
 *  blob. Returns ``undefined`` when no recognised filter param is
 *  present so the accessors short-circuit and produce no WHERE
 *  fragment. */
function parseSchemaImpactFilter(
  searchParams: SchemaImpactSearchParams | Record<string, string | string[] | undefined>,
): SchemaImpactFilter | undefined {
  const f: SchemaImpactFilter = {
    upstreamLineageEdgeId: firstParam(
      searchParams.upstream_lineage_edge_id as string | string[] | undefined,
    ),
    upstreamClassificationId: firstParam(
      searchParams.upstream_classification_id as string | string[] | undefined,
    ),
    upstreamSemanticTypeId: firstParam(
      searchParams.upstream_semantic_type_id as string | string[] | undefined,
    ),
    sourceId: firstParam(searchParams.source_id as string | string[] | undefined),
    srcTable: firstParam(searchParams.src_table as string | string[] | undefined),
    srcColumn: firstParam(searchParams.src_column as string | string[] | undefined),
    impactId: firstParam(searchParams.impact_id as string | string[] | undefined),
  };
  // Strip undefined entries — also short-circuit when nothing matched.
  const cleaned: SchemaImpactFilter = {};
  let any = false;
  if (f.upstreamLineageEdgeId) {
    cleaned.upstreamLineageEdgeId = f.upstreamLineageEdgeId;
    any = true;
  }
  if (f.upstreamClassificationId) {
    cleaned.upstreamClassificationId = f.upstreamClassificationId;
    any = true;
  }
  if (f.upstreamSemanticTypeId) {
    cleaned.upstreamSemanticTypeId = f.upstreamSemanticTypeId;
    any = true;
  }
  if (f.sourceId) {
    cleaned.sourceId = f.sourceId;
    any = true;
  }
  if (f.srcTable) {
    cleaned.srcTable = f.srcTable;
    any = true;
  }
  if (f.srcColumn) {
    cleaned.srcColumn = f.srcColumn;
    any = true;
  }
  if (f.impactId) {
    cleaned.impactId = f.impactId;
    any = true;
  }
  return any ? cleaned : undefined;
}

/** Convert the filter back to the URL-param dict for the
 *  :class:`ActiveFilterChips` row. Mirrors the URL-param naming so
 *  the chip labels read the same as the deeplink the user clicked. */
function filterToChipMap(
  filter: SchemaImpactFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return {
    upstream_lineage_edge_id: filter.upstreamLineageEdgeId,
    upstream_classification_id: filter.upstreamClassificationId,
    upstream_semantic_type_id: filter.upstreamSemanticTypeId,
    source_id: filter.sourceId,
    src_table: filter.srcTable,
    src_column: filter.srcColumn,
    impact_id: filter.impactId,
  };
}

/**
 * Read an upstream-id key off a SchemaImpact's evidence dict,
 * handling both shapes the L4 composite produces:
 *
 *   1. Top-level: evidence[idKey] when a single strategy fired.
 *   2. Composite-merged: evidence[strategyKey][idKey] when multiple
 *      strategies merged onto the same canonical tuple (the L4
 *      composite stores per-strategy sub-dicts).
 *
 * Returns the first non-empty string match in (composite, top-level)
 * preference order. Used by the chain-link rendering for L6/L5/L2 —
 * NOT for L3 which lives on a first-class column (``upstreamLineageEdgeId``).
 */
function readUpstreamEvidenceId(
  evidence: Record<string, unknown> | undefined,
  strategyKey: string,
  idKey: string,
): string | null {
  if (!evidence) return null;
  const sub = evidence[strategyKey] as Record<string, unknown> | undefined;
  const compositeVal =
    typeof sub?.[idKey] === "string" ? (sub[idKey] as string) : null;
  if (compositeVal) return compositeVal;
  const topVal =
    typeof evidence[idKey] === "string" ? (evidence[idKey] as string) : null;
  return topVal;
}

/** Export for tests. */
export const __test__ = {
  parseSchemaImpactFilter,
  filterToChipMap,
  firstParam,
  readUpstreamEvidenceId,
};

export const metadata = { title: "WormBase · Lake · Schema-impact audit" };

export const dynamic = "force-dynamic";

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtChangeDesc(row: SchemaImpactRow): string {
  return `${row.srcTable} · ${row.srcColumn} (${row.changeKind})`;
}

function fmtTarget(row: SchemaImpactRow): string {
  return `${row.tgtTableId} · ${row.tgtColumn}`;
}

export default async function LakeSchemaImpactPage({
  searchParams,
}: {
  searchParams?: SchemaImpactSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. The
  // banner accessors (strategy status, L3/L5/L6 dependency probes)
  // remain filter-blind — those summarise tenant-scoped global state,
  // not per-row narrowing.
  const filter = parseSchemaImpactFilter(searchParams ?? {});

  const [
    proposed,
    confirmed,
    rejected,
    strategyStatus,
    l3Dependency,
    l6Dependency,
    l5Dependency,
  ] = await Promise.all([
    getProposedSchemaImpacts(companyId, { filter }),
    getConfirmedSchemaImpacts(companyId, { filter }),
    getRejectedSchemaImpacts(companyId, { days: 30, filter }),
    getSchemaImpactStrategyStatus(companyId),
    getL3DependencyState(companyId),
    getL6DependencyState(companyId),
    getL5DependencyState(companyId),
  ]);

  const totalImpacts = proposed.length + confirmed.length + rejected.length;

  // L3-dependency banner triggers when L3 is enabled (the master switch
  // is on) but there are no confirmed edges yet. We render the panel
  // unconditionally honest — if L3 is disabled entirely, the strategy
  // banner above already says so via the `lineage_edge` row.
  const showL3DependencyBanner =
    l3Dependency.l3Enabled && l3Dependency.confirmedEdgeCount === 0;

  // L6-dependency banner mirrors the L3 one — the 5th cross-axis chain
  // (L6→L4 governance elevation). When L6 is enabled but has no
  // confirmed classifications, the governance_classification strategy
  // is wired but quiet; the banner surfaces the dependency honestly so
  // operators know to confirm classifications in /lake/column-classification.
  const showL6DependencyBanner =
    l6Dependency.l6Enabled && l6Dependency.confirmedClassificationCount === 0;

  // L5-dependency banner mirrors the L3 + L6 ones — the 6th
  // cross-axis chain (L5→L4 semantic-type elevation, last of the 3
  // originally-foreshadowed peer-axis chains). When L5 is enabled but
  // has no confirmed semantic types, the semantic_type strategy is
  // wired but quiet; the banner surfaces the dependency honestly so
  // operators know to confirm semantic types in /lake/semantic-types.
  const showL5DependencyBanner =
    l5Dependency.l5Enabled && l5Dependency.confirmedSemanticTypeCount === 0;

  return (
    <PageBoundary
      surface="lake schema-impact"
      traceQuery="?surface=lake.schema_impact"
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Semantic layer · schema-impact audit · admin
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Schema-impact audit · {totalImpacts}{" "}
          {totalImpacts === 1 ? "impact" : "impacts"}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
          }}
        >
          The L4 inference axis proposes candidate downstream impacts
          when an upstream column is added, dropped, or its type changes.
          It is the first lake-side axis to consume another axis&apos;s
          output — the ``lineage_edge`` strategy reads L3&apos;s
          confirmed lineage edges to map upstream changes to downstream
          tables. Admins confirm or reject; the projection folds each
          decision forward. Every confirmation and rejection writes a
          ledger entry — replay-stable, audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="schema-impact-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/schema-impact"
        labels={{
          upstream_lineage_edge_id: "upstream lineage edge",
          upstream_classification_id: "upstream classification",
          upstream_semantic_type_id: "upstream semantic type",
          source_id: "source",
          src_table: "src table",
          src_column: "src column",
          impact_id: "Impact ID",
        }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges per
          handoff concern #5. Rendered first so the operator knows what
          the productive surface is before scanning proposals. */}
      <section
        data-testid="schema-impact-strategy-status-banner"
        style={{
          border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          background: "var(--wb-color-paper-deep, #f4eedb)",
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            L4 inference strategy status
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontSize: 13,
              maxWidth: 720,
            }}
          >
            Which inference strategies can produce schema-impact
            proposals in this tenant today. ``productive · L3-dependent``
            = wired against L3&apos;s confirmed edges;
            ``configured · awaiting-L3-edges`` = strategy is correct
            but L3 has no confirmed edges yet;
            ``configured · empty-upstream`` = strategy is correct but
            its upstream emits nothing yet (Wave 1 dbt-test gap);
            ``disabled`` = env knob off.
          </p>
        </header>
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {strategyStatus.map((row: SchemaImpactStrategyStatus) => (
            <li
              key={row.strategy}
              data-testid={`schema-impact-strategy-row-${row.strategy}`}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(160px, 200px) 1fr",
                gap: 12,
                alignItems: "flex-start",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
                color: "var(--wb-color-aged-ink, #2a2620)",
              }}
            >
              <code
                className="wb-mono"
                style={{
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink, #2a2620)",
                  paddingTop: 2,
                }}
              >
                {row.strategy}
              </code>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <CapabilityBadges
                  kind="policy"
                  id={`schema-impact-${row.strategy}`}
                  status={row.badge}
                  statusNote={row.note}
                />
                {row.badgeLabelOverride ? (
                  <span
                    className="wb-mono"
                    data-testid={`schema-impact-strategy-override-${row.strategy}`}
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-sepia-warning-deep, #b6741c)",
                    }}
                  >
                    {row.badgeLabelOverride}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* L3-DEPENDENCY BANNER — handoff concern #9. Surfaced when L3 is
          enabled but has zero confirmed edges, so operators understand
          why the lineage_edge strategy is wired but quiet. */}
      {showL3DependencyBanner ? (
        <section
          data-testid="schema-impact-l3-dependency-banner"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            L3 dependency · awaiting confirmations
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontStyle: "italic",
            }}
          >
            No L3 edges available — L4 awaits L3 confirmations. The
            ``lineage_edge`` strategy reads L3&apos;s confirmed lineage
            edges to map upstream column changes to downstream tables.
            Confirm at least one edge in{" "}
            <a
              href="/lake/lineage"
              data-testid="schema-impact-l3-dependency-link"
              className="wb-mono"
              style={{
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              /lake/lineage
            </a>{" "}
            and the strategy graduates to productive automatically.
            ``type_coercion`` does not depend on L3 and produces
            impacts independently when L4 is enabled.
          </p>
        </section>
      ) : null}

      {/* L6-DEPENDENCY BANNER — 5th cross-axis chain (L6→L4 governance
          elevation). Surfaced when L6 is enabled but has zero confirmed
          classifications, so operators understand why the
          ``governance_classification`` strategy is wired but quiet. */}
      {showL6DependencyBanner ? (
        <section
          data-testid="schema-impact-l6-dependency-banner"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            L6 dependency · awaiting governance confirmations
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontStyle: "italic",
            }}
          >
            No L6 classifications available — governance elevation awaits
            L6 confirmations. The ``governance_classification`` strategy
            reads L6&apos;s confirmed column classifications
            (regulated / pii / confidential) and elevates the impact
            severity when a changed column is governance-sensitive.
            Confirm at least one classification in{" "}
            <a
              href="/lake/column-classification"
              data-testid="schema-impact-l6-dependency-link"
              className="wb-mono"
              style={{
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              /lake/column-classification
            </a>{" "}
            and the strategy graduates to productive automatically.
            Other strategies (``lineage_edge`` / ``dbt_test`` /
            ``type_coercion``) are independent of L6.
          </p>
        </section>
      ) : null}

      {/* L5-DEPENDENCY BANNER — 6th cross-axis chain (L5→L4 semantic-
          type elevation), the last of the 3 originally-foreshadowed
          peer-axis chains. Surfaced when L5 is enabled but has zero
          confirmed semantic types, so operators understand why the
          ``semantic_type`` strategy is wired but quiet. */}
      {showL5DependencyBanner ? (
        <section
          data-testid="schema-impact-l5-dependency-banner"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            }}
          >
            L5 dependency · awaiting semantic-type confirmations
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontStyle: "italic",
            }}
          >
            No L5 semantic types available — semantic-type elevation
            awaits L5 confirmations. The ``semantic_type`` strategy
            reads L5&apos;s confirmed semantic types (email / uuid /
            phone / pii_* / custom) and elevates impact severity to
            ``high`` when a changed column is semantically typed.
            Confirm at least one semantic type in{" "}
            <a
              href="/lake/semantic-types"
              data-testid="schema-impact-l5-dependency-link"
              className="wb-mono"
              style={{
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              /lake/semantic-types
            </a>{" "}
            and the strategy graduates to productive automatically.
            Other strategies (``lineage_edge`` / ``dbt_test`` /
            ``type_coercion`` / ``governance_classification``) are
            independent of L5.
          </p>
        </section>
      ) : null}

      {totalImpacts === 0 ? (
        <EmptyState
          testId="lake-schema-impact-empty"
          eyebrow="no impacts yet"
          title="No schema impacts proposed yet."
          description={
            "The L4 inference axis fires on external_catalog_imported " +
            "cascades when an upstream column is added, dropped, or " +
            "its type changes. Set " +
            "WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true and " +
            "re-import a catalog after a schema change — proposals " +
            "land within the next compounding window."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <SchemaImpactProposalsTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmSchemaImpact}
              rejectAction={rejectSchemaImpact}
            />
          ) : (
            <section
              data-testid="schema-impact-proposals-empty"
              style={{
                border: "1px dashed var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper-deep)",
                padding: 14,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Pending proposals · 0
              </span>
              <p
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                  fontSize: 13,
                }}
              >
                No candidate impacts awaiting review. New proposals
                appear as the L4 inference axis fires on incoming
                catalog snapshots with column-level deltas.
              </p>
            </section>
          )}

          {/* CONFIRMED IMPACTS */}
          <section
            data-testid="schema-impact-confirmed-section"
            style={{ display: "flex", flexDirection: "column", gap: 8 }}
          >
            <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Confirmed impacts · {confirmed.length}
              </span>
              <p
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-aged-ink)",
                  fontSize: 13,
                  maxWidth: 720,
                }}
              >
                Approved schema impacts, with the strategy that proposed
                them + the confidence + the approving admin. Expand a
                row for the strategy-specific evidence dict + reasoning
                + the upstream L3 lineage edge (when applicable).
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="schema-impact-confirmed-empty"
                style={{
                  border: "1px dashed var(--wb-color-paper-edge)",
                  background: "var(--wb-color-paper-deep)",
                  padding: 14,
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                  fontSize: 13,
                }}
              >
                No confirmed impacts yet. Approve a pending proposal to
                see the audit table fill in.
              </div>
            ) : (
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  background: "var(--wb-color-paper, #f8f3e1)",
                  border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
                  fontSize: 12,
                }}
              >
                <thead>
                  <tr
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-hash-gray)",
                      background: "var(--wb-color-paper-deep)",
                    }}
                  >
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Change
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Downstream
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Impact kind
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "right" }}>
                      Conf.
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Strategy
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Confirmed at
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {confirmed.map((r) => (
                    <tr
                      key={r.impactId}
                      data-testid={`schema-impact-confirmed-row-${r.impactId}`}
                    >
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {fmtChangeDesc(r)}
                        </code>
                      </td>
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {fmtTarget(r)}
                        </code>
                      </td>
                      <td style={{ padding: "6px 12px" }}>
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {r.impactKind}
                        </code>
                      </td>
                      <td
                        style={{
                          padding: "6px 12px",
                          textAlign: "right",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        {fmtConfidence(r.confidence)}
                      </td>
                      <td style={{ padding: "6px 12px" }}>
                        <div
                          style={{ display: "flex", flexDirection: "column", gap: 2 }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {r.strategy}
                          </code>
                          {r.upstreamLineageEdgeId ? (
                            <a
                              href={`/lake/lineage?edge_id=${encodeURIComponent(r.upstreamLineageEdgeId)}`}
                              data-testid={`schema-impact-confirmed-l3-link-${r.impactId}`}
                              className="wb-mono"
                              style={{
                                fontSize: 9,
                                letterSpacing: "0.08em",
                                textTransform: "uppercase",
                                color:
                                  "var(--wb-color-botanical-green-deep, #2d5d3a)",
                                textDecoration: "underline",
                              }}
                            >
                              view L3 edge →
                            </a>
                          ) : null}
                          {/* L6→L4 cross-axis row link — surfaced when
                              the governance_classification strategy
                              stamped evidence.upstream_classification_id
                              onto the impact. Mirrors the L3 link.

                              When the impact is a composite-merged row
                              (both governance AND semantic_type fired
                              on the same canonical tuple), the evidence
                              dict is keyed by strategy name — read both
                              the top-level keys (single-strategy rows)
                              AND the strategy-keyed sub-dicts (merged
                              composite rows).

                              L2 link (2026-05-16 producer-side deep-link
                              bundle) closes the L4↦L2 evidence-link
                              asymmetry: when the acknowledged_drift
                              strategy stamps ``upstream_drift_id`` (top-
                              level OR composite-merged under the
                              ``acknowledged_drift`` strategy key), the
                              row renders a "view L2 drift →" link to
                              ``/lake/catalog-drift?drift_id=<id>``. */}
                          {(() => {
                            const govEvidence =
                              (r.evidence?.[
                                "governance_classification"
                              ] as Record<string, unknown> | undefined) ?? null;
                            const govClsId =
                              ((govEvidence?.["upstream_classification_id"] ??
                                r.evidence?.["upstream_classification_id"]) as
                                | string
                                | undefined) ?? null;
                            const govSeverity =
                              ((govEvidence?.["governance_severity"] ??
                                r.evidence?.["governance_severity"]) as
                                | string
                                | undefined) ?? null;
                            // L5→L4 chain — semantic_type strategy.
                            const semEvidence =
                              (r.evidence?.["semantic_type"] as
                                | Record<string, unknown>
                                | undefined) ?? null;
                            const semTypeId =
                              ((semEvidence?.["upstream_semantic_type_id"] ??
                                r.evidence?.["upstream_semantic_type_id"]) as
                                | string
                                | undefined) ?? null;
                            const semSeverity =
                              ((semEvidence?.["semantic_type_severity"] ??
                                r.evidence?.["semantic_type_severity"]) as
                                | string
                                | undefined) ?? null;
                            const semType =
                              ((semEvidence?.["semantic_type"] ??
                                r.evidence?.["semantic_type"]) as
                                | string
                                | undefined) ?? null;
                            // L4↦L2 chain — acknowledged_drift strategy.
                            // Read top-level OR composite-merged
                            // ``acknowledged_drift.upstream_drift_id``.
                            const ackEvidence =
                              (r.evidence?.["acknowledged_drift"] as
                                | Record<string, unknown>
                                | undefined) ?? null;
                            const driftId =
                              ((ackEvidence?.["upstream_drift_id"] ??
                                r.evidence?.["upstream_drift_id"]) as
                                | string
                                | undefined) ?? null;
                            return (
                              <>
                                {govSeverity ? (
                                  <span
                                    className="wb-mono"
                                    data-testid={`schema-impact-confirmed-gov-severity-${r.impactId}`}
                                    style={{
                                      fontSize: 9,
                                      letterSpacing: "0.08em",
                                      textTransform: "uppercase",
                                      color:
                                        govSeverity === "critical"
                                          ? "var(--wb-color-destructive-deep, #a32a1f)"
                                          : "var(--wb-color-sepia-warning-deep, #b6741c)",
                                      border: "1px solid currentColor",
                                      padding: "1px 4px",
                                      borderRadius: 2,
                                      alignSelf: "flex-start",
                                    }}
                                  >
                                    gov: {govSeverity}
                                  </span>
                                ) : null}
                                {govClsId ? (
                                  <a
                                    href={`/lake/column-classification?classification_id=${encodeURIComponent(govClsId)}`}
                                    data-testid={`schema-impact-confirmed-l6-link-${r.impactId}`}
                                    className="wb-mono"
                                    style={{
                                      fontSize: 9,
                                      letterSpacing: "0.08em",
                                      textTransform: "uppercase",
                                      color:
                                        "var(--wb-color-botanical-green-deep, #2d5d3a)",
                                      textDecoration: "underline",
                                    }}
                                  >
                                    view L6 classification →
                                  </a>
                                ) : null}
                                {semSeverity ? (
                                  <span
                                    className="wb-mono"
                                    data-testid={`schema-impact-confirmed-sem-severity-${r.impactId}`}
                                    style={{
                                      fontSize: 9,
                                      letterSpacing: "0.08em",
                                      textTransform: "uppercase",
                                      color:
                                        "var(--wb-color-sepia-warning-deep, #b6741c)",
                                      border: "1px solid currentColor",
                                      padding: "1px 4px",
                                      borderRadius: 2,
                                      alignSelf: "flex-start",
                                    }}
                                  >
                                    sem: {semSeverity}
                                    {semType ? ` (${semType})` : ""}
                                  </span>
                                ) : null}
                                {semTypeId ? (
                                  <a
                                    href={`/lake/semantic-types?type_id=${encodeURIComponent(semTypeId)}`}
                                    data-testid={`schema-impact-confirmed-l5-link-${r.impactId}`}
                                    className="wb-mono"
                                    style={{
                                      fontSize: 9,
                                      letterSpacing: "0.08em",
                                      textTransform: "uppercase",
                                      color:
                                        "var(--wb-color-botanical-green-deep, #2d5d3a)",
                                      textDecoration: "underline",
                                    }}
                                  >
                                    view L5 semantic type →
                                  </a>
                                ) : null}
                                {driftId ? (
                                  <a
                                    href={`/lake/catalog-drift?drift_id=${encodeURIComponent(driftId)}`}
                                    data-testid={`schema-impact-confirmed-l2-link-${r.impactId}`}
                                    className="wb-mono"
                                    style={{
                                      fontSize: 9,
                                      letterSpacing: "0.08em",
                                      textTransform: "uppercase",
                                      color:
                                        "var(--wb-color-botanical-green-deep, #2d5d3a)",
                                      textDecoration: "underline",
                                    }}
                                  >
                                    view L2 drift →
                                  </a>
                                ) : null}
                              </>
                            );
                          })()}
                        </div>
                      </td>
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                          color: "var(--wb-color-hash-gray)",
                        }}
                      >
                        {r.stateChangedAt}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* REJECTED IMPACTS (collapsed by default) */}
          <details
            data-testid="schema-impact-rejected-section"
            style={{
              border: "1px solid var(--wb-color-paper-edge)",
              background: "var(--wb-color-paper)",
              padding: "10px 12px",
            }}
          >
            <summary
              className="wb-mono"
              style={{
                cursor: "pointer",
                fontSize: 11,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              Rejected impacts · {rejected.length} · last 30 days
            </summary>
            <div style={{ marginTop: 10 }}>
              {rejected.length === 0 ? (
                <p
                  style={{
                    margin: 0,
                    fontFamily: "var(--wb-font-serif)",
                    fontStyle: "italic",
                    color: "var(--wb-color-hash-gray)",
                    fontSize: 13,
                  }}
                >
                  No impacts rejected in the last 30 days.
                </p>
              ) : (
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 12,
                  }}
                >
                  <thead>
                    <tr
                      className="wb-mono"
                      style={{
                        fontSize: 10,
                        letterSpacing: "0.12em",
                        textTransform: "uppercase",
                        color: "var(--wb-color-hash-gray)",
                      }}
                    >
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Change
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Downstream
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Impact kind
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Strategy
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>
                        Conf.
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Rejected at
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rejected.map((r) => (
                      <tr
                        key={r.impactId}
                        data-testid={`schema-impact-rejected-row-${r.impactId}`}
                      >
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {fmtChangeDesc(r)}
                          </code>
                        </td>
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {fmtTarget(r)}
                          </code>
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {r.impactKind}
                          </code>
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {r.strategy}
                          </code>
                        </td>
                        <td
                          style={{
                            padding: "6px 8px",
                            textAlign: "right",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          {fmtConfidence(r.confidence)}
                        </td>
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                            color: "var(--wb-color-hash-gray)",
                          }}
                        >
                          {r.stateChangedAt}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </details>
        </>
      )}
    </PageBoundary>
  );
}
