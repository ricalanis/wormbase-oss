/**
 * /lake/quality — L7 Sub-wave D (2026-05-30).
 *
 * Admin-only audit page for the L7 inference axis. Three sections:
 *
 *   1. Pending Proposals — table of candidate quality checks proposed
 *      by the Sub-wave B inference service. Confirm/Reject actions for
 *      admins; read-only for everyone else. Group-by toggle (table /
 *      kind / strategy) per spec §4.1.
 *
 *   2. Confirmed Checks — table view of approved checks; expanding a
 *      row shows the strategy config + evidence + reasoning.
 *
 *   3. Rejected Checks (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * The strategy status banner (top of page) labels which strategies
 *     are productive today vs configured-but-empty-upstream vs stubbed.
 *   * ``dbt_tests`` shows ``configured · empty-upstream`` because Wave
 *     1's catalog-manifest mirror does not yet emit dbt tests; the
 *     strategy is wired correctly but its upstream is empty.
 *   * ``historical_stats`` shows ``configured · stubbed`` when enabled.
 *   * Empty-state copy points operators at the env knob to enable L7.
 *   * Re-trigger affordance warns about
 *     ``WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS`` dedup.
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import { QualityProposalsTable } from "../../../../components/lake/QualityProposalsTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getConfirmedQualityChecks,
  getProposedQualityChecks,
  getQualityStrategyStatus,
  getRejectedQualityChecks,
  type QualityCheckFilter,
  type QualityCheckRow,
  type QualityStrategyStatus,
} from "../../../../lib/quality";
import { confirmQualityCheck, rejectQualityCheck } from "./actions";

/**
 * Per-page filter URL param (2026-05-16). Honored by the page
 * boundary + every accessor call below.
 *
 * Filter source: R4 reverse arc (from /lake/semantic-types).
 *
 * Route note: the dashboard page lives at /lake/quality but the
 * filter-source spec refers to /lake/quality-checks. The reverse
 * arcs point at the page route, which is /lake/quality — the
 * clear-filter link reflects the route, not the spec label.
 */
