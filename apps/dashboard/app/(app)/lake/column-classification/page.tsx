/**
 * /lake/column-classification — L6 Sub-wave D (2026-06-06).
 *
 * Admin-only audit page for the L6 column-level governance
 * classification inference axis. The fifth lake-side compounding axis
 * (after L3 lineage, L7 quality, L4 schema-impact, L5 semantic-types)
 * and the SECOND cross-axis chain (after L4→L3) — the
 * ``semantic_type`` strategy reads L5's confirmed semantic types via
 * the ``ConfirmedSemanticTypeReader`` Protocol and maps each type to
 * a governance level (e.g. ``pii_ssn`` → ``regulated``).
 *
 * Sections (mirrors L3/L7/L4/L5 plus L5-dependency banner pattern
 * matching L4→L3):
 *
 *   1. Strategy status banner — three rows (semantic_type /
 *      naming_pattern / domain_default) via shared
 *      :class:`CapabilityBadges`. Honest postures per L6 design §5:
 *        * ``semantic_type``   — 4 honest postures keyed off the L5
 *          confirmed-type count probe: productive · L5-dependent /
 *          configured · awaiting-L5-types / configured · L5-disabled /
 *          disabled.
 *        * ``naming_pattern``  — productive when L6 on (regex over
 *          bare names). Note expands to surface the 4-pattern
 *          coverage list per Sub-wave C handoff concern #1.
 *        * ``domain_default``  — 3 postures: disabled / configured ·
 *          awaiting-domain-pack / productive · domain-pack-dependent
 *          (with the LedgerDomainDefaultReader rationale per Sub-wave
 *          C handoff concern #3).
 *
 *   2. L5-dependency note — explicit panel when L5 is enabled but has
 *      zero confirmed semantic types (mirrors L4's L3-dependency
 *      banner). Surfaced honestly so operators don't wonder why
 *      ``semantic_type`` is wired but quiet.
 *
 *   3. Pending Proposals — candidate classifications with
 *      Confirm/Reject actions for admins; read-only for everyone
 *      else. Group-by toggle (classification_level / table / strategy)
 *      per spec §5.
 *
 *   4. Confirmed Classifications — table view of approved
 *      classifications; expanding a row shows the strategy config +
 *      evidence + reasoning (including ``domain_id`` from the
 *      LedgerDomainDefaultReader when applicable — rendered
 *      accurately per Sub-wave C handoff concern #4, NOT labelled as
 *      table-specific).
 *
 *   5. Rejected Classifications (last 30 days) — collapsed by default
 *      for strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * #1 naming_pattern coverage surfaced verbatim in the banner.
 *   * #2 min_confidence env knob acknowledged but not-yet-wired (L6
 *      close-out tracker).
 *   * #3 domain_default rationale + 0.60 confidence explained.
 *   * #4 domain_id rendered accurately on the row detail panel.
 *   * Cross-axis trace linking — when ``upstreamSemanticTypeId`` is
 *      set on the row, the strategy cell renders a "view L5 semantic
 *      type →" link to ``/lake/semantic-types?type_id=<id>`` (second
 *      cross-axis dashboard nav in the lake stack; matches L4→L3
 *      pattern).
 *   * Re-trigger affordance warns about
 *      ``WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS`` dedup.
 *   * ``getCurrentPerson(companyId)`` threads the caller's identity
 *      for admin gating (no placeholders).
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import { ColumnClassificationProposalsTable } from "../../../../components/lake/ColumnClassificationProposalsTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getColumnClassificationStrategyStatus,
  getConfirmedColumnClassifications,
  getL5DependencyState,
  getProposedColumnClassifications,
  getRejectedColumnClassifications,
  getSchemaImpactCountByClassification,
  type ClassificationLevel,
  type ColumnClassificationFilter,
  type ColumnClassificationRow,
  type ColumnClassificationStrategyStatus,
} from "../../../../lib/column-classification";

/**
 * Per-page filter URL params. Honored by the page boundary + every
 * accessor call below.
 *
 * Two filter sources:
 *
 *   * ``upstream_semantic_type_id`` (2026-05-16 consumer-filter
 *     bundle) — R2 reverse arc from /lake/semantic-types.
 *   * ``classification_id`` (2026-05-16 producer-side deep-link
 *     bundle) — L4 row's "view L6 classification →" chain link
 *     deep-links into this page filtered to a single row.
 */
