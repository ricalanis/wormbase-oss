/**
 * /lake/semantic-types — L5 Sub-wave D (2026-06-05).
 *
 * Admin-only audit page for the L5 sample-data fingerprinting
 * inference axis. The fourth lake-side compounding axis (after L3
 * lineage, L7 quality, L4 schema-impact) and the first axis built
 * from day one on the shared ``LakeLoopComposite[ProposedSemanticType]``
 * abstraction (Sub-wave B).
 *
 * Sections (mirrors /lake/lineage + /lake/quality + /lake/schema-impact):
 *
 *   1. Strategy status banner — three rows (column_name / value_pattern
 *      / distribution) via shared :class:`CapabilityBadges`. Honest
 *      labels per L5 design §4:
 *        * ``column_name``   — productive (regex over bare names)
 *        * ``value_pattern`` — configured · empty-upstream (Wave 1
 *          sampler not yet emitting) / disabled when env knob OFF
 *        * ``distribution``  — configured · empty-upstream (per-column
 *          historical stats not yet emitting) / disabled when env knob
 *          OFF
 *
 *   2. Pending Proposals — candidate semantic types with Confirm/Reject
 *      actions for admins; read-only for everyone else. Group-by
 *      toggle (table / semantic_type / strategy).
 *
 *   3. Confirmed Semantic Types — table view of approved types;
 *      expanding a row shows the strategy config + evidence + reasoning.
 *
 *   4. Rejected Semantic Types (last 30 days) — collapsed by default
 *      for strategy-tuning audit.
 *
 * Sub-wave C handoff concerns honored:
 *
 *   * 19-value ``semantic_type`` enum pinned via ``SemanticTypeValue``
 *     union in lib/semantic-types.ts.
 *   * 5-value L5-specific reject reason enum (``false_positive`` /
 *     ``low_value`` / ``wrong_type`` / ``out_of_scope`` / ``other``);
 *     ``wrong_type`` is L5-distinct (differs from L4's
 *     ``already_handled`` and L7's ``wrong_threshold``).
 *   * Server actions thread ``getCurrentPerson(companyId)`` for admin
 *     Person UUID — never placeholders.
 *   * Empty-state copy points operators at the env knob to enable L5.
 *   * Re-trigger affordance warns about
 *     ``WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS`` dedup.
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import { SemanticTypeProposalsTable } from "../../../../components/lake/SemanticTypeProposalsTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getClassificationCountBySemanticType,
  getConfirmedSemanticTypes,
  getEntityStitchCountBySemanticType,
  getProposedSemanticTypes,
  getQualityCheckCountBySemanticType,
  getRejectedSemanticTypes,
  getSchemaImpactCountBySemanticType,
  getSemanticTypeStrategyStatus,
  type SemanticTypeFilter,
  type SemanticTypeRow,
  type SemanticTypeStrategyStatus,
} from "../../../../lib/semantic-types";
import { confirmSemanticType, rejectSemanticType } from "./actions";

export const metadata = { title: "WormBase · Lake · Semantic types audit" };

export const dynamic = "force-dynamic";

/**
 * Per-page filter URL param (2026-05-16 — producer-side deep-link
 * bundle). Honored by the page boundary + every projection accessor
 * below.
 *
 * Filter source: any consumer-page row link writing
 * ``?type_id=<id>`` to deep-link a single L5 semantic type (e.g.
 * L4/L6/L7/L8 rows that carry an upstream semantic-type id).
 */
