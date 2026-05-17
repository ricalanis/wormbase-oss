"use client";
/**
 * SourceListInteractive — client wrapper that makes /sources rows
 * clickable into the SourceDetailDrawer.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Wraps each `<SourceRow>` in a button-like region; clicking opens the
 * drawer for that source. The drawer's own writes (classification +
 * maintainer) update the local state so the row re-renders without a
 * page refresh — the next dashboard navigation re-reads from the
 * ledger projection so the wire is the source of truth.
 *
 * Phase 3 Task 3D — sort control. The list defaults to the parent's
 * "default lake first" order (set in `app/(app)/sources/page.tsx`); the
 * "freshness" / "staleness" sort options re-order by
 * `projection_sources.last_seen` so an operator chasing a stale source
 * lands on it without scanning. Default-lake rows always pin to the top.
 */
import { useMemo, useState } from "react";
import { SourceRow } from "./SourceRow";
import { SourceDetailDrawer } from "./SourceDetailDrawer";
import type { SourceRow as SourceRowModel } from "../../lib/ledger-client.types";

export interface SourceListInteractiveProps {
  rows: SourceRowModel[];
  people?: { personId: string; displayName: string }[];
  currentPersonId: string | null;
}

type SortKey = "default" | "fresh" | "stale";

function isDefaultLake(row: SourceRowModel): boolean {
  return (
    row.kind === "local_lake" && row.addedViaFlow === "provisioned_at_install"
  );
}

function freshnessScore(row: SourceRowModel): number {
  // last_seen is the canonical freshness pin (Wave G v003 migration).
  // Fall back to lastProfileTs for pre-Wave-G fixtures so the sort
  // remains meaningful. -Infinity sentinel pushes "never seen" rows to
  // the bottom of fresh-first / top of stale-first.
  if (row.lastSeen) return new Date(row.lastSeen).getTime();
  if (row.lastProfileTs) return new Date(row.lastProfileTs).getTime();
  return Number.NEGATIVE_INFINITY;
}

export function SourceListInteractive({
  rows: initialRows,
  people,
  currentPersonId,
}: SourceListInteractiveProps) {
  const [rows, setRows] = useState<SourceRowModel[]>(initialRows);
  const [openSourceId, setOpenSourceId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("default");

  const sortedRows = useMemo<SourceRowModel[]>(() => {
    if (sortKey === "default") return rows;
    return [...rows].sort((a, b) => {
      // Default lake always pins to the top regardless of freshness
      // sort — it's the worm's "yours from minute zero" anchor row.
      const aDefault = isDefaultLake(a);
      const bDefault = isDefaultLake(b);
      if (aDefault && !bDefault) return -1;
      if (!aDefault && bDefault) return 1;
      const aS = freshnessScore(a);
      const bS = freshnessScore(b);
      return sortKey === "fresh" ? bS - aS : aS - bS;
    });
  }, [rows, sortKey]);

  const open = openSourceId
    ? (rows.find((r) => r.sourceId === openSourceId) ?? null)
    : null;

  function applyUpdate(sourceId: string, next: Partial<SourceRowModel>) {
    setRows((prev) =>
      prev.map((r) =>
        r.sourceId === sourceId
          ? ({ ...r, ...next } as SourceRowModel)
          : r,
      ),
    );
  }

  return (
    <>
      <div
        data-testid="sources-sort-controls"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 11,
          marginBottom: 4,
        }}
      >
        <span
          className="wb-mono"
          style={{
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          sort
        </span>
        {(["default", "fresh", "stale"] as SortKey[]).map((k) => (
          <button
            key={k}
            type="button"
            data-testid={`sources-sort-${k}`}
            data-active={sortKey === k ? "true" : "false"}
            onClick={() => setSortKey(k)}
            className="wb-mono"
            style={{
              fontSize: 11,
              padding: "2px 8px",
              border: "1px solid var(--wb-color-paper-edge)",
              borderColor:
                sortKey === k
                  ? "var(--wb-color-aged-ink)"
                  : "var(--wb-color-paper-edge)",
              background:
                sortKey === k
                  ? "var(--wb-color-aged-ink)"
                  : "transparent",
              color:
                sortKey === k ? "var(--wb-color-paper)" : "var(--wb-color-aged-ink)",
              cursor: "pointer",
            }}
          >
            {k === "default" ? "default" : k === "fresh" ? "freshest" : "stalest"}
          </button>
        ))}
      </div>
      <section
        data-testid="sources-list"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        {sortedRows.map((row) => (
          <div
            key={row.sourceId}
            data-testid={`source-row-clickable-${row.sourceId}`}
            role="button"
            tabIndex={0}
            onClick={() => setOpenSourceId(row.sourceId)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setOpenSourceId(row.sourceId);
              }
            }}
            style={{ cursor: "pointer" }}
          >
            <SourceRow row={row} />
          </div>
        ))}
      </section>
      {open ? (
        <SourceDetailDrawer
          source={open}
          people={people}
          currentPersonId={currentPersonId}
          onClose={() => setOpenSourceId(null)}
          onSourceUpdated={(next) => applyUpdate(open.sourceId, next)}
        />
      ) : null}
    </>
  );
}
