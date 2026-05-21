"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { Card } from "@wormbase/design";

type View = "conv" | "sources" | "loops" | "compound";

const TABS: { id: View; label: string; eyebrow: string }[] = [
  { id: "conv", label: "Conversation", eyebrow: "Plate I" },
  { id: "sources", label: "Sources & Lake", eyebrow: "Plate II" },
  { id: "loops", label: "Agent Loops · L1–L8", eyebrow: "Plate III" },
  { id: "compound", label: "Compounding Knowledge", eyebrow: "Plate IV" },
];

export function DemoDashboard() {
  const [view, setView] = useState<View>("conv");

  return (
    <>
      <nav
        role="tablist"
        style={{
          display: "flex",
          gap: 0,
          borderBottom: "1px solid var(--wb-color-rule-line)",
          marginBottom: 8,
        }}
      >
        {TABS.map((tab) => {
          const active = tab.id === view;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={active}
              onClick={() => setView(tab.id)}
              style={{
                background: "transparent",
                border: "none",
                borderBottom: active
                  ? "2px solid var(--wb-color-botanical-green)"
                  : "2px solid transparent",
                color: active
                  ? "var(--wb-color-aged-ink)"
                  : "var(--wb-color-hash-gray)",
                cursor: "pointer",
                padding: "14px 18px",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 11,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                fontWeight: active ? 600 : 400,
                transition: "color 0.15s",
              }}
            >
              <span style={{ marginRight: 10, color: "var(--wb-color-hash-gray)" }}>
                {tab.eyebrow}
              </span>
              {tab.label}
            </button>
          );
        })}
      </nav>

      {view === "conv" && <ConversationView />}
      {view === "sources" && <SourcesView />}
      {view === "loops" && <LoopsView />}
      {view === "compound" && <CompoundingView />}
    </>
  );
}

// ============================================================================
// shared bits
// ============================================================================

const eyebrow: CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 10,
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const serifTitle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontWeight: 500,
  margin: 0,
};

function PlateHead({
  plate,
  title,
  blurb,
}: {
  plate: string;
  title: string;
  blurb: string;
}) {
  return (
    <header style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 18 }}>
      <span style={eyebrow}>{plate}</span>
      <h1 style={{ ...serifTitle, fontSize: 32, letterSpacing: "-0.015em" }}>{title}</h1>
      <p
        style={{
          margin: 0,
          color: "var(--wb-color-aged-ink-soft)",
          maxWidth: "82ch",
          fontSize: 14.5,
          lineHeight: 1.55,
        }}
      >
        {blurb}
      </p>
    </header>
  );
}

