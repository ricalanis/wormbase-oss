"use client";
/**
 * FirstKnowingsTab — /research surface for un-confirmed worm-detected
 * phenomena (Demo-day P12).
 *
 * Altman Q1: "What does the worm know that the org's CDO doesn't, with
 * the ledger entry where it knew it first?" Each row is a phenomenon
 * the worm proposed (KPI gap, Domain gap, Process gap, Reactivity gap,
 * Person gap) whose corresponding ``*_confirmed`` ledger entry has not
 * yet landed.
 *
 * Filter chips:
 *   * phenomenon-kind — one or more of the five gap kinds
 *   * scope            — mine / team / company
 *   * recency          — 1h / 24h / 7d / all
 *
 * Click a row → /trace deep-link for the originating InfraEvent (the
 * chat_received row at ``referenced_in_seq``) plus a ±3 chatter context
 * inline. The deep-link mirrors W2.A10 TraceFilterBar conventions:
 * ``?surface=research&kind=chat_received&seq=<n>``. Per
 * CLAUDE.md ¶9, an empty list renders an honest "the worm has not flagged
 * anything the org hasn't confirmed yet" message — never a fixture.
 *
 * Visual chrome mirrors LessonsCard / ResearchOverviewCard: editorial
 * ledger feel, sepia rule lines, wb-mono labels, serif body. No icons,
 * no animations.
 */

import { useState } from "react";
import type {
  FirstKnowingPhenomenonKind,
  FirstKnowingRecency,
  FirstKnowingRow,
  FirstKnowingScope,
} from "../../lib/ledger-client.types";

// ---------------------------------------------------------------------------
// Static metadata
// ---------------------------------------------------------------------------

const KIND_LABELS: Record<FirstKnowingPhenomenonKind, string> = {
  kpi_gap: "KPI gap",
  domain_gap: "Domain gap",
  process_gap: "Process gap",
  reactivity_gap: "Reactivity gap",
  person_gap: "Person gap",
};

const KIND_ORDER: ReadonlyArray<FirstKnowingPhenomenonKind> = [
  "kpi_gap",
  "domain_gap",
  "process_gap",
  "reactivity_gap",
  "person_gap",
];

const SCOPE_LABELS: Record<FirstKnowingScope, string> = {
  mine: "Mine",
  team: "Team",
  company: "Company",
};

const SCOPE_ORDER: ReadonlyArray<FirstKnowingScope> = [
  "mine",
  "team",
  "company",
];

const RECENCY_LABELS: Record<FirstKnowingRecency, string> = {
  "1h": "1h",
  "24h": "24h",
  "7d": "7d",
  all: "all",
};

