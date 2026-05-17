/**
 * /lake/lineage — L3 Sub-wave D (2026-05-29).
 *
 * Admin-only audit page for the L3 inference axis. Three sections:
 *
 *   1. Pending Proposals — table of candidate lineage edges proposed
 *      by the Sub-wave B inference service. Confirm/Reject actions for
 *      admins; read-only for everyone else.
 *
 *   2. Confirmed Edges — basic SVG graph view of approved edges. Click
 *      an edge to expand its evidence panel.
 *
 *   3. Rejected Edges (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C concerns surfaced honestly:
 *
 *   * The strategy status banner (top of page) labels which strategies
 *     are productive today vs configured-but-stubbed.
 *   * Empty-state copy points operators at the env knob to enable L3.
 *   * Re-trigger affordance, if any, warns about
 *     ``WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS`` dedup.
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { LineageGraphView } from "../../../../components/lake/LineageGraphView";
import { LineageProposalsTable } from "../../../../components/lake/LineageProposalsTable";
import { StrategyStatusBanner } from "../../../../components/lake/StrategyStatusBanner";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getConfirmedLineageEdges,
  getLineageStrategyStatus,
  getProposedLineageEdges,
  getRejectedLineageEdges,
  getSchemaImpactCountByLineageEdge,
  type LineageEdgeRow,
  type LineageFilter,
} from "../../../../lib/lineage";
import { confirmLineageEdge, rejectLineageEdge } from "./actions";

export const metadata = { title: "WormBase · Lake · Lineage audit" };

export const dynamic = "force-dynamic";

/**
 * Per-page filter URL param (2026-05-16 — producer-side deep-link
 * bundle). Honored by the page boundary + every projection accessor
 * below.
 *
 * Filter source: L4 row's "view L3 edge →" chain link writes
 * ``?edge_id=<id>`` when the impact carries ``upstream_lineage_edge_id``.
 */
type LineageSearchParams = {
  edge_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseLineageFilter(
  searchParams:
    | LineageSearchParams
    | Record<string, string | string[] | undefined>,
): LineageFilter | undefined {
  const edgeId = firstParam(
    searchParams.edge_id as string | string[] | undefined,
  );
  if (!edgeId) return undefined;
  return { edgeId };
}

function filterToChipMap(
  filter: LineageFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return { edge_id: filter.edgeId };
}

/** Export for tests. */
export const __test__ = {
  parseLineageFilter,
  filterToChipMap,
};

function fmtSrcTgt(edge: LineageEdgeRow): string {
  const src = edge.srcColumn
    ? `${edge.srcTableId} · ${edge.srcColumn}`
    : edge.srcTableId;
  const tgt = edge.tgtColumn
    ? `${edge.tgtTableId} · ${edge.tgtColumn}`
    : edge.tgtTableId;
  return `${src}  →  ${tgt}`;
}

export default async function LakeLineagePage({
  searchParams,
}: {
  searchParams?: LineageSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the projection accessors. The banner +
  // reverse-arc count map remain filter-blind.
  const filter = parseLineageFilter(searchParams ?? {});

  const [
    proposed,
    confirmed,
    rejected,
    strategyStatus,
    impactCountsByEdge,
  ] = await Promise.all([
    getProposedLineageEdges(companyId, { filter }),
    getConfirmedLineageEdges(companyId, { filter }),
    getRejectedLineageEdges(companyId, { days: 30, filter }),
    getLineageStrategyStatus(companyId),
    getSchemaImpactCountByLineageEdge(companyId),
  ]);

  const totalEdges = proposed.length + confirmed.length + rejected.length;

  return (
    <PageBoundary surface="lake lineage" traceQuery="?surface=lake.lineage">
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
          Semantic layer · lineage audit · admin
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
          Lineage audit · {totalEdges}{" "}
          {totalEdges === 1 ? "edge" : "edges"}
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
          The L3 inference axis proposes candidate lineage edges from the
          catalog mirror. Admins confirm or reject; the projection folds
          each decision forward. Every confirmation and rejection writes
          a ledger entry — replay-stable, audit-grade.
        </p>
      </header>

      <ActiveFilterChips
        testId="lineage-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/lineage"
        labels={{ edge_id: "Lineage edge" }}
      />

      <StrategyStatusBanner rows={strategyStatus} />

      {totalEdges === 0 ? (
        <EmptyState
          testId="lake-lineage-empty"
          eyebrow="no edges yet"
          title="No lineage edges proposed yet."
          description={
            "The L3 inference axis fires on source_connected + " +
            "external_catalog_imported cascades. Set " +
            "WORMBASE_LINEAGE_DISCOVERY_ENABLED=true and connect a dbt " +
            "or Snowflake source — proposals land within the next " +
            "compounding window."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <LineageProposalsTable
              rows={proposed}
              isAdmin={isAdmin}
              confirmAction={confirmLineageEdge}
              rejectAction={rejectLineageEdge}
              impactCounts={impactCountsByEdge}
            />
          ) : (
            <section
              data-testid="lineage-proposals-empty"
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
                No candidate edges awaiting review. New proposals appear
                as the inference axis fires on incoming catalog
                snapshots.
              </p>
            </section>
          )}

          {/* CONFIRMED EDGES */}
          <section
            data-testid="lineage-confirmed-section"
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
                Confirmed edges · {confirmed.length}
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
                Approved lineage edges, rendered as a directed graph.
                Click an edge to see its inference evidence + the
                approving admin.
              </p>
            </header>
            {confirmed.length === 0 ? (
              <div
                data-testid="lineage-confirmed-empty"
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
                No confirmed edges yet. Approve a pending proposal to
                see the graph fill in.
              </div>
            ) : (
              <LineageGraphView rows={confirmed} />
            )}
          </section>

          {/* REJECTED EDGES (collapsed by default) */}
          <details
            data-testid="lineage-rejected-section"
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
              Rejected edges · {rejected.length} · last 30 days
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
                  No edges rejected in the last 30 days.
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
                        Edge
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
                        key={r.edgeId}
                        data-testid={`lineage-rejected-row-${r.edgeId}`}
                      >
                        <td
                          style={{
                            padding: "6px 8px",
                            fontFamily: "var(--wb-font-serif)",
                          }}
                        >
                          <code className="wb-mono" style={{ fontSize: 11 }}>
                            {fmtSrcTgt(r)}
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
                          {(r.confidence * 100).toFixed(0)}%
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
