/**
 * /lake/catalog-drift — L2 Sub-wave D (2026-06-09).
 *
 * Admin-only audit page for the L2 catalog-drift triage axis. The
 * 8th and FINAL lake-side compounding axis surface in this wave
 * generation (after L3 lineage, L7 quality, L4 schema-impact, L5
 * semantic-types, L6 column-classification, L8 entity-stitch, L1
 * source-candidates). Closes out the L-axis family at 24 of 30 cap.
 *
 * L2 is the **detection / triage** layer for catalog drift. The
 * catalog-mirror's W5a Reactivity already emits
 * ``external_catalog_drift_detected`` as the raw structural-change
 * record; L2 layers inference-bearing strategies on top
 * (table_set / column_set / column_type) and routes proposals
 * through admin acknowledge / reject.
 *
 * L2 does NOT add a peer-L-axis cross-axis chain — its
 * ``CatalogSnapshotReader`` Protocol reads catalog-mirror substrate
 * (``external_catalog_imported`` ledger entries), NOT another
 * L-axis's confirmed projection. Per L1's doctrine clarification
 * (§4.6), lightweight Readers reading first-class platform
 * projections / catalog-mirror substrate are NOT cross-axis chains
 * in the L4→L3 / L6→L5 / L8→L5 sense. Cross-axis chain count stays
 * at 3.
 *
 * Spec §10 foreshadows a future L4→L2-acknowledged-drift chain that
 * would surface an "→ see impact analysis" link from acknowledged
 * rows; this is **deferred** in Wave 1 (the join isn't easily
 * available today and the spec marks it out-of-scope).
 *
 * Sections (mirrors L1/L8/L6/L5/L4/L7/L3):
 *
 *   1. Strategy status banner — three rows (table_set / column_set /
 *      column_type) via shared :class:`CapabilityBadges`. Honest
 *      postures per spec §4.7 + Sub-wave C handoff concerns #1-#4 —
 *      see :func:`getCatalogDriftStrategyStatus` for the full matrix.
 *
 *   2. Pending Drifts — drift triage with Acknowledge/Reject actions
 *      for admins; read-only for everyone else. Group-by toggle
 *      (drift_kind / source_id). High-density advisory above the
 *      table when rows > 200 (mirrors L1's discipline).
 *
 *   3. Acknowledged Drifts — admin-signed-off rows for audit.
 *
 *   4. Rejected Drifts (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * #1 ``list_columns`` returns () today — column_set + column_type
 *     strategies surface ``configured · empty-upstream`` until
 *     catalog-mirror Wave 2 lands per-column ingest. ColumnSpec +
 *     ColumnType remain honest empty-upstream.
 *   * #2 TableSetDriftStrategy is shape-productive but bottlenecked
 *     on upstream — today's ``external_catalog_imported`` payload
 *     doesn't carry per-table lists. Banner surfaces this with
 *     ``configured · awaiting-richer-catalog-substrate`` honestly.
 *   * #3 ``WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE`` knob is forward-
 *     compat (read but not consumed yet). Not surfaced in Wave 1.
 *   * #4 Body keys are ``driftId`` (camelCase) + ``drift_id``
 *     (snake_case) — dashboard actions emit snake_case; responses
 *     carry both; either form is accepted.
 *   * ``getCurrentPerson(companyId)`` threads the caller's identity
 *     for admin gating (no placeholders).
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { BeforeAfterDelta } from "../../../../components/lake/BeforeAfterDelta";
import { CatalogDriftStrategyBanner } from "../../../../components/lake/CatalogDriftStrategyBanner";
import { CatalogDriftsTable } from "../../../../components/lake/CatalogDriftsTable";
import { DriftKindChip } from "../../../../components/lake/DriftKindChip";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getAcknowledgedCatalogDrifts,
  getCatalogDriftStrategyStatus,
  getImpactCountByDriftSource,
  getProposedCatalogDrifts,
  getRejectedCatalogDrifts,
  makeImpactCountKey,
  type CatalogDriftFilter,
} from "../../../../lib/catalog-drift";
import { acknowledgeCatalogDrift, rejectCatalogDrift } from "./actions";

export const metadata = {
  title: "WormBase · Lake · Catalog-drift triage",
};

export const dynamic = "force-dynamic";

/**
 * Per-page filter URL param (2026-05-16 — producer-side deep-link
 * bundle). Honored by the page boundary + every projection accessor
 * below.
 *
 * Filter source: L4 row's NEW "view L2 drift →" chain link writes
 * ``?drift_id=<id>`` when the impact's evidence carries
 * ``upstream_drift_id`` (top-level OR composite-merged
 * ``acknowledged_drift.upstream_drift_id``). Closes the L4↦L2
 * evidence-link asymmetry.
 */