function Stat({
  n,
  label,
  delta,
  tone = "good",
}: {
  n: ReactNode;
  label: string;
  delta?: string;
  tone?: "good" | "warn" | "bad" | "neutral";
}) {
  const deltaColor =
    tone === "good"
      ? "var(--wb-color-botanical-green)"
      : tone === "warn"
      ? "var(--wb-color-sepia-warning)"
      : tone === "bad"
      ? "var(--wb-color-sepia-warning-deep)"
      : "var(--wb-color-hash-gray)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 42,
          lineHeight: 1,
          letterSpacing: "-0.02em",
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {n}
      </div>
      {delta && (
        <div
          style={{
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            color: deltaColor,
            letterSpacing: "0.04em",
          }}
        >
          {delta}
        </div>
      )}
      <div
        style={{
          ...eyebrow,
          marginTop: 8,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </div>
    </div>
  );
}

const PILL_TONES: Record<string, [string, string]> = {
  good: ["var(--wb-color-botanical-green)", "var(--wb-color-botanical-green-soft)"],
  warn: ["var(--wb-color-sepia-warning)", "var(--wb-color-sepia-warning-soft)"],
  bad: ["var(--wb-color-sepia-warning-deep)", "var(--wb-color-sepia-warning-soft)"],
  accent: ["var(--wb-color-aged-ink)", "var(--wb-color-paper-edge)"],
  neutral: ["var(--wb-color-aged-ink-soft)", "var(--wb-color-paper-deep)"],
};

function Pill({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof PILL_TONES;
  children: ReactNode;
}) {
  const [color, bg] = PILL_TONES[tone];
  return (
    <span
      style={{
        display: "inline-block",
        fontFamily: "var(--wb-font-mono)",
        fontSize: 10,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        padding: "3px 8px",
        border: `1px solid ${color}`,
        background: bg,
        color,
        borderRadius: 999,
      }}
    >
      {children}
    </span>
  );
}

// inline SVG line chart
function LineChart({
  series,
  height = 200,
  fill = false,
  labels,
}: {
  series: { label: string; data: number[]; color: string; dashed?: boolean }[];
  height?: number;
  fill?: boolean;
  labels?: string[];
}) {
  const w = 600;
  const h = height;
  const padL = 32;
  const padR = 12;
  const padT = 12;
  const padB = 22;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  const min = 0;
  const n = series[0]?.data.length ?? 0;
  const sx = (i: number) => padL + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const sy = (v: number) => padT + innerH - ((v - min) / (max - min || 1)) * innerH;

  const yTicks = 4;
  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
      >
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const y = padT + (innerH * i) / yTicks;
          return (
            <line
              key={i}
              x1={padL}
              x2={w - padR}
              y1={y}
              y2={y}
              stroke="var(--wb-color-paper-edge)"
              strokeWidth={1}
            />
          );
        })}
        {series.map((s, si) => {
          const pts = s.data.map((v, i) => `${sx(i)},${sy(v)}`).join(" ");
          const area = `M ${sx(0)},${sy(0)} L ${s.data
            .map((v, i) => `${sx(i)},${sy(v)}`)
            .join(" L ")} L ${sx(n - 1)},${sy(0)} Z`;
          return (
            <g key={si}>
              {fill && si === 0 && (
                <path d={area} fill={s.color} fillOpacity={0.12} stroke="none" />
              )}
              <polyline
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dashed ? "4 4" : undefined}
                points={pts}
              />
            </g>
          );
        })}
        {labels && (
          <>
            {labels.map((lab, i) => {
              if (n > 8 && i % 2 !== 0 && i !== n - 1) return null;
              return (
                <text
                  key={i}
                  x={sx(i)}
                  y={h - 6}
                  textAnchor="middle"
                  fontFamily="var(--wb-font-mono)"
                  fontSize="9"
                  fill="var(--wb-color-hash-gray)"
                  letterSpacing="0.06em"
                >
                  {lab}
                </text>
              );
            })}
          </>
        )}
        {[0, max].map((v, i) => (
          <text
            key={i}
            x={padL - 6}
            y={sy(v) + 3}
            textAnchor="end"
            fontFamily="var(--wb-font-mono)"
            fontSize="9"
            fill="var(--wb-color-hash-gray)"
          >
            {v}
          </text>
        ))}
      </svg>
      {series.length > 1 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 14,
            marginTop: 6,
            fontFamily: "var(--wb-font-mono)",
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {series.map((s) => (
            <span
              key={s.label}
              style={{ display: "inline-flex", gap: 6, alignItems: "center" }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 2,
                  background: s.color,
                  borderTop: s.dashed
                    ? `2px dashed ${s.color}`
                    : `2px solid ${s.color}`,
                }}
              />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function HBarChart({
  rows,
  color = "var(--wb-color-botanical-green)",
}: {
  rows: { label: string; value: number }[];
  color?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map((r) => (
        <div key={r.label}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: "var(--wb-color-aged-ink-soft)",
              marginBottom: 3,
            }}
          >
            <span>{r.label}</span>
            <span style={{ color: "var(--wb-color-aged-ink)" }}>{r.value}</span>
          </div>
          <div
            style={{
              height: 6,
              background: "var(--wb-color-paper-edge)",
              borderRadius: 0,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${(r.value / max) * 100}%`,
                height: "100%",
                background: color,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function StackedBars({
  labels,
  series,
  height = 220,
}: {
  labels: string[];
  series: { label: string; data: number[]; color: string }[];
  height?: number;
}) {
  const w = 600;
  const padL = 32;
  const padR = 12;
  const padT = 12;
  const padB = 22;
  const innerW = w - padL - padR;
  const innerH = height - padT - padB;
  const totals = labels.map((_, i) =>
    series.reduce((acc, s) => acc + (s.data[i] ?? 0), 0)
  );
  const max = Math.max(...totals, 1);
  const barW = innerW / labels.length;
  const sy = (v: number) => padT + innerH - (v / max) * innerH;

  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${height}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
      >
        {[0, 1, 2, 3, 4].map((i) => {
          const y = padT + (innerH * i) / 4;
          return (
            <line
              key={i}
              x1={padL}
              x2={w - padR}
              y1={y}
              y2={y}
              stroke="var(--wb-color-paper-edge)"
            />
          );
        })}
        {labels.map((lab, i) => {
          let acc = 0;
          return (
            <g key={lab}>
              {series.map((s) => {
                const v = s.data[i] ?? 0;
                const y0 = sy(acc + v);
                const y1 = sy(acc);
                acc += v;
                return (
                  <rect
                    key={s.label}
                    x={padL + i * barW + 4}
                    width={barW - 8}
                    y={y0}
                    height={Math.max(0, y1 - y0)}
                    fill={s.color}
                  />
                );
              })}
              <text
                x={padL + i * barW + barW / 2}
                y={height - 6}
                textAnchor="middle"
                fontFamily="var(--wb-font-mono)"
                fontSize="9"
                fill="var(--wb-color-hash-gray)"
              >
                {lab}
              </text>
            </g>
          );
        })}
      </svg>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          marginTop: 6,
          fontFamily: "var(--wb-font-mono)",
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        {series.map((s) => (
          <span key={s.label} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                background: s.color,
              }}
            />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function Donut({
  segments,
}: {
  segments: { label: string; value: number; color: string }[];
}) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  const size = 120;
  const stroke = 22;
  const r = (size - stroke) / 2;
  const c = size / 2;
  let acc = 0;
  const circumference = 2 * Math.PI * r;
  return (
    <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={c}
          cy={c}
          r={r}
          stroke="var(--wb-color-paper-edge)"
          strokeWidth={stroke}
          fill="none"
        />
        {segments.map((s) => {
          const frac = s.value / total;
          const dash = frac * circumference;
          const offset = (acc / total) * circumference;
          acc += s.value;
          return (
            <circle
              key={s.label}
              cx={c}
              cy={c}
              r={r}
              stroke={s.color}
              strokeWidth={stroke}
              fill="none"
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${c} ${c})`}
            />
          );
        })}
      </svg>
      <ul
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {segments.map((s) => (
          <li
            key={s.label}
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: "var(--wb-color-aged-ink-soft)",
            }}
          >
            <span
              style={{ display: "inline-block", width: 10, height: 10, background: s.color }}
            />
            <span style={{ minWidth: 80 }}>{s.label}</span>
            <span style={{ color: "var(--wb-color-aged-ink)" }}>{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Sparkline({ data, color = "var(--wb-color-botanical-green)" }: { data: number[]; color?: string }) {
  const w = 100;
  const h = 22;
  const max = Math.max(...data, 1);
  const min = 0;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / (max - min || 1)) * h;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: "100%", height: h }}>
      <polyline fill="none" stroke={color} strokeWidth={1.5} points={pts} />
    </svg>
  );
}

