/**
 * QualityProposalsTable — pending proposals section of /lake/quality
 * (L7 Sub-wave D, 2026-05-30).
 *
 * Owns the modal state for Confirm + Reject dialogs and a group-by
 * toggle (table / kind / strategy per spec §4.1). The actual writes
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

import type { QualityCheckRow as QualityCheckRowData } from "../../lib/quality";
import { QualityCheckRow } from "./QualityCheckRow";
import { QualityConfirmModal } from "./QualityConfirmModal";
import { QualityRejectionModal } from "./QualityRejectionModal";

type GroupBy = "none" | "table" | "kind" | "strategy";

export interface QualityProposalsTableProps {
  rows: QualityCheckRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    checkId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    checkId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

function groupKey(check: QualityCheckRowData, by: GroupBy): string {
  switch (by) {
    case "table":
      return check.tableId;
    case "kind":
      return check.checkKind;
    case "strategy":
      return check.strategy;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "table":
      return "by table";
    case "kind":
      return "by kind";
    case "strategy":
      return "by strategy";
    case "none":
      return "no grouping";
  }
}

export function QualityProposalsTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
}: QualityProposalsTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] = useState<QualityCheckRowData | null>(
    null,
  );
  const [rejecting, setRejecting] = useState<QualityCheckRowData | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, QualityCheckRowData[]>();
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
    checkId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(checkId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    checkId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(checkId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  return (
    <section
      data-testid="quality-proposals-section"
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
            Candidate checks proposed by the L7 inference axis. Confirm
            to commit them to the quality plane; reject with a
            categorical reason so the strategies can downweight future
            candidates of the same shape.
            {!isAdmin
              ? " Read-only — admin role required to confirm or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="quality-group-by"
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
            id="quality-group-by"
            data-testid="quality-group-by"
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
            <option value="kind">By kind</option>
            <option value="strategy">By strategy</option>
          </select>
        </label>
      </header>
      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`quality-proposals-group-${group.key}`}
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
                  Table
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Column
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
                <th style={{ padding: "6px 12px", textAlign: "right" }}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <QualityCheckRow
                  key={row.checkId}
                  check={row}
                  disabled={!isAdmin}
                  onConfirm={(c) => setConfirming(c)}
                  onReject={(c) => setRejecting(c)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p
        className="wb-mono"
        data-testid="quality-window-footnote"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-proposal is dedup&apos;d via WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS
        (24h default) — a re-proposal of the same logical check within
        the window folds onto this row rather than creating a new one.
      </p>
      <QualityConfirmModal
        checkId={confirming?.checkId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <QualityRejectionModal
        checkId={rejecting?.checkId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
