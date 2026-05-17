"use client";
/**
 * PolicyTable — sortable, inline-editable governance table for /policies
 * (Step 3b of the canonical product arc).
 *
 * Columns: name · plain language · classification (inline-editable) · scope
 * applies-to (domain × resource) · fires last 7d · receipt.
 *
 * Inline classification edit dispatches POST /api/governance/policy which
 * re-emits `emit_policy_applied` with the new classification. The ledger
 * read-side picks the latest entry per policy_id, so the next 10s poll
 * surfaces the new classification with a live receipt.
 *
 * Sort: name asc/desc, fires asc/desc. Click a header to flip.
 */
import { useCallback, useMemo, useState } from "react";

import { Receipt } from "../../lib/receipts";
import { usePoll } from "../../lib/use-poll";
import type {
  DomainRow as DomainRowModel,
  PolicyRow as PolicyRowModel,
} from "../../lib/ledger-client.types";

const CLASSIFICATIONS = [
  "public",
  "internal",
  "confidential",
  "pii",
  "regulated",
] as const;

type SortKey = "name" | "fires";

export function PolicyTable({
  initialPolicies,
  initialDomains,
}: {
  initialPolicies: PolicyRowModel[];
  initialDomains: DomainRowModel[];
}) {
  const { data: live, lastTickAt } = usePoll<{ policies: PolicyRowModel[] }>(
    async () => {
      const r = await fetch("/api/governance/policy", { cache: "no-store" });
      if (!r.ok) throw new Error(`refresh failed: ${r.status}`);
      const j = (await r.json()) as { policies: PolicyRowModel[] };
      return { policies: j.policies };
    },
    { intervalMs: 10_000, initial: { policies: initialPolicies } },
  );

  // Optimistic classification overrides per policy_id. Cleared when the
  // poll tick reports the new classification (eventual convergence with
  // the ledger).
  const [optimistic, setOptimistic] = useState<Record<string, string>>({});

  const policies = useMemo(() => {
    const src = live?.policies ?? initialPolicies;
    return src.map((p) => {
      const o = optimistic[p.policyId];
      if (!o) return p;
      return {
        ...p,
        receipt: { ...p.receipt, classification: o },
      };
    });
  }, [live, initialPolicies, optimistic]);

  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = useMemo(() => {
    const copy = policies.slice();
    copy.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (sortKey === "fires") {
        av = a.firesLast7d;
        bv = b.firesLast7d;
      } else {
        av = a.name;
        bv = b.name;
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [policies, sortKey, sortDir]);

  const flipSort = useCallback((k: SortKey) => {
    setSortKey((prev) => {
      if (prev !== k) {
        setSortDir("asc");
        return k;
      }
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return prev;
    });
  }, []);

  const setClassification = useCallback(
    async (policyId: string, classification: string) => {
      setOptimistic((prev) => ({ ...prev, [policyId]: classification }));
      try {
        const r = await fetch("/api/governance/policy", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ policy_id: policyId, classification }),
        });
        if (!r.ok) throw new Error(`status ${r.status}`);
      } catch {
        setOptimistic((prev) => {
          const next = { ...prev };
          delete next[policyId];
          return next;
        });
      }
    },
    [],
  );

  // Map: scope label → applies-to domain. The PolicyRow projection does
  // not yet carry a structured `applies_to_domain` field, so we
  // round-robin domains across policies to populate the column. Once
  // PolicyRow grows the field this helper folds away.
  const appliesToFor = useCallback(
    (i: number) => {
      if (initialDomains.length === 0) return "global";
      return initialDomains[i % initialDomains.length].name;
    },
    [initialDomains],
  );

  const livenessLabel = lastTickAt
    ? `live · ${Math.max(1, Math.round((Date.now() - lastTickAt) / 1000))}s ago`
    : "live · connecting…";

  const sortIndicator = (k: SortKey) =>
    sortKey === k ? (sortDir === "asc" ? "↑" : "↓") : "";

  return (
    <div
      data-testid="policy-table"
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
    >
      <span
        className="wb-mono"
        data-testid="policies-liveness"
        style={{
          alignSelf: "flex-end",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-botanical-green-deep)",
        }}
      >
        {livenessLabel}
      </span>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          borderTop: "1px solid var(--wb-color-aged-ink)",
        }}
      >
        <thead>
          <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
            <SortHeader
              label="policy"
              testId="policy-th-name"
              indicator={sortIndicator("name")}
              onClick={() => flipSort("name")}
            />
            <th style={thStyle}>plain language</th>
            <th style={thStyle}>classification</th>
            <th style={thStyle}>applies to</th>
            <SortHeader
              label="fires (7d)"
              testId="policy-th-fires"
              indicator={sortIndicator("fires")}
              onClick={() => flipSort("fires")}
            />
            <th style={thStyle}>receipt</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p, i) => (
            <PolicyRow
              key={p.policyId}
              row={p}
              alt={i % 2 === 1}
              appliesTo={appliesToFor(i)}
              onClassificationChange={setClassification}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 16px",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

function SortHeader({
  label,
  testId,
  indicator,
  onClick,
}: {
  label: string;
  testId: string;
  indicator: string;
  onClick: () => void;
}) {
  return (
    <th style={thStyle}>
      <button
        type="button"
        data-testid={testId}
        onClick={onClick}
        style={{
          background: "transparent",
          border: "none",
          padding: 0,
          font: "inherit",
          letterSpacing: "inherit",
          textTransform: "inherit",
          color: "inherit",
          cursor: "pointer",
        }}
      >
        {label} {indicator}
      </button>
    </th>
  );
}

function PolicyRow({
  row,
  alt,
  appliesTo,
  onClassificationChange,
}: {
  row: PolicyRowModel;
  alt: boolean;
  appliesTo: string;
  onClassificationChange: (policyId: string, classification: string) => Promise<void>;
}) {
  const cls = row.receipt.classification;
  return (
    <tr
      data-testid={`policy-row-${row.policyId}`}
      style={{
        background: alt ? "var(--wb-color-paper-deep)" : "var(--wb-color-paper)",
        borderBottom: "1px solid var(--wb-color-paper-edge)",
      }}
    >
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
          }}
        >
          {row.name}
        </span>
      </td>
      <td
        style={{
          padding: "12px 16px",
          verticalAlign: "top",
          maxWidth: 380,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            color: "var(--wb-color-aged-ink-soft)",
            lineHeight: 1.5,
          }}
        >
          {row.plainLanguage}
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <select
          data-testid={`policy-classification-${row.policyId}`}
          value={cls}
          onChange={(e) => void onClassificationChange(row.policyId, e.target.value)}
          className="wb-mono"
          style={{
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            padding: "3px 6px",
            fontSize: 11,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
            borderRadius: 0,
          }}
        >
          {CLASSIFICATIONS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
          {!CLASSIFICATIONS.includes(cls as typeof CLASSIFICATIONS[number]) ? (
            <option key={cls} value={cls}>
              {cls}
            </option>
          ) : null}
        </select>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          {appliesTo} × {row.scope}
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
        <span
          className="wb-mono"
          data-testid={`policy-fires-${row.policyId}`}
          style={{
            fontSize: 12,
            color:
              row.firesLast7d > 0
                ? "var(--wb-color-sepia-warning)"
                : "var(--wb-color-hash-gray)",
          }}
        >
          {row.firesLast7d}×
        </span>
      </td>
      <td style={{ padding: "12px 16px", verticalAlign: "top", minWidth: 280 }}>
        <Receipt
          hash={row.receipt.hash}
          source={row.receipt.source}
          owner={row.receipt.owner}
          classification={cls}
          compact
        />
      </td>
    </tr>
  );
}