const DAYS = [
  "Apr 28",
  "Apr 29",
  "Apr 30",
  "May 1",
  "May 2",
  "May 3",
  "May 4",
  "May 5",
  "May 6",
  "May 7",
  "May 8",
  "May 9",
  "May 10",
  "May 11",
];

// ============================================================================
// CONVERSATION
// ============================================================================

function ConversationView() {
  return (
    <>
      <PlateHead
        plate="Plate I · conversation surface · last 14 days"
        title="Conversation insights"
        blurb="Threads, mentions, decisions, recurring questions. The worm reads everything in connected channels and writes structured ledger entries — without ever quoting a person back to them out of context."
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 18,
        }}
      >
        <Card eyebrow="P1 · ledger"><Stat n="1,284" label="Messages observed" delta="▲ 14% wow" /></Card>
        <Card eyebrow="P1 · extracted"><Stat n="42" label="Decisions captured" delta="▲ 9 since Mon" /></Card>
        <Card eyebrow="P1 · clusters"><Stat n="11" label="Active topic clusters" delta="▲ 2 new topics" /></Card>
        <Card eyebrow="P1 · queue"><Stat n="7" label="Recurring questions" delta="▲ pending review" tone="warn" /></Card>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 18,
        }}
      >
        <Card eyebrow="P1.a · timeseries" title="Decisions extracted · rolling 14 days">
          <LineChart
            labels={DAYS}
            fill
            series={[
              { label: "decisions", color: "var(--wb-color-botanical-green-deep)", data: [1,2,3,2,4,3,5,3,4,6,5,3,4,7] },
              { label: "recurring qs", color: "var(--wb-color-sepia-warning)", dashed: true, data: [0,0,1,2,1,2,3,1,2,2,3,4,3,7] },
              { label: "topics added", color: "var(--wb-color-aged-ink-soft)", data: [0,0,1,0,1,0,0,1,0,1,1,0,1,2] },
            ]}
          />
        </Card>
        <Card eyebrow="P1.b · clusters" title="Topics in conversation">
          <HBarChart
            rows={[
              { label: "billing & pricing", value: 184 },
              { label: "hiring", value: 138 },
              { label: "customer support", value: 121 },
              { label: "product roadmap", value: 98 },
              { label: "infra / incidents", value: 86 },
              { label: "data quality", value: 64 },
              { label: "partnerships", value: 52 },
              { label: "metrics & KPIs", value: 48 },
            ]}
          />
        </Card>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 18,
        }}
      >
        <Card eyebrow="P1.c · decisions" title="Recent decisions captured from threads">
          <DecisionTable />
        </Card>
        <Card eyebrow="P1.d · recurring" title="Questions asked more than 3×">
          <RecurringQuestions />
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Card eyebrow="P1.e · cadence" title="Channel activity · messages per hour">
          <StackedBars
            labels={["08","10","12","14","16","18","20"]}
            series={[
              { label: "#product-leads", color: "var(--wb-color-botanical-green-deep)", data: [4,8,12,16,14,9,3] },
              { label: "#eng-platform", color: "var(--wb-color-botanical-green)", data: [2,6,10,14,18,12,6] },
              { label: "#finance-leads", color: "var(--wb-color-sepia-warning)", data: [1,3,5,7,5,2,1] },
            ]}
          />
        </Card>
        <Card eyebrow="P1.f · participation" title="Who's asking, who's answering">
          <StackedBars
            labels={["maya","alex","priya","kenji","jordan","sam"]}
            series={[
              { label: "asks", color: "var(--wb-color-sepia-warning)", data: [22,18,14,9,12,5] },
              { label: "answers", color: "var(--wb-color-botanical-green-deep)", data: [14,28,9,32,11,7] },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

function DecisionTable() {
  const rows = [
    { d: "Ship payments before onboarding revamp.", note: "priority sequenced for Q2", ch: "#product-leads", by: "maya", when: "2h ago" },
    { d: "Adopt NRR = revenue from cohort, ex one-time fees.", note: null, ch: "#finance-leads", by: "alex", when: "1d" },
    { d: "Move from Sentry → OpenObserve for log search.", note: null, ch: "#eng-platform", by: "kenji", when: "2d" },
    { d: "Hire 2 SDRs in Q2; one EU, one US.", note: null, ch: "#go-to-market", by: "priya", when: "3d" },
    { d: "Pause partnership with Acme until renewal terms clarified.", note: null, ch: "#partnerships", by: "maya", when: "4d" },
    { d: "Push annual planning offsite to first week of June.", note: null, ch: "#leadership", by: "alex", when: "5d" },
    { d: "All new tables must declare a domain at creation.", note: null, ch: "#data", by: "kenji", when: "6d" },
  ];
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
      <thead>
        <tr style={{ borderBottom: "1px solid var(--wb-color-rule-line)" }}>
          {["Decision","Channel","By","When"].map((h, i) => (
            <th
              key={h}
              style={{
                textAlign: i === 3 ? "right" : "left",
                padding: "8px 10px 8px 0",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 10,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
                fontWeight: 500,
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderBottom: "1px solid var(--wb-color-paper-edge)" }}>
            <td style={{ padding: "12px 10px 12px 0" }}>
              <span style={{ color: "var(--wb-color-aged-ink)", fontWeight: 500 }}>{r.d}</span>
              {r.note && (
                <span style={{ color: "var(--wb-color-hash-gray)", fontFamily: "var(--wb-font-mono)", fontSize: 11, marginLeft: 6 }}>
                  — {r.note}
                </span>
              )}
            </td>
            <td style={{ padding: "12px 10px 12px 0", fontFamily: "var(--wb-font-mono)", fontSize: 12, color: "var(--wb-color-aged-ink-soft)" }}>{r.ch}</td>
            <td style={{ padding: "12px 10px 12px 0", color: "var(--wb-color-aged-ink-soft)" }}>{r.by}</td>
            <td style={{ padding: "12px 10px 12px 0", textAlign: "right", color: "var(--wb-color-hash-gray)", fontFamily: "var(--wb-font-mono)", fontSize: 12 }}>{r.when}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecurringQuestions() {
  const rows: { q: string; meta: string; tone: keyof typeof PILL_TONES; tag: string }[] = [
    { q: '"What\'s our current ARR?"', meta: "asked 9× by 4 people · last in #finance", tone: "accent", tag: "draft answer" },
    { q: '"Who owns billing?"', meta: "asked 6× · ambiguous owners", tone: "warn", tag: "needs owner" },
    { q: '"How do we count active users?"', meta: "asked 5× · definition unconfirmed", tone: "warn", tag: "propose KPI" },
    { q: '"Where does Stripe data land?"', meta: "asked 4× · L3 has a lineage hint", tone: "good", tag: "resolved" },
    { q: '"Did churn spike in Q3?"', meta: "asked 4× · needs cohort cut", tone: "accent", tag: "draft answer" },
  ];
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {rows.map((r, i) => (
        <li
          key={i}
          style={{
            padding: "10px 0",
            borderBottom: i < rows.length - 1 ? "1px solid var(--wb-color-paper-edge)" : "none",
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
            alignItems: "start",
          }}
        >
          <div>
            <div style={{ color: "var(--wb-color-aged-ink)", fontWeight: 500, fontSize: 13.5 }}>{r.q}</div>
            <div style={{ color: "var(--wb-color-hash-gray)", fontFamily: "var(--wb-font-mono)", fontSize: 11, marginTop: 2 }}>{r.meta}</div>
          </div>
          <Pill tone={r.tone}>{r.tag}</Pill>
        </li>
      ))}
    </ul>
  );
}

// ============================================================================
// SOURCES & LAKE
// ============================================================================

function SourcesView() {
  return (
    <>
      <PlateHead
        plate="Plate II · lake surfaces · live"
        title="Sources & data lake"
        blurb="Four equal source families — external, filedrop, conversation, evidence. Medallion freshness, schema drift, classification, lineage. Every table the worm watches is hash-chained back to the ledger."
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
        <Card eyebrow="P2 · connect"><Stat n="9" label="Sources connected" delta="▲ 2 connected this wk" /></Card>
        <Card eyebrow="P2 · medallion"><Stat n="78" label="Tables tracked · bronze→gold" delta="▲ 14 since Mon" /></Card>
        <Card eyebrow="P2 · L6"><Stat n="12" label="PII / regulated columns" delta="▲ 3 flagged" tone="warn" /></Card>
        <Card eyebrow="P2 · L2 drift"><Stat n="4" label="Drift events · 14d" delta="▲ pending review" tone="bad" /></Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
        <Card eyebrow="P2.a · surfaces" title="Connected sources · freshness, classification, lineage">
          <SourceList />
        </Card>
        <Card eyebrow="P2.b · medallion" title="Lake freshness · bronze / silver / gold">
          <MedallionPanel />
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Card eyebrow="P2.c · L2 drift" title="Schema drift events · 14d">
          <StackedBars
            labels={DAYS}
            height={180}
            series={[
              { label: "drift events", color: "var(--wb-color-sepia-warning)", data: [0,0,1,0,0,2,0,0,1,0,0,0,3,1] },
              { label: "resolved", color: "var(--wb-color-botanical-green)", data: [0,0,1,0,0,2,0,0,1,0,0,0,2,1] },
            ]}
          />
        </Card>
        <Card eyebrow="P2.d · L3 lineage" title="Lineage edges discovered · cumulative">
          <LineChart
            labels={DAYS}
            fill
            series={[
              { label: "edges", color: "var(--wb-color-botanical-green-deep)", data: [12,28,46,72,104,124,148,176,204,238,266,288,304,328] },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

function SourceList() {
  const rows = [
    { ic: "PG", name: "prod-postgres", pill: ["good", "healthy"] as const, meta: "external · 24 tables · domain=core", l5: "L5: 92%", l6: "L6: 4 PII", fresh: "fresh · 12s", stale: false },
    { ic: "SF", name: "snowflake-analytics", pill: ["good", "healthy"] as const, meta: "external · 31 tables · domain=analytics", l5: "L5: 88%", l6: "L6: 2 PII", fresh: "fresh · 1m", stale: false },
    { ic: "$", name: "stripe", pill: ["good", "healthy"] as const, meta: "external · 8 endpoints · domain=billing", l5: "L5: 100%", l6: "L6: 3 PII", fresh: "fresh · 6m", stale: false },
    { ic: "N", name: "notion (MCP)", pill: ["good", "healthy"] as const, meta: "external · 4 dbs · domain=ops", l5: "L5: —", l6: "L6: 1 PII", fresh: "fresh · 28s", stale: false },
    { ic: "HS", name: "hubspot (MCP)", pill: ["warn", "drift"] as const, meta: "external · 5 objects · domain=gtm", l5: "L5: 84%", l6: "L6: 2 PII", fresh: "8h ago", stale: true },
    { ic: "CSV", name: "q1-marketing-spend.csv", pill: ["accent", "filedrop"] as const, meta: "filedrop · 1 file · dropped in #cmo", l5: "L5: 76%", l6: "L6: —", fresh: "profiled · 3d", stale: false },
    { ic: "S3", name: "~/.wormbase/lake", pill: ["good", "local"] as const, meta: "default · bronze/silver/gold · domain=lake", l5: "L5: 94%", l6: "L6: —", fresh: "fresh · 4s", stale: false },
    { ic: "LN", name: "linear (MCP)", pill: ["good", "healthy"] as const, meta: "external · 3 teams · domain=eng", l5: "L5: —", l6: "L6: —", fresh: "fresh · 1m", stale: false },
    { ic: "SL", name: "slack", pill: ["good", "healthy"] as const, meta: "conversation · 14 channels · domain=org", l5: "L5: —", l6: "L6: —", fresh: "live", stale: false },
  ];
  return (
    <div>
      {rows.map((r, i) => (
        <div
          key={r.name}
          style={{
            display: "grid",
            gridTemplateColumns: "32px 1fr 60px 70px 110px",
            gap: 14,
            alignItems: "center",
            padding: "12px 0",
            borderBottom: i < rows.length - 1 ? "1px solid var(--wb-color-paper-edge)" : "none",
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              display: "grid",
              placeItems: "center",
              border: "1px solid var(--wb-color-rule-line)",
              background: "var(--wb-color-paper-deep)",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 10,
              color: "var(--wb-color-botanical-green-deep)",
              fontWeight: 600,
            }}
          >
            {r.ic}
          </div>
          <div>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ color: "var(--wb-color-aged-ink)", fontWeight: 500 }}>{r.name}</span>
              <Pill tone={r.pill[0]}>{r.pill[1]}</Pill>
            </div>
            <div style={{ fontFamily: "var(--wb-font-mono)", fontSize: 11, color: "var(--wb-color-hash-gray)", marginTop: 2 }}>{r.meta}</div>
          </div>
          <div style={{ fontFamily: "var(--wb-font-mono)", fontSize: 11, color: "var(--wb-color-hash-gray)" }}>{r.l5}</div>
          <div style={{ fontFamily: "var(--wb-font-mono)", fontSize: 11, color: "var(--wb-color-hash-gray)" }}>{r.l6}</div>
          <div
            style={{
              textAlign: "right",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              color: r.stale ? "var(--wb-color-sepia-warning)" : "var(--wb-color-botanical-green)",
            }}
          >
            {r.fresh}
          </div>
        </div>
      ))}
    </div>
  );
}

function MedallionPanel() {
  const rows: { label: string; meta: string; pct: number; color: string }[] = [
    { label: "bronze", meta: "47 tables · <1m", pct: 96, color: "#B48A5D" },
    { label: "silver", meta: "23 tables · 6m avg", pct: 82, color: "#A5A5A5" },
    { label: "gold", meta: "8 tables · 14m avg", pct: 64, color: "#C49A3E" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {rows.map((r) => (
          <div key={r.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 11,
                marginBottom: 4,
              }}
            >
              <span style={{ color: "var(--wb-color-aged-ink-soft)", textTransform: "uppercase", letterSpacing: "0.14em" }}>{r.label}</span>
              <span style={{ color: "var(--wb-color-aged-ink)" }}>{r.meta}</span>
            </div>
            <div
              style={{
                height: 8,
                background: "var(--wb-color-paper-edge)",
                overflow: "hidden",
              }}
            >
              <div style={{ width: `${r.pct}%`, height: "100%", background: r.color }} />
            </div>
          </div>
        ))}
      </div>
      <div>
        <div style={{ ...eyebrow, marginBottom: 8 }}>L6 classification</div>
        <Donut
          segments={[
            { label: "public", value: 42, color: "var(--wb-color-hash-gray)" },
            { label: "internal", value: 28, color: "var(--wb-color-botanical-green)" },
            { label: "confidential", value: 12, color: "var(--wb-color-aged-ink-soft)" },
            { label: "PII", value: 9, color: "var(--wb-color-sepia-warning)" },
            { label: "regulated", value: 3, color: "var(--wb-color-sepia-warning-deep)" },
          ]}
        />
      </div>
    </div>
  );
}

// ============================================================================
// LOOPS
// ============================================================================

function LoopsView() {
  return (
    <>
      <PlateHead
        plate="Plate III · lake-side loops · L1–L8"
        title="Agent tending activity"
        blurb="Eight loops, running concurrently since t=0 of install. Each one writes confirmed-state outputs other loops chain off. The funnel below shows how proposals become hash-chained ledger entries."
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
        <Card eyebrow="P3 · ledger"><Stat n="8,412" label="Loop entries · 14d" delta="▲ 1,204 / 24h" /></Card>
        <Card eyebrow="P3 · chains"><Stat n="36" label="Cross-axis chains fired" delta="▲ 8 this wk" /></Card>
        <Card eyebrow="P3 · confirm"><Stat n="84%" label="Proposal → confirm rate" delta="▲ 6 pts" /></Card>
        <Card eyebrow="P3 · throughput"><Stat n="142/h" label="Hash-chain writes" delta="steady" tone="neutral" /></Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
        <Card eyebrow="P3.a · per loop" title="Activity by loop · last 7 days">
          <StackedBars
            labels={DAYS.slice(-7)}
            height={240}
            series={[
              { label: "L1", color: "#2C5F3E", data: [4,6,5,8,7,9,10] },
              { label: "L2", color: "#B8603C", data: [1,0,2,3,1,4,3] },
              { label: "L3", color: "#6AA9C9", data: [12,18,14,22,18,24,28] },
              { label: "L4", color: "#8E4525", data: [3,4,3,5,4,4,4] },
              { label: "L5", color: "#B58CD1", data: [28,34,42,40,52,60,68] },
              { label: "L6", color: "#A8A49A", data: [10,14,18,16,20,16,12] },
              { label: "L7", color: "#1F4A2E", data: [48,52,60,58,72,76,80] },
              { label: "L8", color: "#C49A3E", data: [6,5,8,9,10,9,11] },
            ]}
          />
        </Card>
        <Card eyebrow="P3.b · funnel" title="Proposal → execute → verify → resolve">
          <Funnel />
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Card eyebrow="P3.c · per loop" title="L1–L8 · activity & 24h trend">
          <LoopRows />
        </Card>
        <Card eyebrow="P3.d · chains" title="Cross-axis chains fired">
          <ChainsTable />
        </Card>
      </div>
    </>
  );
}

function Funnel() {
  const steps = [
    { label: "proposed", n: 214, drop: "since install" },
    { label: "executed", n: 198, drop: "−16" },
    { label: "verified", n: 189, drop: "−9" },
    { label: "resolved", n: 180, drop: "−9 / 84%" },
  ];
  return (
    <>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          border: "1px solid var(--wb-color-rule-line)",
        }}
      >
        {steps.map((s, i) => (
          <div
            key={s.label}
            style={{
              padding: "14px 14px 16px",
              borderRight: i < 3 ? "1px solid var(--wb-color-rule-line)" : "none",
              background: "var(--wb-color-paper-deep)",
            }}
          >
            <div style={{ ...eyebrow, marginBottom: 6 }}>{s.label}</div>
            <div
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 28,
                lineHeight: 1.1,
                color: "var(--wb-color-aged-ink)",
              }}
            >
              {s.n}
            </div>
            <div style={{ fontFamily: "var(--wb-font-mono)", fontSize: 10, color: "var(--wb-color-hash-gray)", marginTop: 4 }}>
              {s.drop}
            </div>
          </div>
        ))}
      </div>
      <p style={{ marginTop: 14, marginBottom: 0, fontSize: 13, color: "var(--wb-color-aged-ink-soft)" }}>
        Every step writes to the ledger.{" "}
        <span style={{ fontFamily: "var(--wb-font-mono)", color: "var(--wb-color-hash-gray)" }}>
          propose → execute → verify → resolve → trace
        </span>{" "}
        — the canonical sequence.
      </p>
    </>
  );
}

function LoopRows() {
  const rows = [
    { id: "L1", verb: "Triaged candidate sources from conversation", n: 38, spark: [2,4,3,5,7,9,8] },
    { id: "L2", verb: "Detected catalog drift in connected surfaces", n: 14, spark: [1,0,2,3,1,4,3] },
    { id: "L3", verb: "Discovered lineage edges between tables", n: 112, spark: [8,10,14,18,22,18,22] },
    { id: "L4", verb: "Computed schema-impact on connected surfaces", n: 21, spark: [2,3,1,4,3,4,4] },
    { id: "L5", verb: "Fingerprinted columns · semantic types", n: 284, spark: [20,28,34,42,40,52,68] },
    { id: "L6", verb: "Classified PII / confidential / regulated", n: 96, spark: [6,10,14,18,16,20,12] },
    { id: "L7", verb: "Ran quality checks · emitted findings", n: 412, spark: [42,48,52,60,58,72,80] },
    { id: "L8", verb: "Stitched entities across surfaces", n: 53, spark: [4,6,5,8,9,10,11] },
  ];
  return (
    <div>
      {rows.map((r, i) => (
        <div
          key={r.id}
          style={{
            display: "grid",
            gridTemplateColumns: "50px 1fr 60px 100px",
            alignItems: "center",
            gap: 14,
            padding: "10px 0",
            borderBottom: i < rows.length - 1 ? "1px solid var(--wb-color-paper-edge)" : "none",
          }}
        >
          <div
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              letterSpacing: "0.15em",
              color: "var(--wb-color-botanical-green-deep)",
              fontWeight: 600,
            }}
          >
            {r.id}
          </div>
          <div style={{ color: "var(--wb-color-aged-ink)", fontSize: 13.5 }}>{r.verb}</div>
          <div
            style={{
              textAlign: "right",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 14,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {r.n}
          </div>
          <div style={{ height: 22 }}>
            <Sparkline data={r.spark} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ChainsTable() {
  const rows = [
    { chain: "L5 → L7", what: "Detected timestamp drift in", target: "orders.created_at", tail: "— flagged 3 quality findings.", when: "14m" },
    { chain: "L6 → L4", what: "Reclassified", target: "users.phone", tail: "as regulated — impact: 4 downstream views.", when: "1h" },
    { chain: "L5 → L4", what: "Semantic type shift in", target: "prices.currency", tail: "— cast review queued.", when: "3h" },
    { chain: "L4 ↦ L2", what: "Schema impact widens drift cohort by 2 tables in", target: "snowflake-analytics", tail: ".", when: "5h" },
    { chain: "L7 → L8", what: "Quality finding suggests duplicate identities — entity stitch reopened.", target: null, tail: "", when: "8h" },
    { chain: "L1 → L3", what: "New", target: "hubspot", tail: "tables connected — 11 lineage edges discovered immediately.", when: "11h" },
  ];
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
      <thead>
        <tr style={{ borderBottom: "1px solid var(--wb-color-rule-line)" }}>
          {["Chain","Inferred","When"].map((h, i) => (
            <th
              key={h}
              style={{
                textAlign: i === 2 ? "right" : "left",
                padding: "8px 10px 8px 0",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 10,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
                fontWeight: 500,
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderBottom: "1px solid var(--wb-color-paper-edge)" }}>
            <td
              style={{
                padding: "12px 10px 12px 0",
                fontFamily: "var(--wb-font-mono)",
                color: "var(--wb-color-botanical-green-deep)",
                fontSize: 12,
                whiteSpace: "nowrap",
              }}
            >
              {r.chain}
            </td>
            <td style={{ padding: "12px 10px 12px 0", color: "var(--wb-color-aged-ink-soft)" }}>
              {r.what}{" "}
              {r.target && (
                <span style={{ color: "var(--wb-color-aged-ink)", fontWeight: 500 }}>{r.target}</span>
              )}
              {r.tail && ` ${r.tail}`}
            </td>
            <td
              style={{
                padding: "12px 10px 12px 0",
                textAlign: "right",
                fontFamily: "var(--wb-font-mono)",
                color: "var(--wb-color-hash-gray)",
                fontSize: 12,
              }}
            >
              {r.when}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ============================================================================
// COMPOUNDING
// ============================================================================

function CompoundingView() {
  return (
    <>
      <PlateHead
        plate="Plate IV · compounding wiki · per ledger"
        title="What's compounding"
        blurb="KPIs in a tree, decisions hashed, processes auto-mapped, data products produced, autoresearch per role. Every artifact started at zero on day one and grows per ledger entry — never reset, always replayable."
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
        <Card eyebrow="P4 · KPIs"><Stat n="18" label="KPIs in the tree" delta="▲ 4 / 7d" /></Card>
        <Card eyebrow="P4 · processes"><Stat n="7" label="Processes auto-discovered" delta="▲ 2 mapped" /></Card>
        <Card eyebrow="P4 · products"><Stat n="12" label="Data products produced" delta="▲ 3 / 7d" /></Card>
        <Card eyebrow="P4 · research"><Stat n="23" label="Autoresearch experiments" delta="▲ 6 experiments" /></Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
        <Card eyebrow="P4.a · ramp" title="Knowledge ramp · since install">
          <LineChart
            labels={DAYS}
            series={[
              { label: "KPIs", color: "var(--wb-color-botanical-green-deep)", data: [0,1,2,4,6,8,10,12,13,14,15,16,17,18] },
              { label: "processes", color: "var(--wb-color-sepia-warning)", data: [0,0,1,1,2,2,3,4,4,5,6,6,7,7] },
              { label: "data products", color: "var(--wb-color-aged-ink-soft)", data: [0,0,1,2,3,4,5,6,7,8,9,10,11,12] },
              { label: "decisions", color: "var(--wb-color-botanical-green)", dashed: true, data: [0,2,4,6,9,12,15,19,22,26,30,33,37,42] },
            ]}
          />
        </Card>
        <Card eyebrow="P4.b · KPI tree" title="Top of the KPI tree">
          <KpiTree />
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
        <Card eyebrow="P4.c · processes" title="Auto-mapped from threads">
          <ProcessesList />
        </Card>
        <Card eyebrow="P4.d · products" title="Data products with provenance">
          <DataProductsList />
        </Card>
        <Card eyebrow="P4.e · autoresearch" title="Experiments per role">
          <StackedBars
            labels={["CFO","COO","CMO","eng","data","support"]}
            height={180}
            series={[
              { label: "approved", color: "var(--wb-color-botanical-green-deep)", data: [5,4,3,4,3,2] },
              { label: "rejected", color: "var(--wb-color-sepia-warning-deep)", data: [1,1,2,2,1,0] },
              { label: "pending", color: "var(--wb-color-sepia-warning)", data: [1,2,0,2,1,1] },
            ]}
          />
          <p style={{ marginTop: 10, marginBottom: 0, fontSize: 12.5, color: "var(--wb-color-aged-ink-soft)", lineHeight: 1.5 }}>
            Each role gets a per-user autoresearch seat. The CFO's loop runs metric hygiene checks; the COO's runs process-completion sweeps; eng runs schema-quality probes.
          </p>
        </Card>
      </div>
    </>
  );
}

function KpiTree() {
  type Node = { level: 1 | 2 | 3; label: string; value: string; tone?: "good" | "bad" };
  const nodes: Node[] = [
    { level: 1, label: "North Star · ARR", value: "$4.21M ▲", tone: "good" },
    { level: 2, label: "NRR (Q1)", value: "108.4% ▲", tone: "good" },
    { level: 3, label: "expansion revenue", value: "$314k" },
    { level: 3, label: "churned ARR", value: "$214k", tone: "bad" },
    { level: 2, label: "New ARR (Q1)", value: "$620k ▲", tone: "good" },
    { level: 3, label: "SDR-sourced", value: "$182k" },
    { level: 3, label: "inbound", value: "$438k" },
    { level: 2, label: "Active users", value: "12,841" },
    { level: 3, label: "DAU/MAU", value: "28%" },
  ];
  const styleFor = (n: Node) => {
    const base: CSSProperties = {
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "8px 12px",
      border: "1px solid var(--wb-color-rule-line)",
      background: "var(--wb-color-paper-deep)",
      fontSize: 13,
    };
    if (n.level === 1) return { ...base, borderLeft: "3px solid var(--wb-color-botanical-green-deep)" };
    if (n.level === 2) return { ...base, marginLeft: 22, borderLeft: "2px solid var(--wb-color-botanical-green)" };
    return { ...base, marginLeft: 44, color: "var(--wb-color-aged-ink-soft)", borderLeft: "1px solid var(--wb-color-hash-gray)" };
  };
  const valColor = (tone?: "good" | "bad") =>
    tone === "good"
      ? "var(--wb-color-botanical-green-deep)"
      : tone === "bad"
      ? "var(--wb-color-sepia-warning-deep)"
      : "var(--wb-color-aged-ink)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {nodes.map((n, i) => (
        <div key={i} style={styleFor(n)}>
          <span>{n.label}</span>
          <span style={{ marginLeft: "auto", fontFamily: "var(--wb-font-mono)", color: valColor(n.tone) }}>{n.value}</span>
        </div>
      ))}
    </div>
  );
}

function ProcessesList() {
  const rows: { name: string; meta: string; tone: keyof typeof PILL_TONES; tag: string }[] = [
    { name: "Invoice approval", meta: "4 steps · 3 owners · #finance", tone: "good", tag: "live" },
    { name: "PR review", meta: "3 steps · CODEOWNERS-aware", tone: "good", tag: "live" },
    { name: "Incident response", meta: "5 steps · paging matrix from PagerDuty", tone: "good", tag: "live" },
    { name: "Customer onboarding", meta: "7 steps · partial · owner unknown", tone: "warn", tag: "partial" },
    { name: "Quarterly planning", meta: "draft · 6 steps", tone: "accent", tag: "propose" },
  ];
  return <ListWithPills rows={rows} />;
}

function DataProductsList() {
  const rows: { name: string; meta: string; tone: keyof typeof PILL_TONES; tag: string }[] = [
    { name: "Q1 churn cohort", meta: "notebook · signed by maya · replayable", tone: "accent", tag: "notebook" },
    { name: "NRR live tile", meta: "dashboard tile · receipt-backed", tone: "accent", tag: "tile" },
    { name: "Free-trial → paid funnel", meta: "dashboard · 5 columns from gold", tone: "accent", tag: "view" },
    { name: "PII drift digest", meta: "alert · weekly to admins", tone: "accent", tag: "alert" },
    { name: "Daily ARR receipt", meta: "slack msg · 09:00 to #finance", tone: "accent", tag: "slack" },
  ];
  return <ListWithPills rows={rows} />;
}

function ListWithPills({
  rows,
}: {
  rows: { name: string; meta: string; tone: keyof typeof PILL_TONES; tag: string }[];
}) {
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {rows.map((r, i) => (
        <li
          key={r.name}
          style={{
            padding: "10px 0",
            borderBottom: i < rows.length - 1 ? "1px solid var(--wb-color-paper-edge)" : "none",
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
            alignItems: "start",
          }}
        >
          <div>
            <div style={{ color: "var(--wb-color-aged-ink)", fontWeight: 500, fontSize: 13.5 }}>{r.name}</div>
            <div style={{ color: "var(--wb-color-hash-gray)", fontFamily: "var(--wb-font-mono)", fontSize: 11, marginTop: 2 }}>{r.meta}</div>
          </div>
          <Pill tone={r.tone}>{r.tag}</Pill>
        </li>
      ))}
    </ul>
  );
}
