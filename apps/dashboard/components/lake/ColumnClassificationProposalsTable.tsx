/**
 * ColumnClassificationProposalsTable — pending proposals section of
 * /lake/column-classification (L6 Sub-wave D, 2026-06-06).
 *
 * Owns the modal state for Confirm + Reject dialogs and a group-by
 * toggle (classification_level / table / strategy). The actual writes
 * are server actions threaded in via the props (so the page can keep
 * the actions co-located in actions.ts).
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state. Optimistic in-memory
 * removal is intentionally avoided — the wire-replay determinism
 * preference means we re-fetch from the source of truth.
 */

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { ColumnClassificationRow as ColumnClassificationRowData } from "../../lib/column-classification";
import { ColumnClassificationConfirmModal } from "./ColumnClassificationConfirmModal";
import { ColumnClassificationRejectionModal } from "./ColumnClassificationRejectionModal";
import { ColumnClassificationRow } from "./ColumnClassificationRow";

type GroupBy = "none" | "classification_level" | "table" | "strategy";

export interface ColumnClassificationProposalsTableProps {
  rows: ColumnClassificationRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    classificationId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    classificationId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  /**
   * L4↦L6 reverse-arc enrichment (Recipe Addendum #3): map from
   * ``classificationId`` → downstream schema-impact count. Empty map
   * (or undefined) renders no badge on any row. Threaded from the
   * page accessor :func:`getSchemaImpactCountByClassification`.
   */
  impactCounts?: Record<string, number>;
}

function groupKey(
  proposal: ColumnClassificationRowData,
  by: GroupBy,
): string {
  switch (by) {
    case "classification_level":
      return proposal.classificationLevel;
    case "table":
      return proposal.tableId;
    case "strategy":
      return proposal.strategy;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "classification_level":
      return "by classification_level";
    case "table":
      return "by table";
    case "strategy":
      return "by strategy";
    case "none":
      return "no grouping";
  }
}

export function ColumnClassificationProposalsTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
  impactCounts,
}: ColumnClassificationProposalsTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] =
    useState<ColumnClassificationRowData | null>(null);
  const [rejecting, setRejecting] =
    useState<ColumnClassificationRowData | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, ColumnClassificationRowData[]>();
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
    classificationId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(classificationId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    classificationId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(classificationId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  return (
    <section
      data-testid="column-classification-proposals-section"
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
            Candidate column classifications proposed by the L6 inference
            axis (semantic_type / naming_pattern / domain_default). Each
            proposal pins one of 5 governance levels (public / internal
            / confidential / pii / regulated). Confirm to commit them;
            reject with a categorical reason so the strategies can
            downweight future candidates of the same shape. Proposals
            from the ``semantic_type`` strategy carry a cross-axis link
            back to the L5 confirmed semantic type that drove them
            (e.g. ``pii_ssn`` → ``regulated``).
            {!isAdmin
              ? " Read-only — admin role required to confirm or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="column-classification-group-by"
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
            id="column-classification-group-by"
            data-testid="column-classification-group-by"
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
            <option value="classification_level">By classification_level</option>
            <option value="table">By table</option>
            <option value="strategy">By strategy</option>
          </select>
        </label>
      </header>
      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`column-classification-proposals-group-${group.key}`}
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
                  Classification
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
                <ColumnClassificationRow
                  key={row.classificationId}
                  proposal={row}
                  disabled={!isAdmin}
                  onConfirm={(c) => setConfirming(c)}
                  onReject={(c) => setRejecting(c)}
                  impactCount={impactCounts?.[row.classificationId]}
                />
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p
        className="wb-mono"
        data-testid="column-classification-window-footnote"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-proposal is dedup&apos;d via
        WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS (24h
        default) — a re-proposal of the same logical (table_id, column,
        classification_level, strategy) within the window folds onto
        this row rather than creating a new one.
      </p>
      <ColumnClassificationConfirmModal
        classificationId={confirming?.classificationId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <ColumnClassificationRejectionModal
        classificationId={rejecting?.classificationId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
