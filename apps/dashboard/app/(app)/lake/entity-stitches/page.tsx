/**
 * /lake/entity-stitches — L8 Sub-wave D (2026-06-07).
 *
 * Admin-only audit page for the L8 cross-source entity-stitching axis.
 * The sixth lake-side compounding axis (after L3 lineage, L7 quality,
 * L4 schema-impact, L5 semantic-types, L6 column-classification) AND
 * the THIRD cross-axis chain (after L4→L3 and L6→L5). The NameMatch
 * strategy's semantic-type-anchor path reads L5's confirmed semantic
 * types via the **reused** L6 ``ConfirmedSemanticTypeReader`` Protocol
 * — second consumer of the same Protocol, validating the
 * consumer-owned-Protocol pattern generalises.
 *
 * Sections (mirrors L3/L7/L4/L5/L6):
 *
 *   1. Strategy status banner — three rows (name_match /
 *      sample_overlap / schema_shape) via shared
 *      :class:`CapabilityBadges`. Honest postures per L8 design §7:
 *        * ``name_match``      — 4 honest postures keyed off the L8
 *          anchor sub-knob + the L5 confirmed-type count probe:
 *          productive · L5-dependent / configured · awaiting-L5-types
 *          / configured · L5-disabled / productive · fuzzy-only.
 *        * ``schema_shape``    — productive (when columns available)
 *          + "currently quiet — awaits per-column catalog imports"
 *          qualifier per Sub-wave C handoff concern #1.
 *        * ``sample_overlap``  — configured · empty-upstream (NoopSampler today).
 *
 *   2. L5-dependency note — explicit panel when the NameMatch anchor
 *      is enabled but L5 has zero confirmed types (mirrors L6's
 *      L5-dependency banner).
 *
 *   3. Pending Proposals — candidate stitches with Confirm/Reject
 *      actions for admins; read-only for everyone else. Group-by
 *      toggle (entity_kind / strategy). High-density advisory above
 *      the table when rows > 200 (Sub-wave C handoff concern #2).
 *
 *   4. Confirmed Stitches — table view of approved stitches;
 *      expanding a row shows the strategy config + evidence +
 *      reasoning (including ``upstream_semantic_type_id`` when the
 *      NameMatch anchor path fired).
 *
 *   5. Rejected Stitches (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * #1 SchemaShape no-op today (banner qualifier + close-out tracker).
 *   * #2 Pair enumeration O(N²) — high-density advisory in the table.
 *   * #3 ``entity_kind`` admin override out of scope this sub-wave
 *      (future enhancement; confirm posts without override).
 *   * #4 NameMatch fuzzy → entity_kind="other" rendered as muted slate
 *      chip in :class:`EntityKindChip`.
 *   * #5 Tenant scope closure returns [] today, moot for this surface.
 *   * Cross-axis trace linking — when ``upstreamSemanticTypeId`` is
 *      set on the row, the strategy cell renders a "view L5 semantic
 *      type →" link to ``/lake/semantic-types?type_id=<id>`` (third
 *      cross-axis dashboard nav in the lake stack; matches L4→L3 and
 *      L6→L5 patterns).
 *   * Re-trigger affordance warns about
 *      ``WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS`` dedup.
 *   * ``getCurrentPerson(companyId)`` threads the caller's identity
 *      for admin gating (no placeholders).
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { EntityKindChip } from "../../../../components/lake/EntityKindChip";
import { EntityStitchStrategyBanner } from "../../../../components/lake/EntityStitchStrategyBanner";
import { EntityStitchesTable } from "../../../../components/lake/EntityStitchesTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getConfirmedEntityStitches,
  getEntityStitchStrategyStatus,
  getL5DependencyStateForStitches,
  getProposedEntityStitches,
  getRejectedEntityStitches,
  type EntityStitchFilter,
  type EntityStitchRow,
} from "../../../../lib/entity-stitches";
import { confirmEntityStitch, rejectEntityStitch } from "./actions";

/**
 * Per-page filter URL param (2026-05-16). Honored by the page
 * boundary + every accessor call below.
 *
 * Filter source: R3 reverse arc (from /lake/semantic-types).
 */
