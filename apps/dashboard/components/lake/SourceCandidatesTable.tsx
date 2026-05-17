/**
 * SourceCandidatesTable — pending proposals section of
 * /lake/source-candidates (L1 Sub-wave D, 2026-06-08).
 *
 * Owns the modal state for Promote + Reject dialogs and a group-by
 * toggle (strategy / proposed_kind). The actual writes are server
 * actions threaded in via the props (so the page can keep the
 * actions co-located in actions.ts).
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state. Optimistic in-memory
 * removal is intentionally avoided — wire-replay determinism
 * preference means we re-fetch from the source of truth.
 *
 * High-density advisory above the table when rows > 200 (mirrors
 * L8's discipline; L1 candidate enumeration can also spike when many
 * KPI gaps or many connector mentions land in one window).
 */

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { SourceCandidateRow as SourceCandidateRowData } from "../../lib/source-candidates";
import { SourceCandidatePromoteModal } from "./SourceCandidatePromoteModal";
import { SourceCandidateRejectionModal } from "./SourceCandidateRejectionModal";
import { SourceCandidateRow } from "./SourceCandidateRow";

type GroupBy = "none" | "strategy" | "proposed_kind";

/** Threshold above which the high-density advisory renders. Mirrors
 *  L8's ``HIGH_DENSITY_THRESHOLD``. */
export const HIGH_DENSITY_THRESHOLD = 200;

export interface SourceCandidatesTableProps {
  rows: SourceCandidateRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  promoteAction: (
    candidateId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    candidateId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

function groupKey(
  proposal: SourceCandidateRowData,
  by: GroupBy,
): string {
  switch (by) {
    case "strategy":
      return proposal.strategy;
    case "proposed_kind":
      return proposal.proposedKind;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "strategy":
      return "by strategy";
    case "proposed_kind":
      return "by proposed_kind";
    case "none":
      return "no grouping";
  }
}

export function SourceCandidatesTable({
  rows,
  isAdmin,
  promoteAction,
  rejectAction,
}: SourceCandidatesTableProps): JSX.Element {
  const router = useRouter();
  const [promoting, setPromoting] =
    useState<SourceCandidateRowData | null>(null);
  const [rejecting, setRejecting] =
    useState<SourceCandidateRowData | null>(null);
  // Default group-by is strategy — L1's three strategies are the
  // primary mental model for triage. Group-by proposed_kind is the
  // alternative for connector-portfolio-thinking.
  const [groupBy, setGroupBy] = useState<GroupBy>("strategy");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, SourceCandidateRowData[]>();
    for (const r of rows) {
      const k = groupKey(r, groupBy);
      const existing = buckets.get(k);
      if (existing) {
        existing.push(r);
      } else {
        buckets.set(k, [r]);
      }
    }
    return Array.from(buckets.entries())
      .map(([key, bucketRows]) => ({ key, rows: bucketRows }))
      .sort((a, b) => a.key.localeCompare(b.key));
  }, [rows, groupBy]);

  const handlePromote = async (
    candidateId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await promoteAction(candidateId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    candidateId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(candidateId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const highDensity = rows.length > HIGH_DENSITY_THRESHOLD;

  return (
    <section
      data-testid="source-candidate-proposals-section"
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
    >
      <header
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-start",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Pending proposals · {rows.length}
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
            Candidate data sources proposed by the L1 inference axis
            (kpi_gap / channel_mention / complementarity). Each candidate
            carries a connector-registry kind, an identifier hint, the
            proposing strategy, and a confidence score. Promote to send
            the candidate downstream into the source-pipeline (dual-write
            — emits source_candidate_promoted AND triggers
            source_proposed); reject with a categorical reason so the
            strategies can downweight similar future candidates.
            {!isAdmin
              ? " Read-only — admin role required to promote or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="source-candidate-group-by"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 11,
            minWidth: 200,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            Group by
          </span>
          <select
            id="source-candidate-group-by"
            data-testid="source-candidate-group-by"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              padding: 4,
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
              background: "var(--wb-color-paper-deep, #f4eedb)",
            }}
          >
            <option value="strategy">By strategy</option>
            <option value="proposed_kind">By proposed_kind</option>
            <option value="none">No grouping</option>
          </select>
        </label>
      </header>

      {/* High-density advisory — mirrors L8's discipline. */}
      {highDensity ? (
        <div
          data-testid="source-candidate-high-density-advisory"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
            background: "var(--wb-color-paper-deep, #f4eedb)",
            padding: 10,
            display: "flex",
            flexDirection: "column",
            gap: 2,
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
            High density · {rows.length} pending candidates
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink, #2a2620)",
              fontSize: 12,
            }}
          >
            More than {HIGH_DENSITY_THRESHOLD} pending candidates.
            Group by strategy or proposed_kind and triage in bulk to
            keep the queue tractable. The most common L1-specific
            reject reason is ``duplicate`` (we already have an
            equivalent source); use it liberally.
          </p>
        </div>
      ) : null}

      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`source-candidate-proposals-group-${group.key}`}
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          {groupBy !== "none" ? (
            <span
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray, #7c7569)",
                marginTop: 6,
              }}
            >
              {groupLabel(groupBy)} · {group.key} · {group.rows.length}
            </span>
          ) : null}
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              background: "var(--wb-color-paper, #f8f3e1)",
              border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
            }}
          >
            <thead>
              <tr
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray, #7c7569)",
                  background: "var(--wb-color-paper-deep, #f4eedb)",
                }}
              >
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Proposed (kind · identifier)
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Domain hint
                </th>
                <th style={{ padding: "6px 12px", textAlign: "right" }}>
                  Conf.
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Strategy
                </th>
                <th style={{ padding: "6px 12px", textAlign: "right" }}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <SourceCandidateRow
                  key={row.candidateId}
                  proposal={row}
                  disabled={!isAdmin}
                  onPromote={(c) => setPromoting(c)}
                  onReject={(c) => setRejecting(c)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <SourceCandidatePromoteModal
        candidateId={promoting?.candidateId ?? ""}
        open={promoting !== null}
        onClose={() => setPromoting(null)}
        onSubmit={handlePromote}
      />
      <SourceCandidateRejectionModal
        candidateId={rejecting?.candidateId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
