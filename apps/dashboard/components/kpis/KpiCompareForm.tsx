"use client";
/**
 * KpiCompareForm — picks two replay timestamps and submits to the
 * server-rendered ``/kpis/compare`` page via plain GET. No JS framework
 * needed; the form action is the page itself, search params drive the
 * RSC pass.
 */
import { useState } from "react";

interface Props {
  kpiId: string;
  initialT1: string | null;
  initialT2: string | null;
  /** Available KPI ids. Empty → render a free-text id input. */
  kpiIds?: string[];
}

const ROW_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const LABEL_STYLE: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const INPUT_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  padding: "6px 8px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper-deep)",
  color: "var(--wb-color-aged-ink)",
};

const BUTTON_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  padding: "8px 16px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-botanical-green)",
  color: "var(--wb-color-aged-ink)",
  cursor: "pointer",
};

/**
 * Convert an ISO-8601 string to the format ``<input type="datetime-local">``
 * accepts (``YYYY-MM-DDTHH:MM``). Returns ``""`` for null/invalid values.
 */
function isoToLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  );
}

export function KpiCompareForm({ kpiId, initialT1, initialT2, kpiIds }: Props) {
  const [id, setId] = useState(kpiId);
  const [t1, setT1] = useState(isoToLocal(initialT1));
  const [t2, setT2] = useState(isoToLocal(initialT2));

  // Submit via GET so the page re-renders with the new search params and
  // the server-side replay runs against ledger truth.
  return (
    <form
      data-testid="kpi-compare-form"
      method="GET"
      action="/kpis/compare"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr auto",
        gap: 12,
        alignItems: "end",
      }}
    >
      <div style={ROW_STYLE}>
        <label htmlFor="kpi-id" style={LABEL_STYLE}>
          kpi id
        </label>
        {kpiIds && kpiIds.length > 0 ? (
          <select
            id="kpi-id"
            name="id"
            data-testid="kpi-compare-id-select"
            style={INPUT_STYLE}
            value={id}
            onChange={(e) => setId(e.target.value)}
          >
            {kpiIds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
            {kpiIds.includes(id) ? null : <option value={id}>{id}</option>}
          </select>
        ) : (
          <input
            id="kpi-id"
            name="id"
            data-testid="kpi-compare-id-input"
            style={INPUT_STYLE}
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="revenue.q3"
          />
        )}
      </div>
      <div style={ROW_STYLE}>
        <label htmlFor="t1" style={LABEL_STYLE}>
          replay A · until_ts
        </label>
        <input
          id="t1"
          name="t1"
          type="datetime-local"
          data-testid="kpi-compare-t1-input"
          style={INPUT_STYLE}
          value={t1}
          onChange={(e) => setT1(e.target.value)}
        />
      </div>
      <div style={ROW_STYLE}>
        <label htmlFor="t2" style={LABEL_STYLE}>
          replay B · until_ts
        </label>
        <input
          id="t2"
          name="t2"
          type="datetime-local"
          data-testid="kpi-compare-t2-input"
          style={INPUT_STYLE}
          value={t2}
          onChange={(e) => setT2(e.target.value)}
        />
      </div>
      <button type="submit" data-testid="kpi-compare-submit" style={BUTTON_STYLE}>
        Replay
      </button>
    </form>
  );
}