type EntityStitchSearchParams = {
  upstream_semantic_type_id?: string;
  /** Producer-side primary-key deep-link (2026-05-16 — Lake-Side
   *  Overview activity-stream drill-in). Narrows to the single
   *  entity-stitch identified by ``stitch_id``. */
  stitch_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseEntityStitchFilter(
  searchParams:
    | EntityStitchSearchParams
    | Record<string, string | string[] | undefined>,
): EntityStitchFilter | undefined {
  const upstreamSemanticTypeId = firstParam(
    searchParams.upstream_semantic_type_id as
      | string
      | string[]
      | undefined,
  );
  const stitchId = firstParam(
    searchParams.stitch_id as string | string[] | undefined,
  );
  const cleaned: EntityStitchFilter = {};
  let any = false;
  if (upstreamSemanticTypeId) {
    cleaned.upstreamSemanticTypeId = upstreamSemanticTypeId;
    any = true;
  }
  if (stitchId) {
    cleaned.stitchId = stitchId;
    any = true;
  }
  return any ? cleaned : undefined;
}

function filterToChipMap(
  filter: EntityStitchFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return {
    upstream_semantic_type_id: filter.upstreamSemanticTypeId,
    stitch_id: filter.stitchId,
  };
}

/** Export for tests. */
export const __test__ = {
  parseEntityStitchFilter,
  filterToChipMap,
};

export const metadata = {
  title: "WormBase · Lake · Entity-stitch audit",
};

export const dynamic = "force-dynamic";

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtPair(row: EntityStitchRow): string {
  return `${row.srcTableA}·${row.srcColumnA} ↔ ${row.srcTableB}·${row.srcColumnB}`;
}

export default async function LakeEntityStitchesPage({
  searchParams,
}: {
  searchParams?: EntityStitchSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. Banner
  // accessors (strategy status, L5 dependency probe) remain
  // filter-blind — those summarise tenant-scoped state.
  const filter = parseEntityStitchFilter(searchParams ?? {});

  const [proposed, confirmed, rejected, strategyStatus, l5Dependency] =
    await Promise.all([
      getProposedEntityStitches(companyId, { filter }),
      getConfirmedEntityStitches(companyId, { filter }),
      getRejectedEntityStitches(companyId, { days: 30, filter }),
      getEntityStitchStrategyStatus(companyId),
      getL5DependencyStateForStitches(companyId),
    ]);

  const totalStitches = proposed.length + confirmed.length + rejected.length;

  // L5-dependency banner triggers when the NameMatch anchor is wired
  // (sub-knob on) AND L5 is enabled but there are no confirmed types
  // yet. Honest panel — if the anchor sub-knob is off or L5 is
  // disabled entirely, the strategy banner above already says so via
  // the ``name_match`` row.
  const anchorEnabled =
    (process.env.WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED ?? "")
      .toLowerCase()
      .trim() === "true" &&
    (process.env.WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED ?? "")
      .toLowerCase()
      .trim() === "true";
  const showL5DependencyBanner =
    anchorEnabled &&
    l5Dependency.l5Enabled &&
    l5Dependency.confirmedSemanticTypeCount === 0;

  return (
    <PageBoundary
      surface="lake entity-stitches"
      traceQuery="?surface=lake.entity_stitches"
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
          Semantic layer · entity-stitch audit · admin
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
          Entity-stitch audit · {totalStitches}{" "}
          {totalStitches === 1 ? "proposal" : "proposals"}
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
          The L8 inference axis proposes cross-source entity stitches —
          two columns on two different sources that refer to the same
          real-world entity — from the strict 8-value enum (person /
          organization / transaction / product / event / location /
          session / other). Three strategies vote: ``name_match``
          (cross-axis chain into L5 via the reused L6
          ``ConfirmedSemanticTypeReader`` Protocol — shared semantic
          types at 0.90; normalised Levenshtein on column names at
          0.60-0.75), ``sample_overlap`` (Jaccard on sampled values at
          0.50-0.85), ``schema_shape`` (parent-table structural
          similarity at 0.50-0.75). The third cross-axis chain in the
          lake stack (after L4→L3 and L6→L5). Admins confirm or reject;
          the projection folds each decision forward. Every confirmation
          and rejection writes a ledger entry — replay-stable,
          audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="entity-stitch-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/entity-stitches"
        labels={{
          upstream_semantic_type_id: "upstream semantic type",
          stitch_id: "Entity stitch",
        }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges. */}
      <EntityStitchStrategyBanner rows={strategyStatus} />

      {/* L5-DEPENDENCY BANNER — surfaced when the NameMatch anchor is
          enabled and L5 is enabled but has zero confirmed types.
          Mirrors L6's L5-dependency banner pattern. */}
      {showL5DependencyBanner ? (
        <section
          data-testid="entity-stitch-l5-dependency-banner"
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
            L5 dependency · awaiting confirmations
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
            No L5 confirmed semantic types available — L8&apos;s
            NameMatch anchor path awaits L5 confirmations. The anchor
            reads L5&apos;s confirmed semantic types via the reused L6
            ``ConfirmedSemanticTypeReader`` Protocol and proposes a
            stitch at 0.90 confidence when both endpoints share a
            confirmed type (e.g. both ``pii_email`` → entity_kind=
            person). The fuzzy-name sub-path still runs at 0.60-0.75
            with entity_kind=other. Confirm at least one type in{" "}
            <a
              href="/lake/semantic-types"
              data-testid="entity-stitch-l5-dependency-link"
              className="wb-mono"
              style={{
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              /lake/semantic-types
            </a>{" "}
            and the anchor path graduates to productive automatically.
          </p>
        </section>
      ) : null}

      {totalStitches === 0 ? (
        <EmptyState
          testId="lake-entity-stitches-empty"
          eyebrow="no stitches yet"
          title="No cross-source entity stitches proposed yet."
          description={
            "The L8 inference axis fires on external_catalog_imported " +
            "cascades and enumerates cross-source column pairs to " +
            "propose stitches. Set " +
            "WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true and import " +
            "catalogs on at least two sources — proposals land within " +
            "the next compounding window. NameMatch fuzzy path fires " +
            "immediately on similar column names; the anchor path " +
            "graduates once at least one L5 type is confirmed; " +
            "SchemaShape graduates once per-column catalog import " +
            "flows land; SampleOverlap graduates once a real per-source " +
            "sampler is bound."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <EntityStitchesTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmEntityStitch}
              rejectAction={rejectEntityStitch}
            />
          ) : (
            <section
              data-testid="entity-stitch-proposals-empty"
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
                No entity-stitch proposals awaiting review. New
                proposals appear as the L8 inference axis fires on
                incoming catalog snapshots.
              </p>
            </section>
          )}

          {/* CONFIRMED STITCHES */}
          <section
            data-testid="entity-stitch-confirmed-section"
            style={{ display: "flex", flexDirection: "column", gap: 8 }}
          >
            <header
              style={{ display: "flex", flexDirection: "column", gap: 2 }}
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
                Confirmed stitches · {confirmed.length}
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
                Approved cross-source entity stitches, with the strategy
                that proposed them + the confidence + the approving
                admin. When the ``name_match`` strategy fired through
                the semantic-type-anchor path, the row links to the L5
                semantic type that drove the stitch (third cross-axis
                chain).
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="entity-stitch-confirmed-empty"
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
                No confirmed stitches yet. Approve a pending proposal to
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
                      Endpoints (a ↔ b)
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Entity kind
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
                      key={r.stitchId}
                      data-testid={`entity-stitch-confirmed-row-${r.stitchId}`}
                    >
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {fmtPair(r)}
                        </code>
                      </td>
                      <td style={{ padding: "6px 12px" }}>
                        <EntityKindChip
                          kind={r.entityKind}
                          testIdSuffix={`confirmed-${r.stitchId}`}
                        />
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
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 2,
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {r.strategy}
                          </code>
                          {r.upstreamSemanticTypeId ? (
                            <a
                              href={`/lake/semantic-types?type_id=${encodeURIComponent(r.upstreamSemanticTypeId)}`}
                              data-testid={`entity-stitch-confirmed-l5-link-${r.stitchId}`}
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

          {/* REJECTED STITCHES (collapsed by default) */}
          <details
            data-testid="entity-stitch-rejected-section"
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
              Rejected stitches · {rejected.length} · last 30 days
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
                  No stitches rejected in the last 30 days.
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
                        Endpoints (a ↔ b)
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Entity kind
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
                        key={r.stitchId}
                        data-testid={`entity-stitch-rejected-row-${r.stitchId}`}
                      >
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {fmtPair(r)}
                          </code>
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <EntityKindChip
                            kind={r.entityKind}
                            testIdSuffix={`rejected-${r.stitchId}`}
                          />
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