type ColumnClassificationSearchParams = {
  upstream_semantic_type_id?: string;
  classification_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseColumnClassificationFilter(
  searchParams:
    | ColumnClassificationSearchParams
    | Record<string, string | string[] | undefined>,
): ColumnClassificationFilter | undefined {
  const upstreamSemanticTypeId = firstParam(
    searchParams.upstream_semantic_type_id as
      | string
      | string[]
      | undefined,
  );
  const classificationId = firstParam(
    searchParams.classification_id as string | string[] | undefined,
  );
  if (!upstreamSemanticTypeId && !classificationId) return undefined;
  const out: ColumnClassificationFilter = {};
  if (upstreamSemanticTypeId) out.upstreamSemanticTypeId = upstreamSemanticTypeId;
  if (classificationId) out.classificationId = classificationId;
  return out;
}

function filterToChipMap(
  filter: ColumnClassificationFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return {
    upstream_semantic_type_id: filter.upstreamSemanticTypeId,
    classification_id: filter.classificationId,
  };
}

/** Export for tests. */
export const __test__ = {
  parseColumnClassificationFilter,
  filterToChipMap,
};
import {
  confirmColumnClassification,
  rejectColumnClassification,
} from "./actions";

export const metadata = {
  title: "WormBase · Lake · Column-classification audit",
};

export const dynamic = "force-dynamic";

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function fmtTarget(row: ColumnClassificationRow): string {
  return `${row.tableId} · ${row.column}`;
}

interface ChipColors {
  bg: string;
  fg: string;
  border: string;
  prefix?: string;
}

function levelChip(level: ClassificationLevel): ChipColors {
  switch (level) {
    case "public":
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
    case "internal":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-archive-blue-deep, #2c5f7c)",
        border: "var(--wb-color-archive-blue-deep, #2c5f7c)",
      };
    case "confidential":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
        border: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "pii":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        border: "var(--wb-color-alarm-red-deep, #9c2a2a)",
      };
    case "regulated":
      return {
        bg: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        fg: "var(--wb-color-paper, #f8f3e1)",
        border: "var(--wb-color-alarm-red-deep, #9c2a2a)",
        prefix: "\u{1F512} ",
      };
  }
}

function renderLevelChip(
  level: ClassificationLevel,
  testIdSuffix: string,
): JSX.Element {
  const c = levelChip(level);
  return (
    <span
      data-testid={`column-classification-level-chip-${testIdSuffix}`}
      data-level={level}
      data-regulated={level === "regulated" ? "true" : "false"}
      className="wb-mono"
      style={{
        display: "inline-block",
        padding: "2px 8px",
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.fg,
        fontSize: 10,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontWeight: 600,
      }}
    >
      {c.prefix ?? ""}
      {level}
    </span>
  );
}

