/**
 * EntityStitchesTable — pending proposals section of
 * /lake/entity-stitches (L8 Sub-wave D, 2026-06-07).
 *
 * Owns the modal state for Confirm + Reject dialogs and a group-by
 * toggle (entity_kind / strategy). The actual writes are server
 * actions threaded in via the props (so the page can keep the
 * actions co-located in actions.ts).
 *
 * Per Sub-wave C handoff concern #2 — pair enumeration is O(N²) at
 * the inference layer, so high row counts on this surface signal
 * dense pair-space. When ``rows.length > 200`` the table renders a
 * soft "high density" advisory above the table (non-blocking, just
 * informational so admins know they may want to filter or batch-
 * approve).
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state. Optimistic in-memory
 * removal is intentionally avoided — the wire-replay determinism
 * preference means we re-fetch from the source of truth.
 */

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { EntityStitchRow as EntityStitchRowData } from "../../lib/entity-stitches";
import { EntityStitchConfirmModal } from "./EntityStitchConfirmModal";
import { EntityStitchRejectionModal } from "./EntityStitchRejectionModal";
import { EntityStitchRow } from "./EntityStitchRow";

type GroupBy = "none" | "entity_kind" | "strategy";

/** Threshold above which the high-density advisory renders. Per
 *  Sub-wave C handoff concern #2 (pair enumeration is O(N²) at the
 *  inference layer). Soft, not blocking. */
export const HIGH_DENSITY_THRESHOLD = 200;

export interface EntityStitchesTableProps {
  rows: EntityStitchRowData[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    stitchId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    stitchId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
}

function groupKey(
  proposal: EntityStitchRowData,
  by: GroupBy,
): string {
  switch (by) {
    case "entity_kind":
      return proposal.entityKind;
    case "strategy":
      return proposal.strategy;
    case "none":
      return "all";
  }
}

function groupLabel(by: GroupBy): string {
  switch (by) {
    case "entity_kind":
      return "by entity_kind";
    case "strategy":
      return "by strategy";
    case "none":
      return "no grouping";
  }
}

export function EntityStitchesTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
}: EntityStitchesTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] =
    useState<EntityStitchRowData | null>(null);
  const [rejecting, setRejecting] =
    useState<EntityStitchRowData | null>(null);
  // Default group-by is entity_kind to lean on the 8-color chip
  // discipline as the primary visual organizer for stitch proposals.
  const [groupBy, setGroupBy] = useState<GroupBy>("entity_kind");

  const grouped = useMemo(() => {
    if (groupBy === "none") {
      return [{ key: "all", rows }];
    }
    const buckets = new Map<string, EntityStitchRowData[]>();
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
    stitchId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(stitchId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    stitchId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(stitchId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const highDensity = rows.length > HIGH_DENSITY_THRESHOLD;

  return (
    <section
      data-testid="entity-stitch-proposals-section"
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
            Candidate cross-source entity stitches proposed by the L8
            inference axis (name_match / sample_overlap / schema_shape).
            Each proposal bridges two columns across sources at one of
            8 entity classes (person / organization / transaction /
            product / event / location / session / other). Confirm to
            commit them; reject with a categorical reason so the
            strategies can downweight future candidates of the same
            shape. Proposals from NameMatch&apos;s semantic-type-anchor
            path carry a cross-axis link back to the L5 confirmed
            semantic type that drove them (third cross-axis chain;
            reuses L6&apos;s Protocol).
            {!isAdmin
              ? " Read-only — admin role required to confirm or reject."
              : null}
          </p>
        </div>
        <label
          htmlFor="entity-stitch-group-by"
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
            id="entity-stitch-group-by"
            data-testid="entity-stitch-group-by"
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
            <option value="entity_kind">By entity_kind</option>
            <option value="strategy">By strategy</option>
            <option value="none">No grouping</option>
          </select>
        </label>
      </header>

      {/* High-density advisory — Sub-wave C handoff concern #2. Soft,
          not blocking — just informational so admins know the pair-
          space is dense and they may want to filter or batch-approve. */}
      {highDensity ? (
        <div
          data-testid="entity-stitch-high-density-advisory"
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
            High density · {rows.length} pending stitches
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
            More than {HIGH_DENSITY_THRESHOLD} pending stitch proposals.
            Pair enumeration is O(N²) at the inference layer (Sub-wave
            C handoff concern #2), so dense pair-space here usually
            means several sources just landed catalog imports. Consider
            grouping by entity_kind or strategy + confirming/rejecting
            in bulk to keep the queue tractable.
          </p>
        </div>
      ) : null}

      {grouped.map((group) => (
        <div
          key={group.key}
          data-testid={`entity-stitch-proposals-group-${group.key}`}
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
                  Endpoints (a ↔ b)
                </th>
                <th style={{ padding: "6px 12px", textAlign: "left" }}>
                  Entity kind
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
                <EntityStitchRow
                  key={row.stitchId}
                  proposal={row}
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
        data-testid="entity-stitch-window-footnote"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-proposal is dedup&apos;d via
        WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS (24h default) —
        a re-proposal of the same logical pair (in either A↔B order)
        within the window folds onto this row rather than creating a
        new one (stitch_id is order-independent SHA-256 over the
        canonical endpoint pair).
      </p>
      <EntityStitchConfirmModal
        stitchId={confirming?.stitchId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <EntityStitchRejectionModal
        stitchId={rejecting?.stitchId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