type SemanticTypeSearchParams = {
  type_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseSemanticTypeFilter(
  searchParams:
    | SemanticTypeSearchParams
    | Record<string, string | string[] | undefined>,
): SemanticTypeFilter | undefined {
  const typeId = firstParam(
    searchParams.type_id as string | string[] | undefined,
  );
  if (!typeId) return undefined;
  return { typeId };
}

function filterToChipMap(
  filter: SemanticTypeFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return { type_id: filter.typeId };
}

/** Export for tests. */
export const __test__ = {
  parseSemanticTypeFilter,
  filterToChipMap,
};

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtTarget(row: SemanticTypeRow): string {
  return `${row.tableId} · ${row.column}`;
}

export default async function LakeSemanticTypesPage({
  searchParams,
}: {
  searchParams?: SemanticTypeSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the projection accessors. The banner +
  // reverse-arc count maps remain filter-blind.
  const filter = parseSemanticTypeFilter(searchParams ?? {});

  const [
    proposed,
    confirmed,
    rejected,
    strategyStatus,
    classificationCountsByType,
    entityStitchCountsByType,
    qualityCountsByType,
    impactCountsByType,
  ] = await Promise.all([
    getProposedSemanticTypes(companyId, { filter }),
    getConfirmedSemanticTypes(companyId, { filter }),
    getRejectedSemanticTypes(companyId, { days: 30, filter }),
    getSemanticTypeStrategyStatus(companyId),
    // Reverse-arc downstream-counts cluster (Recipe Addendum #3):
    // R2 L6↦L5 / R3 L8↦L5 / R4 L7↦L5 / R6 L4↦L5. Each accessor
    // returns ``{}`` when its projection is empty — the cluster
    // renders nothing on those rows (honest empty).
    getClassificationCountBySemanticType(companyId),
    getEntityStitchCountBySemanticType(companyId),
    getQualityCheckCountBySemanticType(companyId),
    getSchemaImpactCountBySemanticType(companyId),
  ]);

  const totalTypes = proposed.length + confirmed.length + rejected.length;

  return (
    <PageBoundary
      surface="lake semantic-types"
      traceQuery="?surface=lake.semantic_types"
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
          Semantic layer · semantic-types audit · admin
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
          Semantic types audit · {totalTypes}{" "}
          {totalTypes === 1 ? "proposal" : "proposals"}
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
          The L5 inference axis proposes a semantic type from a strict
          19-value enum (identity / temporal / identifiers / geo-locale
          / PII / metric / catch-all) for each catalog column it
          fingerprints. Three strategies vote: ``column_name`` (regex
          over bare names), ``value_pattern`` (regex over sampled
          values), ``distribution`` (per-column historical stats).
          Admins confirm or reject; the projection folds each decision
          forward. Every confirmation and rejection writes a ledger
          entry — replay-stable, audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="semantic-types-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/semantic-types"
        labels={{ type_id: "Semantic type" }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges per
          handoff concern. Rendered first so the operator knows what the
          productive surface is before scanning proposals. */}
      <section
        data-testid="semantic-types-strategy-status-banner"
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
            L5 inference strategy status
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
            Which fingerprinting strategies can produce semantic-type
            proposals in this tenant today. ``productive`` = wired and
            actively emitting; ``configured · empty-upstream`` =
            strategy is correct but its upstream (sampler / per-column
            stats) emits nothing yet; ``disabled`` = env knob off.
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
          {strategyStatus.map((row: SemanticTypeStrategyStatus) => (
            <li
              key={row.strategy}
              data-testid={`semantic-types-strategy-row-${row.strategy}`}
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
                  id={`semantic-types-${row.strategy}`}
                  status={row.badge}
                  statusNote={row.note}
                />
                {row.badgeLabelOverride ? (
                  <span
                    className="wb-mono"
                    data-testid={`semantic-types-strategy-override-${row.strategy}`}
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

      {totalTypes === 0 ? (
        <EmptyState
          testId="lake-semantic-types-empty"
          eyebrow="no semantic types yet"
          title="No semantic-type proposals yet."
          description={
            "The L5 inference axis fires on external_catalog_imported " +
            "cascades to fingerprint each column. Set " +
            "WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true and re-import " +
            "a catalog — proposals land within the next compounding " +
            "window. column_name proposals appear immediately on " +
            "well-known column names (email / created_at / etc.); " +
            "value_pattern + distribution graduate once their upstream " +
            "sampler / stats begin emitting."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <SemanticTypeProposalsTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmSemanticType}
              rejectAction={rejectSemanticType}
              classificationCounts={classificationCountsByType}
              entityStitchCounts={entityStitchCountsByType}
              qualityCounts={qualityCountsByType}
              impactCounts={impactCountsByType}
            />
          ) : (
            <section
              data-testid="semantic-types-proposals-empty"
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
                No semantic-type proposals awaiting review. New
                proposals appear as the L5 inference axis fires on
                incoming catalog snapshots.
              </p>
            </section>
          )}

          {/* CONFIRMED SEMANTIC TYPES */}
          <section
            data-testid="semantic-types-confirmed-section"
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
                Confirmed semantic types · {confirmed.length}
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
                Approved semantic types, with the strategy that proposed
                them + the confidence + the approving admin. Expand a
                row for the strategy-specific evidence dict + reasoning
                (e.g. matched regex pattern; sample values when the
                value_pattern strategy graduates).
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="semantic-types-confirmed-empty"
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
                No confirmed semantic types yet. Approve a pending
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
                      Table · column
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Semantic type
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
                      key={r.typeId}
                      data-testid={`semantic-types-confirmed-row-${r.typeId}`}
                    >
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
                          {r.semanticType}
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

          {/* REJECTED SEMANTIC TYPES (collapsed by default) */}
          <details
            data-testid="semantic-types-rejected-section"
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
              Rejected semantic types · {rejected.length} · last 30 days
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
                  No semantic types rejected in the last 30 days.
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
                        Semantic type
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
                        key={r.typeId}
                        data-testid={`semantic-types-rejected-row-${r.typeId}`}
                      >
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
                            {r.semanticType}
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