export default async function LakeColumnClassificationPage({
  searchParams,
}: {
  searchParams?: ColumnClassificationSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. The
  // banner accessors (strategy status, L5 dependency probe,
  // reverse-arc count map) remain filter-blind.
  const filter = parseColumnClassificationFilter(searchParams ?? {});

  const [
    proposed,
    confirmed,
    rejected,
    strategyStatus,
    l5Dependency,
    impactCountsByClassification,
  ] = await Promise.all([
    getProposedColumnClassifications(companyId, { filter }),
    getConfirmedColumnClassifications(companyId, { filter }),
    getRejectedColumnClassifications(companyId, { days: 30, filter }),
    getColumnClassificationStrategyStatus(companyId),
    getL5DependencyState(companyId),
    // R5 L4↦L6 reverse-arc enrichment (Recipe Addendum #3):
    // honest empty map when L4 projection has no
    // classification-derived impacts.
    getSchemaImpactCountByClassification(companyId),
  ]);

  const totalClassifications =
    proposed.length + confirmed.length + rejected.length;

  // L5-dependency banner triggers when L5 is enabled (the master
  // switch is on) but there are no confirmed semantic types yet.
  // Honest panel — if L5 is disabled entirely, the strategy banner
  // above already says so via the ``semantic_type`` row.
  const showL5DependencyBanner =
    l5Dependency.l5Enabled && l5Dependency.confirmedSemanticTypeCount === 0;

  return (
    <PageBoundary
      surface="lake column-classification"
      traceQuery="?surface=lake.column_classification"
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
          Semantic layer · column-classification audit · admin
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
          Column-classification audit · {totalClassifications}{" "}
          {totalClassifications === 1 ? "proposal" : "proposals"}
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
          The L6 inference axis proposes a governance classification
          level from the strict 5-value enum (public / internal /
          confidential / pii / regulated) for each catalog column.
          Three strategies vote: ``semantic_type`` (cross-axis chain
          into L5 — maps confirmed types like ``pii_ssn`` →
          ``regulated``), ``naming_pattern`` (regex over bare column
          names), ``domain_default`` (per-domain pack fallback). The
          second cross-axis chain in the lake stack (after L4→L3).
          Admins confirm or reject; the projection folds each decision
          forward. Every confirmation and rejection writes a ledger
          entry — replay-stable, audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="column-classification-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/column-classification"
        labels={{
          upstream_semantic_type_id: "upstream semantic type",
          classification_id: "Classification",
        }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges. */}
      <section
        data-testid="column-classification-strategy-status-banner"
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
            L6 inference strategy status
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
            Which classification strategies can produce proposals in
            this tenant today. ``productive · L5-dependent`` = wired
            against L5&apos;s confirmed types;
            ``configured · awaiting-L5-types`` = strategy is correct
            but L5 has no confirmed types yet;
            ``configured · L5-disabled`` = strategy is correct but L5
            master switch is off;
            ``configured · awaiting-domain-pack`` =
            ``domain_default`` is wired but no domain pack registered;
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
          {strategyStatus.map((row: ColumnClassificationStrategyStatus) => (
            <li
              key={row.strategy}
              data-testid={`column-classification-strategy-row-${row.strategy}`}
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
                  id={`column-classification-${row.strategy}`}
                  status={row.badge}
                  statusNote={row.note}
                />
                {row.badgeLabelOverride ? (
                  <span
                    className="wb-mono"
                    data-testid={`column-classification-strategy-override-${row.strategy}`}
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

      {/* L5-DEPENDENCY BANNER — surfaced when L5 is enabled but has zero
          confirmed types, so operators understand why semantic_type is
          wired but quiet. Mirrors L4's L3-dependency banner pattern. */}
      {showL5DependencyBanner ? (
        <section
          data-testid="column-classification-l5-dependency-banner"
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
            No L5 confirmed semantic types available — L6 awaits L5
            confirmations. The ``semantic_type`` strategy reads
            L5&apos;s confirmed semantic types and maps each to a
            governance classification (e.g. ``pii_ssn`` →
            ``regulated``, ``email`` → ``internal``). Confirm at least
            one type in{" "}
            <a
              href="/lake/semantic-types"
              data-testid="column-classification-l5-dependency-link"
              className="wb-mono"
              style={{
                color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
                textDecoration: "underline",
              }}
            >
              /lake/semantic-types
            </a>{" "}
            and the strategy graduates to productive automatically.
            ``naming_pattern`` and ``domain_default`` do not depend on
            L5 and produce classifications independently when L6 is
            enabled.
          </p>
        </section>
      ) : null}

      {totalClassifications === 0 ? (
        <EmptyState
          testId="lake-column-classification-empty"
          eyebrow="no classifications yet"
          title="No column classifications proposed yet."
          description={
            "The L6 inference axis fires on external_catalog_imported " +
            "cascades to classify each column at one of 5 governance " +
            "levels. Set " +
            "WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true " +
            "and re-import a catalog — proposals land within the next " +
            "compounding window. naming_pattern proposals appear " +
            "immediately on columns matching the regex coverage list; " +
            "semantic_type graduates once at least one L5 type is " +
            "confirmed; domain_default graduates once a domain pack " +
            "is selected."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <ColumnClassificationProposalsTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmColumnClassification}
              rejectAction={rejectColumnClassification}
              impactCounts={impactCountsByClassification}
            />
          ) : (
            <section
              data-testid="column-classification-proposals-empty"
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
                No column-classification proposals awaiting review. New
                proposals appear as the L6 inference axis fires on
                incoming catalog snapshots.
              </p>
            </section>
          )}

          {/* CONFIRMED CLASSIFICATIONS */}
          <section
            data-testid="column-classification-confirmed-section"
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
                Confirmed classifications · {confirmed.length}
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
                Approved column classifications, with the strategy that
                proposed them + the confidence + the approving admin.
                Expand a row for the strategy-specific evidence dict +
                reasoning + the upstream L5 semantic type (when the
                ``semantic_type`` strategy fired). When the
                ``domain_default`` strategy fired, the evidence carries
                the picked ``domain_id`` (the alphabetically-first
                registered domain — not a per-table mapping).
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="column-classification-confirmed-empty"
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
                No confirmed classifications yet. Approve a pending
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
                      Classification
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
                      key={r.classificationId}
                      data-testid={`column-classification-confirmed-row-${r.classificationId}`}
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
                        {renderLevelChip(
                          r.classificationLevel,
                          `confirmed-${r.classificationId}`,
                        )}
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
                              data-testid={`column-classification-confirmed-l5-link-${r.classificationId}`}
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

          {/* REJECTED CLASSIFICATIONS (collapsed by default) */}
          <details
            data-testid="column-classification-rejected-section"
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
              Rejected classifications · {rejected.length} · last 30 days
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
                  No classifications rejected in the last 30 days.
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
                        Classification
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
                        key={r.classificationId}
                        data-testid={`column-classification-rejected-row-${r.classificationId}`}
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
                          {renderLevelChip(
                            r.classificationLevel,
                            `rejected-${r.classificationId}`,
                          )}
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
