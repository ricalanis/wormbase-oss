/**
 * /lake/source-candidates — L1 Sub-wave D (2026-06-08).
 *
 * Admin-only audit page for the L1 source-candidate triage axis.
 * The seventh lake-side compounding axis (after L3 lineage, L7
 * quality, L4 schema-impact, L5 semantic-types, L6 column-
 * classification, L8 entity-stitch). Unlike L4→L3, L6→L5, L8→L5, L1
 * does NOT add a peer-L-axis cross-axis chain — its three strategies
 * (kpi_gap / channel_mention / complementarity) read lightweight
 * **platform projections** (``projection_kpi_nodes``,
 * ``projection_conversations``, ``projection_sources``) through
 * scoped Reader Protocols, not other axes' confirmed outputs. The
 * cross-axis-chain count stays at 3 per spec §4.6.
 *
 * There IS a sui-generis "→ source pipeline" downstream link on
 * promoted candidates — the promote endpoint dual-writes a downstream
 * ``source_proposed``, and the resulting source id is threaded back
 * into the promote entry's ``downstream_source_proposed_id``. Per
 * Sub-wave C handoff concern #1 (dual-write atomicity), the surface
 * renders both the linked-success state AND the NULL "investigate"
 * state honestly — no synthesis.
 *
 * Sections (mirrors L3/L7/L4/L5/L6/L8):
 *
 *   1. Strategy status banner — three rows (kpi_gap /
 *      channel_mention / complementarity) via shared
 *      :class:`CapabilityBadges`. Honest postures per spec §4.7 +
 *      Sub-wave B/C handoff notes — see
 *      :func:`getSourceCandidateStrategyStatus` for the full matrix.
 *
 *   2. Pending Proposals — candidate triage with Promote/Reject
 *      actions for admins; read-only for everyone else. Group-by
 *      toggle (strategy / proposed_kind). High-density advisory above
 *      the table when rows > 200 (mirrors L8's discipline).
 *
 *   3. Promoted Candidates — promoted rows; expanding a row surfaces
 *      strategy config + evidence + the downstream-link affordance
 *      (or the "investigate" advisory when the dual-write failed).
 *
 *   4. Rejected Candidates (last 30 days) — collapsed by default for
 *      strategy-tuning audit.
 *
 * Sub-wave C handoff concerns surfaced honestly:
 *
 *   * #1 Dual-write atomicity — promoted rows render the downstream-
 *     link affordance OR the "investigate" advisory when
 *     downstream_source_proposed_id is NULL.
 *   * #2 ``KpiNodeRecord.domain_id = None`` (Wave 1) — domain_id_hint
 *     surfaces honestly (NULL → ``—`` cell, not synthesized).
 *   * #3 ``SilverConversationRecord.domain_id = None`` (Wave 1) —
 *     same honest-NULL treatment in the row + banner note.
 *   * #4 ``_proposed_kind_to_source_kind`` heuristic — connector
 *     resolution is downstream's job. ProposedKindChip renders the
 *     ``proposed_kind`` verbatim from projection; unknown kinds (and
 *     ``mcp:*`` namespace) fall back to muted slate.
 *   * #5 Table name is ``projection_conversations`` (NOT
 *     ``projection_silver_conversations``).
 *   * #6 Channel-mention 24h × 1000-row cap surfaced in the banner
 *     note.
 *   * #7 No reactivity-ordering integration test in scope for this
 *     sub-wave.
 *   * ``getCurrentPerson(companyId)`` threads the caller's identity
 *     for admin gating (no placeholders).
 */
import { ActiveFilterChips } from "../../../../components/lake/ActiveFilterChips";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { ProposedKindChip } from "../../../../components/lake/ProposedKindChip";
import { SourceCandidateStrategyBanner } from "../../../../components/lake/SourceCandidateStrategyBanner";
import { SourceCandidatesTable } from "../../../../components/lake/SourceCandidatesTable";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import {
  getProposedSourceCandidates,
  getPromotedSourceCandidates,
  getRejectedSourceCandidates,
  getSourceCandidateStrategyStatus,
  type SourceCandidateFilter,
} from "../../../../lib/source-candidates";
import { promoteSourceCandidate, rejectSourceCandidate } from "./actions";

