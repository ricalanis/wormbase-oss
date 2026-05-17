/**
 * SemanticTypeProposalsTable — pending proposals section of
 * /lake/semantic-types (L5 Sub-wave D, 2026-06-05).
 *
 * Owns the modal state for Confirm + Reject dialogs and a group-by
 * toggle (table / semantic_type / strategy). The actual writes are
 * server actions threaded in via the props (so the page can keep the
 * actions co-located in actions.ts).
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state. Optimistic in-memory
 * removal is intentionally avoided — the wire-replay determinism
 * preference means we re-fetch from the source of truth.
 */

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { SemanticTypeRow as SemanticTypeRowData } from "../../lib/semantic-types";
import { SemanticTypeConfirmModal } from "./SemanticTypeConfirmModal";
import { SemanticTypeRejectionModal } from "./SemanticTypeRejectionModal";
import { SemanticTypeRow } from "./SemanticTypeRow";

type GroupBy = "none" | "table" | "semantic_type" | "strategy";

export interface SemanticTypeProposalsTableProps {
  rows: SemanticTypeRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    typeId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    typeId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  /**
   * Reverse-arc enrichment (Recipe Addendum #3): four downstream
   * consumer count maps keyed by ``typeId``. Empty maps (or
   * undefined) render no chips on any row. Threaded from the page
   * accessors (R2 L6↦L5 / R3 L8↦L5 / R4 L7↦L5 / R6 L4↦L5).
   */
  classificationCounts?: Record<string, number>;
  entityStitchCounts?: Record<string, number>;
  qualityCounts?: Record<string, number>;
  impactCounts?: Record<string, number>;
}

function groupKey(proposal: SemanticTypeRowData, by: GroupBy): string {
  switch (by) {
    case "table":
      return proposal.tableId;
    case "semantic_type":
      return proposal.semanticType;
    case "strategy":
      return proposal.strategy;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "table":
      return "by table";
    case "semantic_type":
      return "by semantic_type";
    case "strategy":
      return "by strategy";
    case "none":
      return "no grouping";
  }
}

export function SemanticTypeProposalsTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
  classificationCounts,
  entityStitchCounts,
  qualityCounts,
  impactCounts,
}: SemanticTypeProposalsTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] = useState<SemanticTypeRowData | null>(
    null,
  );
  const [rejecting, setRejecting] = useState<SemanticTypeRowData | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, SemanticTypeRowData[]>();
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

  const handleConfirm = async (
    typeId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(typeId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    typeId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(typeId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  return (
    <section
      data-testid="semantic-type-proposals-section"
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
            Candidate semantic types proposed by the L5 fingerprinting
            axis (column_name / value_pattern / distribution). Confirm
            to commit them; reject with a categorical reason so the
            strategies can downweight future candidates of the same
            shape. PII-band proposals (pii_name / pii_address /
            pii_ssn / pii_credit_card) carry a sensitivity chip —
            confirming them seeds the Phase 2 L5 → L6 ``regulated``
            classification chain.
            {!isAdmin
              ? " Read-only — admin role required to confirm or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="semantic-type-group-by"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 11,
            minWidth: 160,
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
            id="semantic-type-group-by"
            data-testid="semantic-type-group-by"
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
            <option value="none">No grouping</option>
            <option value="table">By table</option>
            <option value="semantic_type">By semantic_type</option>
            <option value="strategy">By strategy</option>
          </select>
        </label>
      </header>
      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`semantic-type-proposals-group-${group.key}`}
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
                <th style={{ padding: "6px 12px", textAlign: "right" }}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <SemanticTypeRow
                  key={row.typeId}
                  proposal={row}
                  disabled={!isAdmin}
                  onConfirm={(c) => setConfirming(c)}
                  onReject={(c) => setRejecting(c)}
                  classificationCount={classificationCounts?.[row.typeId]}
                  entityStitchCount={entityStitchCounts?.[row.typeId]}
                  qualityCount={qualityCounts?.[row.typeId]}
                  impactCount={impactCounts?.[row.typeId]}
                />
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p
        className="wb-mono"
        data-testid="semantic-type-window-footnote"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-proposal is dedup&apos;d via
        WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS (24h default) — a
        re-proposal of the same logical (table_id, column,
        semantic_type) within the window folds onto this row rather
        than creating a new one.
      </p>
      <SemanticTypeConfirmModal
        typeId={confirming?.typeId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <SemanticTypeRejectionModal
        typeId={rejecting?.typeId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
