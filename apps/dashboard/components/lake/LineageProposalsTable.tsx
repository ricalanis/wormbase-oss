/**
 * LineageProposalsTable — pending proposals section of /lake/lineage.
 *
 * Owns the modal state for Confirm + Reject dialogs. The actual writes
 * are server actions threaded in via the props (so the page can keep
 * the actions co-located in actions.ts).
 *
 * On a successful action the table calls ``router.refresh()`` so the
 * server fetches the latest projection state.  Optimistic in-memory
 * removal is intentionally avoided — the wire-replay determinism
 * preference means we re-fetch from the source of truth.
 */

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { LineageEdgeRow } from "../../lib/lineage";
import { LineageConfirmModal } from "./LineageConfirmModal";
import { LineageProposalRow } from "./LineageProposalRow";
import { LineageRejectionModal } from "./LineageRejectionModal";

export interface LineageProposalsTableProps {
  rows: LineageEdgeRow[];
  /** True when the caller holds an admin/installer grant. */
  isAdmin: boolean;
  confirmAction: (
    edgeId: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  rejectAction: (
    edgeId: string,
    reason: string,
    notes?: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  /**
   * L4↦L3 reverse-arc enrichment (Recipe Addendum #3): map from
   * ``edgeId`` → downstream schema-impact count. Empty map (or
   * undefined) renders no badge on any row. Threaded from the page
   * accessor :func:`getSchemaImpactCountByLineageEdge`.
   */
  impactCounts?: Record<string, number>;
}

export function LineageProposalsTable({
  rows,
  isAdmin,
  confirmAction,
  rejectAction,
  impactCounts,
}: LineageProposalsTableProps): JSX.Element {
  const router = useRouter();
  const [confirming, setConfirming] = useState<LineageEdgeRow | null>(null);
  const [rejecting, setRejecting] = useState<LineageEdgeRow | null>(null);

  const handleConfirm = async (
    edgeId: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await confirmAction(edgeId, notes);
    if (result.ok) router.refresh();
    return result;
  };

  const handleReject = async (
    edgeId: string,
    reason: string,
    notes?: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const result = await rejectAction(edgeId, reason, notes);
    if (result.ok) router.refresh();
    return result;
  };

  return (
    <section
      data-testid="lineage-proposals-section"
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
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
          Candidate edges proposed by the L3 inference axis. Confirm to
          commit them to the lineage graph; reject with a categorical
          reason so the strategies can downweight future candidates of
          the same shape.
          {!isAdmin
            ? " Read-only — admin role required to confirm or reject."
            : null}
        </p>
      </header>
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
            <th style={{ padding: "6px 12px", textAlign: "left" }}>Source</th>
            <th style={{ padding: "6px 12px", textAlign: "left" }}>Target</th>
            <th style={{ padding: "6px 12px", textAlign: "right" }}>Conf.</th>
            <th style={{ padding: "6px 12px", textAlign: "left" }}>Strategy</th>
            <th style={{ padding: "6px 12px", textAlign: "right" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <LineageProposalRow
              key={row.edgeId}
              edge={row}
              disabled={!isAdmin}
              onConfirm={(e) => setConfirming(e)}
              onReject={(e) => setRejecting(e)}
              impactCount={impactCounts?.[row.edgeId]}
            />
          ))}
        </tbody>
      </table>
      <p
        className="wb-mono"
        style={{
          margin: 0,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray, #7c7569)",
          fontStyle: "italic",
        }}
      >
        Re-trigger is gated by WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS
        (24h default) — a re-proposal of the same logical edge within
        the window folds onto this row rather than creating a new one.
      </p>
      <LineageConfirmModal
        edgeId={confirming?.edgeId ?? ""}
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onSubmit={handleConfirm}
      />
      <LineageRejectionModal
        edgeId={rejecting?.edgeId ?? ""}
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        onSubmit={handleReject}
      />
    </section>
  );
}