type QualityCheckSearchParams = {
  upstream_semantic_type_id?: string;
  /** Producer-side primary-key deep-link (2026-05-16 — Lake-Side
   *  Overview activity-stream drill-in). Narrows to the single quality
   *  check identified by ``check_id``. */
  check_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseQualityCheckFilter(
  searchParams:
    | QualityCheckSearchParams
    | Record<string, string | string[] | undefined>,
): QualityCheckFilter | undefined {
  const upstreamSemanticTypeId = firstParam(
    searchParams.upstream_semantic_type_id as
      | string
      | string[]
      | undefined,
  );
  const checkId = firstParam(
    searchParams.check_id as string | string[] | undefined,
  );
  const cleaned: QualityCheckFilter = {};
  let any = false;
  if (upstreamSemanticTypeId) {
    cleaned.upstreamSemanticTypeId = upstreamSemanticTypeId;
    any = true;
  }
  if (checkId) {
    cleaned.checkId = checkId;
    any = true;
  }
  return any ? cleaned : undefined;
}

function filterToChipMap(
  filter: QualityCheckFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return {
    upstream_semantic_type_id: filter.upstreamSemanticTypeId,
    check_id: filter.checkId,
  };
}

/** Export for tests. */
export const __test__ = {
  parseQualityCheckFilter,
  filterToChipMap,
};

export const metadata = { title: "WormBase · Lake · Quality audit" };

export const dynamic = "force-dynamic";

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtTableColumn(row: QualityCheckRow): string {
  if (row.column) return `${row.tableId} · ${row.column}`;
  return row.tableId;
}

export default async function LakeQualityPage({
  searchParams,
}: {
  searchParams?: QualityCheckSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. The
  // strategy status banner remains filter-blind — it summarises
  // tenant-scoped global state, not per-row narrowing.
  const filter = parseQualityCheckFilter(searchParams ?? {});

  const [proposed, confirmed, rejected, strategyStatus] = await Promise.all([
    getProposedQualityChecks(companyId, { filter }),
    getConfirmedQualityChecks(companyId, { filter }),
    getRejectedQualityChecks(companyId, { days: 30, filter }),
    getQualityStrategyStatus(companyId),
  ]);

  const totalChecks = proposed.length + confirmed.length + rejected.length;

  return (
    <PageBoundary surface="lake quality" traceQuery="?surface=lake.quality">
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
          Semantic layer · quality audit · admin
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
          Quality audit · {totalChecks}{" "}
          {totalChecks === 1 ? "check" : "checks"}
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
          The L7 inference axis proposes candidate data-quality checks
          (unique / not_null / freshness / enum / row-count-range) from
          the catalog mirror + dbt manifests + historical statistics.
          Admins confirm or reject; the projection folds each decision
          forward. Every confirmation and rejection writes a ledger
          entry — replay-stable, audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="quality-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/quality"
        labels={{
          upstream_semantic_type_id: "upstream semantic type",
          check_id: "Quality check",
        }}
      />

      {/* STRATEGY STATUS BANNER — uses shared CapabilityBadges component
          to surface each strategy's productive / empty-upstream /
          stubbed / disabled posture honestly. */}
      <section
        data-testid="quality-strategy-status-banner"
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
            L7 inference strategy status
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
            Which inference strategies can produce quality checks in
            this tenant today. ``productive`` = wired against real data;
            ``configured · empty-upstream`` = strategy is correct but
            its upstream emits nothing yet (Wave 1 mirror gap);
            ``configured · stubbed`` = env knob on but the underlying
            implementation is a no-op; ``disabled`` = env knob off.
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
          {strategyStatus.map((row: QualityStrategyStatus) => (
            <li
              key={row.strategy}
              data-testid={`quality-strategy-row-${row.strategy}`}
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
                  id={`quality-${row.strategy}`}
                  status={row.badge}
                  statusNote={row.note}
                />
                {row.badgeLabelOverride ? (
                  <span
                    className="wb-mono"
                    data-testid={`quality-strategy-override-${row.strategy}`}
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

      {totalChecks === 0 ? (
        <EmptyState
          testId="lake-quality-empty"
          eyebrow="no checks yet"
          title="No quality checks proposed yet."
          description={
            "The L7 inference axis fires on source_connected + " +
            "external_catalog_imported cascades. Set " +
            "WORMBASE_QUALITY_DISCOVERY_ENABLED=true and connect a " +
            "dbt or Snowflake source — proposals land within the " +
            "next compounding window."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <QualityProposalsTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmQualityCheck}
              rejectAction={rejectQualityCheck}
            />
          ) : (
            <section
              data-testid="quality-proposals-empty"
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
                No candidate checks awaiting review. New proposals
                appear as the inference axis fires on incoming catalog
                snapshots or dbt manifest imports.
              </p>
            </section>
          )}

          {/* CONFIRMED CHECKS */}
          <section
            data-testid="quality-confirmed-section"
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
                Confirmed checks · {confirmed.length}
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
                Approved quality checks, with the strategy that proposed
                them + the confidence + the approving admin. Expand a
                row for the strategy-specific config + evidence +
                reasoning.
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="quality-confirmed-empty"
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
                No confirmed checks yet. Approve a pending proposal to
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
                      Table · column
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Kind
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
                      key={r.checkId}
                      data-testid={`quality-confirmed-row-${r.checkId}`}
                    >
                      <td
                        style={{
                          padding: "6px 12px",
                          fontFamily: "var(--wb-font-serif)",
                        }}
                      >
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {fmtTableColumn(r)}
                        </code>
                      </td>
                      <td style={{ padding: "6px 12px" }}>
                        <code className="wb-mono" style={{ fontSize: 11 }}>
                          {r.checkKind}
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
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* REJECTED CHECKS (collapsed by default) */}
          <details
            data-testid="quality-rejected-section"
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
              Rejected checks · {rejected.length} · last 30 days
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
                  No checks rejected in the last 30 days.
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
                        Table · column
                      </th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>
                        Kind
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
                        key={r.checkId}
                        data-testid={`quality-rejected-row-${r.checkId}`}
                      >
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {fmtTableColumn(r)}
                          </code>
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {r.checkKind}
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
