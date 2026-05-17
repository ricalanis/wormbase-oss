"use client";
/**
 * ReactivitiesView — client wrapper for /reactivities (W5.A5).
 *
 * Owns:
 *   - "Show disabled" toggle (boolean state).
 *   - "Propose new reactivity" modal mount.
 *   - Refresh of the reactivity list after mutations.
 *
 * Reactivities arrive from the server component as the initial list;
 * after a confirm/disable/propose mutation we refetch via
 * /api/v1/reactivities/list so the rendered state matches the registry.
 */

import { useCallback, useState } from "react";
import type { Reactivity } from "../../lib/ledger-client.types";
import { ProposeReactivityModal } from "./ProposeReactivityModal";
import { ReactivityCard } from "./ReactivityCard";

interface ReactivitiesViewProps {
  initialReactivities: Reactivity[];
}

function bySection(rows: Reactivity[]): {
  active: Reactivity[];
  proposed: Reactivity[];
  disabled: Reactivity[];
} {
  const active: Reactivity[] = [];
  const proposed: Reactivity[] = [];
  const disabled: Reactivity[] = [];
  for (const r of rows) {
    if (r.state === "active") active.push(r);
    else if (r.state === "proposed") proposed.push(r);
    else if (r.state === "disabled") disabled.push(r);
  }
  // Active sorted by last-fire desc (most active first).
  active.sort((a, b) => {
    const at = a.lastFiredAt ?? "0";
    const bt = b.lastFiredAt ?? "0";
    return bt.localeCompare(at);
  });
  return { active, proposed, disabled };
}

export function ReactivitiesView({
  initialReactivities,
}: ReactivitiesViewProps) {
  const [rows, setRows] = useState<Reactivity[]>(initialReactivities);
  const [showDisabled, setShowDisabled] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/reactivities/list", {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as { reactivities?: Reactivity[] };
      if (Array.isArray(body.reactivities)) {
        setRows(body.reactivities);
      }
    } catch {
      // Silent — keep prior rows if refresh fails.
    }
  }, []);

  const sections = bySection(rows);

  return (
    <div
      data-testid="reactivities-view"
      style={{ display: "flex", flexDirection: "column", gap: 28 }}
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          data-testid="reactivities-propose-cta"
          onClick={() => setModalOpen(true)}
          style={{
            padding: "8px 14px",
            border: "1px solid var(--wb-color-botanical-green-deep)",
            background: "var(--wb-color-botanical-green)",
            color: "var(--wb-color-paper)",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Propose new reactivity
        </button>
        <button
          type="button"
          data-testid="reactivities-show-disabled-toggle"
          onClick={() => setShowDisabled((v) => !v)}
          style={{
            padding: "8px 14px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "transparent",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          {showDisabled
            ? `Hide disabled (${sections.disabled.length})`
            : `Show disabled (${sections.disabled.length})`}
        </button>
      </div>

      <ReactivitySection
        testId="reactivities-active"
        title="Active reactivities"
        eyebrow={`${sections.active.length} firing`}
        emptyLabel="no active reactivities"
        rows={sections.active}
        onMutated={refresh}
      />

      <ReactivitySection
        testId="reactivities-proposed"
        title="Pending proposals"
        eyebrow={`${sections.proposed.length} awaiting confirm`}
        emptyLabel="no pending proposals"
        rows={sections.proposed}
        onMutated={refresh}
      />

      {showDisabled ? (
        <ReactivitySection
          testId="reactivities-disabled"
          title="Disabled reactivities"
          eyebrow={`${sections.disabled.length} disabled · audit-only`}
          emptyLabel="no disabled reactivities"
          rows={sections.disabled}
          onMutated={refresh}
        />
      ) : null}

      {modalOpen ? (
        <ProposeReactivityModal
          onClose={() => setModalOpen(false)}
          onProposed={() => {
            void refresh();
            // Leave the modal open so the admin sees the success
            // banner, but they can dismiss via Close.
          }}
        />
      ) : null}
    </div>
  );
}

interface ReactivitySectionProps {
  testId: string;
  title: string;
  eyebrow: string;
  emptyLabel: string;
  rows: Reactivity[];
  onMutated: () => void;
}

function ReactivitySection({
  testId,
  title,
  eyebrow,
  emptyLabel,
  rows,
  onMutated,
}: ReactivitySectionProps) {
  return (
    <section
      data-testid={testId}
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {eyebrow}
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            borderBottom: "1px solid var(--wb-color-rule-line)",
            paddingBottom: 6,
          }}
        >
          {title}
        </h2>
      </header>
      {rows.length === 0 ? (
        <span
          data-testid={`${testId}-empty`}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          {emptyLabel}
        </span>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {rows.map((r) => (
            <ReactivityCard
              key={r.id}
              reactivity={r}
              onMutated={onMutated}
            />
          ))}
        </div>
      )}
    </section>
  );
}