type CatalogDriftSearchParams = {
  drift_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseCatalogDriftFilter(
  searchParams:
    | CatalogDriftSearchParams
    | Record<string, string | string[] | undefined>,
): CatalogDriftFilter | undefined {
  const driftId = firstParam(
    searchParams.drift_id as string | string[] | undefined,
  );
  if (!driftId) return undefined;
  return { driftId };
}

function filterToChipMap(
  filter: CatalogDriftFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return { drift_id: filter.driftId };
}

/** Export for tests. */
export const __test__ = {
  parseCatalogDriftFilter,
  filterToChipMap,
};

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtTarget(d: {
  sourceId: string;
  tableId: string;
  column: string | null;
}): string {
  const tail = d.column ? `.${d.column}` : "";
  return `${d.sourceId}.${d.tableId}${tail}`;
}

export default async function LakeCatalogDriftPage({
  searchParams,
}: {
  searchParams?: CatalogDriftSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. The
  // banner + reverse-arc impact-count map remain filter-blind.
  const filter = parseCatalogDriftFilter(searchParams ?? {});

  // L4↦L2 cross-axis enrichment (Half B): fetch downstream-impact
  // roll-up counts in parallel. Empty map renders no badges (honest
  // empty state); never blocks the page on the cross-axis read.
  const [
    proposed,
    acknowledged,
    rejected,
    strategyStatus,
    impactCounts,
  ] = await Promise.all([
    getProposedCatalogDrifts(companyId, { filter }),
    getAcknowledgedCatalogDrifts(companyId, { filter }),
    getRejectedCatalogDrifts(companyId, { days: 30, filter }),
    getCatalogDriftStrategyStatus(companyId),
    getImpactCountByDriftSource(companyId),
  ]);

  const totalDrifts = proposed.length + acknowledged.length + rejected.length;
  const totalImpactedDrifts = Object.keys(impactCounts).length;

  return (
    <PageBoundary
      surface="lake catalog-drift"
      traceQuery="?surface=lake.catalog_drift"
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
          Semantic layer · catalog-drift triage · admin
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
          Catalog-drift triage · {totalDrifts}{" "}
          {totalDrifts === 1 ? "drift" : "drifts"}
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
          The L2 inference axis detects catalog drift between
          successive ``external_catalog_imported`` snapshots and
          surfaces one of five drift kinds for admin triage:
          ``table_added`` / ``table_removed`` / ``column_added`` /
          ``column_removed`` / ``column_type_changed``. Three
          strategies (table_set / column_set / column_type) compute
          the per-snapshot diffs through a lightweight
          ``CatalogSnapshotReader`` Protocol that reads catalog-mirror
          substrate (NOT another L-axis&apos;s output — cross-axis
          chain count stays at 3). Admins acknowledge (the drift is
          known/expected, no downstream effect) or reject (false
          positive / inconsequential / expected_change / out_of_scope
          / other). Every decision writes a ledger entry — replay-
          stable, audit-grade. L2 is the **8th and FINAL** lake-side
          axis in this wave generation; the L-axis family closes here
          at 24 of 30 cap.
        </p>
      </header>

      <ActiveFilterChips
        testId="catalog-drift-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/catalog-drift"
        labels={{ drift_id: "Catalog drift" }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges. */}
      <CatalogDriftStrategyBanner rows={strategyStatus} />

      {totalDrifts === 0 ? (
        <EmptyState
          testId="lake-catalog-drift-empty"
          eyebrow="no drifts yet"
          title="No catalog drifts proposed yet."
          description={
            "The L2 inference axis fires on " +
            "``external_catalog_imported`` snapshot changes and " +
            "proposes drift events for admin triage. Set " +
            "WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true plus the " +
            "per-strategy sub-knobs (TABLE_SET / COLUMN_SET / " +
            "COLUMN_TYPE) and proposals land as the upstream catalog-" +
            "mirror substrate populates: table_set once any source " +
            "has ≥2 catalog snapshots with carryable per-table " +
            "deltas; column_set and column_type once catalog-mirror " +
            "Wave 2 ships per-column ingest."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING DRIFTS */}
          {proposed.length > 0 ? (
            <CatalogDriftsTable
              rows={proposed}
              isAdmin={isAdmin}
              acknowledgeAction={acknowledgeCatalogDrift}
              rejectAction={rejectCatalogDrift}
              impactCounts={impactCounts}
            />
          ) : (
            <section
              data-testid="catalog-drift-proposals-empty"
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
                Pending drifts · 0
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
                No catalog-drift proposals awaiting triage. New drifts
                appear as the L2 inference axis fires on upstream
                ``external_catalog_imported`` snapshot changes.
              </p>
            </section>
          )}

          {/* ACKNOWLEDGED DRIFTS */}
          <section
            data-testid="catalog-drift-acknowledged-section"
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
                Acknowledged drifts · {acknowledged.length}
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
                Drifts signed off by admin as known/expected — purely
                a record of operator disposition (no downstream
                pipeline trigger). The **L4↦L2 reverse arc**
                (shipped 2026-06-12) surfaces a "↪ N downstream
                impacts via L4" badge on rows whose column has L4
                schema-evolution-impact entries — clicking the badge
                jumps to ``/lake/schema-impact`` filtered to the
                drift's tuple.
                {totalImpactedDrifts > 0 ? (
                  <>
                    {" "}Currently <strong>{totalImpactedDrifts}</strong>{" "}
                    drift{totalImpactedDrifts === 1 ? "" : "s"} have
                    downstream impact rows.
                  </>
                ) : null}
              </p>
            </header>
            {acknowledged.length === 0 ? (
              <div
                data-testid="catalog-drift-acknowledged-empty"
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
                No drifts acknowledged yet. Acknowledge a pending
                proposal to see the audit table fill in.
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
                      Drift (kind · target)
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Before → After
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "right" }}>
                      Conf.
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Strategy
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Acknowledged at
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {acknowledged.map((r) => {
                    const ackImpactCount =
                      impactCounts[
                        makeImpactCountKey(r.sourceId, r.tableId, r.column)
                      ];
                    const ackHasImpacts =
                      typeof ackImpactCount === "number" &&
                      ackImpactCount > 0;
                    const ackImpactHref = (() => {
                      const params = new URLSearchParams();
                      params.set("source_id", r.sourceId);
                      params.set("src_table", r.tableId);
                      if (r.column) params.set("src_column", r.column);
                      return `/lake/schema-impact?${params.toString()}`;
                    })();
                    return (
                    <tr
                      key={r.driftId}
                      data-testid={`catalog-drift-acknowledged-row-${r.driftId}`}
                    >
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 4,
                          }}
                        >
                          <DriftKindChip
                            kind={r.driftKind}
                            testIdSuffix={`ack-${r.driftId}`}
                          />
                          <code
                            className="wb-mono"
                            style={{ fontSize: 11 }}
                          >
                            {fmtTarget(r)}
                          </code>
                          {ackHasImpacts ? (
                            <a
                              href={ackImpactHref}
                              data-testid={`catalog-drift-impact-badge-ack-${r.driftId}`}
                              className="wb-mono"
                              style={{
                                fontSize: 10,
                                letterSpacing: "0.08em",
                                color:
                                  "var(--wb-color-sepia-warning-deep, #b6741c)",
                                textDecoration: "none",
                                marginTop: 2,
                                cursor: "pointer",
                              }}
                              title="View L4 schema-evolution-impact rows for this drift's column"
                            >
                              {`↪ ${ackImpactCount} downstream impact${
                                ackImpactCount === 1 ? "" : "s"
                              } via L4`}
                            </a>
                          ) : null}
                        </div>
                      </td>
                      <td style={{ padding: "6px 12px" }}>
                        <BeforeAfterDelta
                          driftKind={r.driftKind}
                          before={r.before}
                          after={r.after}
                          testIdSuffix={`ack-${r.driftId}`}
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
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {r.strategy}
                        </code>
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
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>

          {/* REJECTED DRIFTS (collapsed by default) */}
          <details
            data-testid="catalog-drift-rejected-section"
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
              Rejected drifts · {rejected.length} · last 30 days
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
                  No drifts rejected in the last 30 days.
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
                        Drift (kind · target)
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
                        key={r.driftId}
                        data-testid={`catalog-drift-rejected-row-${r.driftId}`}
                      >
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 4,
                            }}
                          >
                            <DriftKindChip
                              kind={r.driftKind}
                              testIdSuffix={`rej-${r.driftId}`}
                            />
                            <code
                              className="wb-mono"
                              style={{ fontSize: 11 }}
                            >
                              {fmtTarget(r)}
                            </code>
                          </div>
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