/**
 * Per-page filter URL param (2026-05-16 — Lake-Side Overview
 * activity-stream drill-in coverage). Honored by the page boundary +
 * every projection accessor below.
 *
 * Filter source: Lake-Side Overview activity stream's drill-in for L1
 * rows writes ``?candidate_id=<id>`` (mirrors the L2/L3/L5/L6 drill-in
 * URLs shipped by ``bdee480``).
 */
type SourceCandidatesSearchParams = {
  candidate_id?: string;
};

function firstParam(
  v: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

function parseSourceCandidatesFilter(
  searchParams:
    | SourceCandidatesSearchParams
    | Record<string, string | string[] | undefined>,
): SourceCandidateFilter | undefined {
  const candidateId = firstParam(
    searchParams.candidate_id as string | string[] | undefined,
  );
  if (!candidateId) return undefined;
  return { candidateId };
}

function filterToChipMap(
  filter: SourceCandidateFilter | undefined,
): Record<string, string | undefined> {
  if (!filter) return {};
  return { candidate_id: filter.candidateId };
}

/** Export for tests. */
export const __test__ = {
  parseSourceCandidatesFilter,
  filterToChipMap,
};

export const metadata = {
  title: "WormBase · Lake · Source-candidate triage",
};

export const dynamic = "force-dynamic";

function fmtConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

export default async function LakeSourceCandidatesPage({
  searchParams,
}: {
  searchParams?: SourceCandidatesSearchParams;
} = {}): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  const isAdmin =
    me?.tenancyRole === "admin" || me?.tenancyRole === "installer";

  // Parse + thread filter into the three projection accessors. The
  // strategy status banner remains filter-blind — it summarises tenant-
  // scoped global state, not per-row narrowing.
  const filter = parseSourceCandidatesFilter(searchParams ?? {});

  const [proposed, promoted, rejected, strategyStatus] = await Promise.all([
    getProposedSourceCandidates(companyId, { filter }),
    getPromotedSourceCandidates(companyId, { filter }),
    getRejectedSourceCandidates(companyId, { days: 30, filter }),
    getSourceCandidateStrategyStatus(companyId),
  ]);

  const totalCandidates = proposed.length + promoted.length + rejected.length;

  return (
    <PageBoundary
      surface="lake source-candidates"
      traceQuery="?surface=lake.source_candidates"
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
          Semantic layer · source-candidate triage · admin
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
          Source-candidate triage · {totalCandidates}{" "}
          {totalCandidates === 1 ? "candidate" : "candidates"}
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
          The L1 inference axis proposes data-source candidates from
          three lightweight platform readers: ``kpi_gap`` (KPI nodes
          without an upstream source), ``channel_mention`` (24h × 1000-
          row scan of silver-conversation messages against a 30-pattern
          regex bank), and ``complementarity`` (portfolio-gap
          heuristics over connected sources). Each candidate carries a
          connector-registry kind + a free-form identifier hint;
          admins promote (dual-write — emits
          ``source_candidate_promoted`` AND triggers downstream
          ``source_proposed``) or reject with a categorical reason.
          Every decision writes a ledger entry — replay-stable, audit-
          grade. L1 does NOT add a peer-L-axis cross-axis chain
          (count stays at 3 — its strategies read lightweight platform
          projections, not other axes&apos; confirmed outputs).
        </p>
      </header>

      <ActiveFilterChips
        testId="source-candidates-active-filters"
        filter={filterToChipMap(filter)}
        clearHref="/lake/source-candidates"
        labels={{ candidate_id: "Source candidate" }}
      />

      {/* STRATEGY STATUS BANNER — reuses shared CapabilityBadges. */}
      <SourceCandidateStrategyBanner rows={strategyStatus} />

      {totalCandidates === 0 ? (
        <EmptyState
          testId="lake-source-candidates-empty"
          eyebrow="no candidates yet"
          title="No source candidates proposed yet."
          description={
            "The L1 inference axis fires on platform-projection " +
            "changes (KPI tree growth, silver-conversation cascade, " +
            "new sources) and proposes connector-registry candidates " +
            "for admin triage. Set " +
            "WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true plus the " +
            "per-strategy sub-knobs (KPI_GAP / CHANNEL_MENTION / " +
            "COMPLEMENTARITY) and proposals land as the upstream lake " +
            "populates: kpi_gap once the KPI tree has nodes; " +
            "channel_mention once silver-conversation messages flow; " +
            "complementarity once at least one source is connected."
          }
          cta={{ label: "Connect a source", href: "/sources/new" }}
          secondaryCta={{ label: "See raw activity", href: "/activity" }}
        />
      ) : (
        <>
          {/* PENDING PROPOSALS */}
          {proposed.length > 0 ? (
            <SourceCandidatesTable
              rows={proposed}
              isAdmin={isAdmin}
              promoteAction={promoteSourceCandidate}
              rejectAction={rejectSourceCandidate}
            />
          ) : (
            <section
              data-testid="source-candidate-proposals-empty"
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
                No source-candidate proposals awaiting triage. New
                candidates appear as the L1 inference axis fires on
                upstream platform-projection changes.
              </p>
            </section>
          )}

          {/* PROMOTED CANDIDATES */}
          <section
            data-testid="source-candidate-promoted-section"
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
                Promoted candidates · {promoted.length}
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
                Approved source candidates, with the proposing
                strategy, confidence, approving admin, and (when the
                dual-write succeeded) a downstream link to the
                ``source_proposed`` entry it triggered. When the
                ``downstream_source_proposed_id`` is NULL the row
                surfaces an honest "investigate" advisory — the
                promote audit entry landed but the downstream pipeline
                did not fire (Sub-wave C handoff concern #1).
              </p>
            </header>
            {promoted.length === 0 ? (
              <div
                data-testid="source-candidate-promoted-empty"
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
                No candidates promoted yet. Approve a pending proposal
                to see the audit table fill in.
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
                      Proposed (kind · identifier)
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "right" }}>
                      Conf.
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Strategy
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Downstream
                    </th>
                    <th style={{ padding: "6px 12px", textAlign: "left" }}>
                      Promoted at
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {promoted.map((r) => (
                    <tr
                      key={r.candidateId}
                      data-testid={`source-candidate-promoted-row-${r.candidateId}`}
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
                          <ProposedKindChip
                            kind={r.proposedKind}
                            testIdSuffix={`promoted-${r.candidateId}`}
                          />
                          <code
                            className="wb-mono"
                            style={{ fontSize: 11 }}
                          >
                            {r.proposedIdentifier}
                          </code>
                        </div>
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
                      <td style={{ padding: "6px 12px" }}>
                        {r.downstreamSourceProposedId ? (
                          <a
                            href={`/sources?id=${encodeURIComponent(r.downstreamSourceProposedId)}`}
                            data-testid={`source-candidate-downstream-link-${r.candidateId}`}
                            className="wb-mono"
                            style={{
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              textTransform: "uppercase",
                              color:
                                "var(--wb-color-botanical-green-deep, #2d5d3a)",
                              textDecoration: "underline",
                            }}
                          >
                            → source pipeline
                          </a>
                        ) : (
                          <span
                            data-testid={`source-candidate-downstream-missing-${r.candidateId}`}
                            className="wb-mono"
                            style={{
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              textTransform: "uppercase",
                              color:
                                "var(--wb-color-sepia-warning-deep, #b6741c)",
                              fontStyle: "italic",
                            }}
                            title="Promote audit entry landed but the downstream source_proposed did not fire — Sub-wave C handoff concern #1 (dual-write atomicity). Investigate the source-builder."
                          >
                            promote succeeded · downstream did not fire ·
                            investigate
                          </span>
                        )}
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

          {/* REJECTED CANDIDATES (collapsed by default) */}
          <details
            data-testid="source-candidate-rejected-section"
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
              Rejected candidates · {rejected.length} · last 30 days
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
                  No candidates rejected in the last 30 days.
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
                        Proposed (kind · identifier)
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
                        key={r.candidateId}
                        data-testid={`source-candidate-rejected-row-${r.candidateId}`}
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
                            <ProposedKindChip
                              kind={r.proposedKind}
                              testIdSuffix={`rejected-${r.candidateId}`}
                            />
                            <code
                              className="wb-mono"
                              style={{ fontSize: 11 }}
                            >
                              {r.proposedIdentifier}
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
