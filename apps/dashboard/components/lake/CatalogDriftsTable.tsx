/**
 * CatalogDriftsTable — pending proposals section of
 * /lake/catalog-drift (L2 Sub-wave D, 2026-06-09).
 *
 * Owns the modal state for Acknowledge + Reject dialogs and a
 * group-by toggle (drift_kind / source_id). The actual writes are
 * server actions threaded in via the props.
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state. Optimistic in-memory
 * removal is intentionally avoided — wire-replay determinism
 * preference means we re-fetch from the source of truth.
 *
 * High-density advisory above the table when rows > 200 (mirrors
 * L1's discipline; L2 drift enumeration can spike during major
 * migrations touching many tables at once).
 */

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { CatalogDriftRow as CatalogDriftRowData } from "../../lib/catalog-drift";
import { makeImpactCountKey } from "../../lib/catalog-drift";
import { CatalogDriftAcknowledgeModal } from "./CatalogDriftAcknowledgeModal";
import { CatalogDriftRejectionModal } from "./CatalogDriftRejectionModal";
import { CatalogDriftRow } from "./CatalogDriftRow";

type GroupBy = "none" | "drift_kind" | "source_id";

/** Threshold above which the high-density advisory renders. Mirrors
 *  L1's ``HIGH_DENSITY_THRESHOLD``. */
export const HIGH_DENSITY_THRESHOLD = 200;

export interface CatalogDriftsTableProps {
  rows: CatalogDriftRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  acknowledgeAction: (
    driftId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    driftId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  /**
   * L4↦L2 reverse-arc enrichment (Half B): map from
   * ``makeImpactCountKey(sourceId, tableId, column)`` →
   * impact count. Empty map (or undefined) renders no badges on any
   * row. Threaded from the page accessor
   * :func:`getImpactCountByDriftSource`.
   */
  impactCounts?: Record<string, number>;
}

function groupKey(drift: CatalogDriftRowData, by: GroupBy): string {
  switch (by) {
    case "drift_kind":
      return drift.driftKind;
    case "source_id":
      return drift.sourceId;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "drift_kind":
      return "by drift_kind";
    case "source_id":
      return "by source_id";
    case "none":
      return "no grouping";
  }
}

export function CatalogDriftsTable({
  rows,
  isAdmin,
  acknowledgeAction,
  rejectAction,
  impactCounts,
}: CatalogDriftsTableProps): JSX.Element {
  const router = useRouter();
  const [acknowledging, setAcknowledging] =
    useState<CatalogDriftRowData | null>(null);
  const [rejecting, setRejecting] =
    useState<CatalogDriftRowData | null>(null);
  // Default group-by is drift_kind — L2's 5 kinds are the primary
  // mental model for triage. Group-by source_id surfaces "all the
  // drifts hitting one source" (e.g. a single migration touching
  // multiple tables of one DB).
  const [groupBy, setGroupBy] = useState<GroupBy>("drift_kind");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, CatalogDriftRowData[]>();
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

  const handleAcknowledge = async (
    driftId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await acknowledgeAction(driftId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    driftId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(driftId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const highDensity = rows.length > HIGH_DENSITY_THRESHOLD;

  return (
    <section
      data-testid="catalog-drift-proposals-section"
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
            Pending drifts · {rows.length}
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
            Catalog drifts proposed by the L2 inference axis (table_set
            / column_set / column_type). Each drift carries one of 5
            ``drift_kind`` enum values, the affected
            ``source.table[.column]``, the before→after delta, the
            proposing strategy, and a confidence score. Acknowledge
            to record the drift as known/expected (record-only — no
            downstream pipeline); reject with a categorical reason so
            the strategies can downweight similar future drifts.
            {!isAdmin
              ? " Read-only — admin role required to acknowledge or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="catalog-drift-group-by"
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
            id="catalog-drift-group-by"
            data-testid="catalog-drift-group-by"
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
            <option value="drift_kind">By drift_kind</option>
            <option value="source_id">By source_id</option>
            <option value="none">No grouping</option>
          </select>
        </label>
      </header>

      {/* High-density advisory — mirrors L1's discipline. */}
      {highDensity ? (
        <div
          data-testid="catalog-drift-high-density-advisory"
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
            High density · {rows.length} pending drifts
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
            More than {HIGH_DENSITY_THRESHOLD} pending drifts. Group by
            source_id and triage in bulk — a major schema migration
            often surfaces dozens of column-level drifts under one
            source_id, where ``expected_change`` is the appropriate
            reject reason en bloc.
          </p>
        </div>
      ) : null}

      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`catalog-drift-proposals-group-${group.key}`}
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
                  Drift (kind · target)
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Before → After
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
              {group.rows.map((row) => {
                const key = makeImpactCountKey(
                  row.sourceId,
                  row.tableId,
                  row.column,
                );
                const impactCount = impactCounts?.[key];
                return (
                  <CatalogDriftRow
                    key={row.driftId}
                    drift={row}
                    disabled={!isAdmin}
                    onAcknowledge={(d) => setAcknowledging(d)}
                    onReject={(d) => setRejecting(d)}
                    impactCount={impactCount}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      <CatalogDriftAcknowledgeModal
        driftId={acknowledging?.driftId ?? ""}
        open={acknowledging !== null}
        onClose={() => setAcknowledging(null)}
        onSubmit={handleAcknowledge}
      />
      <CatalogDriftRejectionModal
        driftId={rejecting?.driftId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