const RECENCY_ORDER: ReadonlyArray<FirstKnowingRecency> = [
  "1h",
  "24h",
  "7d",
  "all",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface FirstKnowingsTabProps {
  rows: FirstKnowingRow[];
}

export function FirstKnowingsTab({ rows }: FirstKnowingsTabProps) {
  const [kindChip, setKindChip] = useState<FirstKnowingPhenomenonKind | "all">(
    "all",
  );
  const [scopeChip, setScopeChip] = useState<FirstKnowingScope | "all">("all");
  const [recencyChip, setRecencyChip] = useState<FirstKnowingRecency>("all");
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);

  const now = Date.now();
  const filtered = rows.filter((r) => {
    if (kindChip !== "all" && r.kind !== kindChip) return false;
    if (scopeChip !== "all" && r.scope !== scopeChip) return false;
    if (recencyChip !== "all") {
      const hours =
        recencyChip === "1h" ? 1 : recencyChip === "24h" ? 24 : 24 * 7;
      const cutoff = now - hours * 3600 * 1000;
      if (new Date(r.firstDetectedTs).getTime() < cutoff) return false;
    }
    return true;
  });

  return (
    <section
      data-testid="first-knowings-tab"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderTop: "1px solid var(--wb-color-rule-line)",
        paddingTop: 24,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Institutional AI · Altman Q1
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-lg)",
            fontWeight: 500,
          }}
        >
          What the worm has flagged that the org has not yet confirmed
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-sm)",
            color: "var(--wb-color-hash-gray)",
            fontStyle: "italic",
          }}
        >
          The worm proposed it; no human has signed off yet. Each row links
          to the InfraEvent where it knew it first plus the chatter that
          surrounded it.
        </p>
      </header>

      <FilterChips
        kindChip={kindChip}
        scopeChip={scopeChip}
        recencyChip={recencyChip}
        onKind={setKindChip}
        onScope={setScopeChip}
        onRecency={setRecencyChip}
      />

      {filtered.length === 0 ? (
        <p
          data-testid="first-knowings-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            paddingTop: 12,
          }}
        >
          {rows.length === 0
            ? "No first-knowings yet — every phenomenon the worm proposes lands here until a human confirms it. Once a phenomenon-gap detector fires, it appears within one polling cycle."
            : "No first-knowings match the active filters. Loosen the chip selectors to see more."}
        </p>
      ) : (
        <ul
          data-testid="first-knowings-list"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {filtered.map((row) => (
            <FirstKnowingItem
              key={`${row.targetKind}::${row.refId}::${row.firstDetectedSeq}`}
              row={row}
              expanded={expandedSeq === row.firstDetectedSeq}
              onToggleExpand={() =>
                setExpandedSeq((cur) =>
                  cur === row.firstDetectedSeq ? null : row.firstDetectedSeq,
                )
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface FilterChipsProps {
  kindChip: FirstKnowingPhenomenonKind | "all";
  scopeChip: FirstKnowingScope | "all";
  recencyChip: FirstKnowingRecency;
  onKind: (v: FirstKnowingPhenomenonKind | "all") => void;
  onScope: (v: FirstKnowingScope | "all") => void;
  onRecency: (v: FirstKnowingRecency) => void;
}

function FilterChips({
  kindChip,
  scopeChip,
  recencyChip,
  onKind,
  onScope,
  onRecency,
}: FilterChipsProps) {
  return (
    <div
      data-testid="first-knowings-chips"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <ChipGroup
        groupTestId="chip-group-kind"
        label="kind"
        chips={[
          { value: "all", label: "all kinds", testId: "chip-kind-all" },
          ...KIND_ORDER.map((k) => ({
            value: k,
            label: KIND_LABELS[k],
            testId: `chip-kind-${k}`,
          })),
        ]}
        active={kindChip}
        onSelect={(v) => onKind(v as FirstKnowingPhenomenonKind | "all")}
      />
      <ChipGroup
        groupTestId="chip-group-scope"
        label="scope"
        chips={[
          { value: "all", label: "any scope", testId: "chip-scope-all" },
          ...SCOPE_ORDER.map((s) => ({
            value: s,
            label: SCOPE_LABELS[s],
            testId: `chip-scope-${s}`,
          })),
        ]}
        active={scopeChip}
        onSelect={(v) => onScope(v as FirstKnowingScope | "all")}
      />
      <ChipGroup
        groupTestId="chip-group-recency"
        label="first detected in last"
        chips={RECENCY_ORDER.map((r) => ({
          value: r,
          label: RECENCY_LABELS[r],
          testId: `chip-recency-${r}`,
        }))}
        active={recencyChip}
        onSelect={(v) => onRecency(v as FirstKnowingRecency)}
      />
    </div>
  );
}

interface ChipDescriptor {
  value: string;
  label: string;
  testId: string;
}

interface ChipGroupProps {
  groupTestId: string;
  label: string;
  chips: ChipDescriptor[];
  active: string;
  onSelect: (value: string) => void;
}

function ChipGroup({
  groupTestId,
  label,
  chips,
  active,
  onSelect,
}: ChipGroupProps) {
  return (
    <div
      data-testid={groupTestId}
      style={{
        display: "flex",
        gap: 6,
        flexWrap: "wrap",
        alignItems: "baseline",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
          minWidth: 84,
        }}
      >
        {label}
      </span>
      {chips.map((chip) => {
        const isActive = chip.value === active;
        return (
          <button
            key={chip.value}
            type="button"
            data-testid={chip.testId}
            data-active={isActive ? "true" : "false"}
            onClick={() => onSelect(chip.value)}
            style={{
              padding: "3px 10px",
              border: isActive
                ? "1px solid var(--wb-color-aged-ink)"
                : "1px solid var(--wb-color-paper-edge)",
              borderRadius: 0,
              background: isActive
                ? "var(--wb-color-aged-ink)"
                : "transparent",
              color: isActive
                ? "var(--wb-color-paper)"
                : "var(--wb-color-aged-ink)",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            {chip.label}
          </button>
        );
      })}
    </div>
  );
}

interface FirstKnowingItemProps {
  row: FirstKnowingRow;
  expanded: boolean;
  onToggleExpand: () => void;
}

function FirstKnowingItem({
  row,
  expanded,
  onToggleExpand,
}: FirstKnowingItemProps) {
  const traceHref = buildTraceHref(row);
  const wallclock = formatWallClock(row.firstDetectedTs);
  return (
    <li
      data-testid={`first-knowing-row-${row.firstDetectedSeq}`}
      style={{
        borderBottom: "1px solid var(--wb-color-paper-edge)",
        paddingBottom: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          gap: 12,
          alignItems: "baseline",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <span
          data-testid={`first-knowing-kind-${row.firstDetectedSeq}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper-edge)",
            padding: "2px 8px",
            borderRadius: 2,
          }}
        >
          {KIND_LABELS[row.kind]}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.06em",
          }}
        >
          seq @{row.firstDetectedSeq} · {wallclock} · scope {row.scope}
        </span>
      </header>

      <p
        data-testid={`first-knowing-summary-${row.firstDetectedSeq}`}
        style={{
          margin: "8px 0 0 0",
          fontFamily: "var(--wb-font-serif)",
          fontSize: "var(--wb-text-sm)",
          lineHeight: 1.5,
        }}
      >
        {row.summary}
      </p>

      <footer
        style={{
          display: "flex",
          gap: 10,
          alignItems: "baseline",
          marginTop: 8,
          flexWrap: "wrap",
        }}
      >
        <a
          href={traceHref}
          data-testid={`first-knowing-trace-link-${row.firstDetectedSeq}`}
          style={{
            fontFamily: "var(--wb-font-mono)",
            fontSize: 10,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--wb-color-botanical-green-deep)",
            textDecoration: "none",
            borderBottom: "1px solid var(--wb-color-botanical-green-deep)",
          }}
        >
          {row.referencedInSeq > 0
            ? `open InfraEvent · seq ${row.referencedInSeq}`
            : "open in /trace"}
        </a>
        {row.chatterContext.length > 0 ? (
          <button
            type="button"
            data-testid={`first-knowing-toggle-chatter-${row.firstDetectedSeq}`}
            onClick={onToggleExpand}
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 10,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--wb-color-aged-ink)",
              background: "transparent",
              border: "1px solid var(--wb-color-paper-edge)",
              borderRadius: 0,
              cursor: "pointer",
              padding: "2px 8px",
            }}
          >
            {expanded ? "hide" : "show"} chatter ±3
          </button>
        ) : null}
        {row.confidence !== null ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            confidence {(row.confidence ?? 0).toFixed(2)}
          </span>
        ) : null}
        {row.noveltyKey ? (
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {row.noveltyKey}
          </span>
        ) : null}
        <span
          className="wb-mono"
          style={{
            marginLeft: "auto",
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {row.receipt.hash}
        </span>
      </footer>

      {expanded && row.chatterContext.length > 0 ? (
        <ChatterContext context={row.chatterContext} parentSeq={row.firstDetectedSeq} />
      ) : null}
    </li>
  );
}

function ChatterContext({
  context,
  parentSeq,
}: {
  context: FirstKnowingRow["chatterContext"];
  parentSeq: number;
}) {
  return (
    <ul
      data-testid={`first-knowing-chatter-${parentSeq}`}
      style={{
        listStyle: "none",
        padding: "10px 12px",
        margin: "10px 0 0 0",
        background: "var(--wb-color-paper-edge)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {context.map((c) => (
        <li
          key={c.seq}
          data-testid={`chatter-row-${c.seq}`}
          data-anchor={c.isAnchor ? "true" : "false"}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-xs)",
            color: c.isAnchor
              ? "var(--wb-color-aged-ink)"
              : "var(--wb-color-hash-gray)",
            fontWeight: c.isAnchor ? 500 : 400,
            display: "flex",
            gap: 8,
            alignItems: "baseline",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.1em",
              minWidth: 60,
            }}
          >
            seq @{c.seq}
          </span>
          <span
            className="wb-mono"
            style={{
              fontSize: 9,
              color: "var(--wb-color-hash-gray)",
              minWidth: 80,
            }}
          >
            {c.senderPerson || "unknown"}
          </span>
          <span style={{ flex: 1 }}>{c.text || "(no text captured)"}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildTraceHref(row: FirstKnowingRow): string {
  const params = new URLSearchParams();
  params.set("surface", "research");
  if (row.referencedInSeq > 0) {
    params.set("kind", "chat_received");
    params.set("seq", String(row.referencedInSeq));
  } else {
    // Fall back to the propose row's seq — still navigable to /trace, the
    // viewer can scroll to the seq from the unfiltered stream.
    params.set("seq", String(row.firstDetectedSeq));
    params.set("kind", row.targetKind);
  }
  return `/trace?${params.toString()}`;
}

function formatWallClock(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch {
    return "—";
  }
}
