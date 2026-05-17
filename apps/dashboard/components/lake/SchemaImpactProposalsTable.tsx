/**
 * SchemaImpactProposalsTable — pending proposals section of
 * /lake/schema-impact (L4 Sub-wave D, 2026-06-02).
 *
 * Owns the modal state for Confirm + Reject dialogs and a group-by
 * toggle (source / impact_kind / target_table / strategy per spec §4.1
 * — note L4 has FOUR group-by axes vs L7's three). The actual writes
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

import type { SchemaImpactRow as SchemaImpactRowData } from "../../lib/schema-impact";
import { SchemaImpactConfirmModal } from "./SchemaImpactConfirmModal";
import { SchemaImpactRejectionModal } from "./SchemaImpactRejectionModal";
import { SchemaImpactRow } from "./SchemaImpactRow";

type GroupBy = "none" | "source" | "impact_kind" | "target_table" | "strategy";

export interface SchemaImpactProposalsTableProps {
  rows: SchemaImpactRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    impactId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    impactId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

function groupKey(impact: SchemaImpactRowData, by: GroupBy): string {
  switch (by) {
    case "source":
      return impact.sourceId;
    case "impact_kind":
      return impact.impactKind;
    case "target_table":
      return impact.tgtTableId;
    case "strategy":
      return impact.strategy;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "source":
      return "by source";
    case "impact_kind":
      return "by impact_kind";
    case "target_table":
      return "by target_table";
    case "strategy":
      return "by strategy";
    case "none":
      return "no grouping";
  }
}

export function SchemaImpactProposalsTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
}: SchemaImpactProposalsTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] = useState<SchemaImpactRowData | null>(
    null,
  );
  const [rejecting, setRejecting] = useState<SchemaImpactRowData | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, SchemaImpactRowData[]>();
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
    impactId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(impactId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    impactId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(impactId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  return (
    <section
      data-testid="schema-impact-proposals-section"
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
            Candidate impacts proposed by the L4 inference axis. Confirm
            to commit them; reject with a categorical reason so the
            strategies can downweight future candidates of the same
            shape. Rows that came from L3 (the ``lineage_edge``
            strategy) carry a &quot;view L3 edge&quot; link — the first
            cross-axis trace navigation in the lake stack.
            {!isAdmin
              ? " Read-only — admin role required to confirm or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="schema-impact-group-by"
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
            id="schema-impact-group-by"
            data-testid="schema-impact-group-by"
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
            <option value="source">By source</option>
            <option value="impact_kind">By impact_kind</option>
            <option value="target_table">By target_table</option>
            <option value="strategy">By strategy</option>
          </select>
        </label>
      </header>
      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`schema-impact-proposals-group-${group.key}`}
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
                  Change
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Downstream
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Change kind
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Impact kind
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
                <SchemaImpactRow
                  key={row.impactId}
                  impact={row}
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
        data-testid="schema-impact-window-footnote"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-proposal is dedup&apos;d via
        WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS (24h default) — a
        re-proposal of the same logical impact within the window folds
        onto this row rather than creating a new one.
      </p>
      <SchemaImpactConfirmModal
        impactId={confirming?.impactId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <SchemaImpactRejectionModal
        impactId={rejecting?.impactId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
