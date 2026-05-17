"use client";
/**
 * AgentQueryChainView — chronological PEVR + chained-entry timeline
 * (Wave 3 Task 3 — SOC-2-credibility view).
 *
 * Renders the full audit trail of a single agent_query lifecycle: the
 * four PEVR phase rows of the root cycle, every chained
 * ``inference_served`` / ``credential`` / ``query_correction_suggested``
 * / ``query_outcome_recorded`` entry, and every retry-tree PEVR cycle
 * a correction kicked off.
 *
 * Per-kind detail:
 *   - agent_query        : mcp_tool, route_mode, status, phase, latency,
 *                          cost, row_count, caused_by indent
 *   - inference_served   : served_by (model), latency_ms, cost_usd
 *   - credential         : kind (data/model), target, ttl_expires_at,
 *                          status
 *   - query_correction_suggested
 *                        : failure_kind, failure_detail, link to refined
 *                          retry chain
 *   - query_outcome_recorded
 *                        : used, useful, quality_score, optional user
 *                          correction note
 *
 * Gate denials (passed=false / status=denied) highlight in red.
 * Model invocations render in indigo. Credential issuance renders in
 * teal. caused_by chains indent visually so a retry tree reads as a
 * subtree under the original failed query.
 */
import { useState } from "react";
import type { AgentQueryChain, ChainEntry } from "../../lib/agent-query-chain";

// ─── Design-token colors per kind ─────────────────────────────────────────

/** Map a chain entry's kind to its accent color. Reuses existing
 *  --wb-color-* tokens so the field-notebook visual language stays
 *  consistent across the dashboard. */
function kindAccent(kind: string): string {
  switch (kind) {
    case "agent_query":
      return "var(--wb-color-botanical-green-deep)";
    case "inference_served":
      // Model invocations get indigo so the human eye finds them at a
      // glance — model spend is the audit dimension auditors zero in on.
      return "var(--wb-color-indigo-deep, #3636A8)";
    case "credential":
      // Teal for credential issuance — separates "we issued a token"
      // from "we made a model call" in the timeline.
      return "var(--wb-color-teal-deep, #1E6B7A)";
    case "query_correction_suggested":
      // Amber: a failure happened, recovery is in progress.
      return "var(--wb-color-amber-deep, #9C6500)";
    case "query_outcome_recorded":
      return "var(--wb-color-aged-ink)";
    default:
      return "var(--wb-color-hash-gray)";
  }
}

/** Highlight gate-denied entries in red (auditors look here first). */
function isDenied(entry: ChainEntry): boolean {
  const p = entry.payload ?? {};
  if (p.passed === false) return true;
  if (p.status === "denied") return true;
  return false;
}

// ─── Top-level chain card ─────────────────────────────────────────────────

export interface AgentQueryChainViewProps {
  chain: AgentQueryChain;
}

export function AgentQueryChainView({ chain }: AgentQueryChainViewProps) {
  return (
    <section
      data-testid="agent-query-chain"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <ChainHeader chain={chain} />
      <ol
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 0,
        }}
      >
        {chain.entries.map((entry, idx) => {
          const depth =
            entry.causedBy && entry.causedBy !== chain.rootAuditTrailId ? 1 : 0;
          // Visually nest retry-tree entries (those caused_by a non-root
          // audit_trail_id) one level in.
          const indentPx = depth * 28;
          return (
            <li
              key={`${entry.seq}-${entry.kind}-${entry.phase ?? "none"}`}
              data-testid={`chain-entry-${entry.kind}-${entry.phase ?? "none"}-${idx}`}
              data-denied={isDenied(entry) ? "true" : "false"}
              data-kind={entry.kind}
              style={{
                display: "grid",
                gridTemplateColumns: `${indentPx + 28}px 1fr`,
                gap: 12,
              }}
            >
              <Spine
                accent={kindAccent(entry.kind)}
                isFirst={idx === 0}
                isLast={idx === chain.entries.length - 1}
                denied={isDenied(entry)}
                indentPx={indentPx}
              />
              <EntryCard entry={entry} />
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ─── Header strip (rolls up the root cycle's headline stats) ──────────────

function ChainHeader({ chain }: { chain: AgentQueryChain }) {
  const statusLabel = chain.status === "denied" ? "denied · gate fired" : chain.status;
  return (
    <header
      data-testid="agent-query-chain-header"
      style={{
        display: "flex",
        gap: 16,
        flexWrap: "wrap",
        padding: "12px 16px",
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        borderLeft: `3px solid ${
          chain.status === "denied"
            ? "var(--wb-color-red, #B23A2D)"
            : "var(--wb-color-botanical-green-deep)"
        }`,
      }}
    >
      <HeaderField label="agent" value={chain.agentId || "(unknown)"} mono />
      <HeaderField label="mcp_tool" value={chain.mcpTool || "(unknown)"} mono />
      <HeaderField label="route" value={chain.routeMode} mono />
      <HeaderField
        label="status"
        value={statusLabel}
        mono
        denied={chain.status === "denied"}
      />
      <HeaderField
        label="latency"
        value={
          chain.totalLatencyMs !== null
            ? `${chain.totalLatencyMs.toLocaleString()}ms`
            : "—"
        }
        mono
      />
      <HeaderField
        label="cost"
        value={
          chain.totalCostUsd !== null ? `$${chain.totalCostUsd}` : "—"
        }
        mono
      />
      <HeaderField
        label="entries"
        value={chain.entries.length.toString()}
        mono
      />
    </header>
  );
}

function HeaderField({
  label,
  value,
  mono = false,
  denied = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  denied?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
      <span
        className={mono ? "wb-mono" : undefined}
        style={{
          fontSize: 13,
          color: denied
            ? "var(--wb-color-red, #B23A2D)"
            : "var(--wb-color-aged-ink)",
          fontWeight: denied ? 600 : 400,
        }}
      >
        {value}
      </span>
    </div>
  );
}

// ─── Spine + per-entry card ───────────────────────────────────────────────

function Spine({
  accent,
  isFirst,
  isLast,
  denied,
  indentPx,
}: {
  accent: string;
  isFirst: boolean;
  isLast: boolean;
  denied: boolean;
  indentPx: number;
}) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "relative",
        minHeight: 72,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingLeft: indentPx,
      }}
    >
      <span
        style={{
          flex: "0 0 16px",
          width: 2,
          background: isFirst
            ? "transparent"
            : denied
              ? "var(--wb-color-red, #B23A2D)"
              : accent,
        }}
      />
      <span
        data-testid="chain-node-dot"
        style={{
          width: 12,
          height: 12,
          borderRadius: 0,
          border: `2px solid ${denied ? "var(--wb-color-red, #B23A2D)" : accent}`,
          background: denied ? "var(--wb-color-red-soft, #F5D9D5)" : accent,
          margin: "2px 0",
        }}
      />
      <span
        style={{
          flex: 1,
          width: 2,
          minHeight: 16,
          background: isLast
            ? "transparent"
            : denied
              ? "var(--wb-color-red, #B23A2D)"
              : accent,
        }}
      />
    </div>
  );
}

function EntryCard({ entry }: { entry: ChainEntry }) {
  const denied = isDenied(entry);
  const accent = kindAccent(entry.kind);
  return (
    <article
      data-testid={`chain-card-${entry.kind}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "12px 16px",
        margin: "8px 0 12px",
        background: denied
          ? "var(--wb-color-red-soft, #F5D9D5)"
          : "var(--wb-color-paper)",
        border: `1px solid ${denied ? "var(--wb-color-red, #B23A2D)" : "var(--wb-color-paper-edge)"}`,
        borderLeft: `3px solid ${denied ? "var(--wb-color-red, #B23A2D)" : accent}`,
      }}
    >
      <CardHeader entry={entry} accent={accent} denied={denied} />
      <CardDetail entry={entry} />
      <CardFooter entry={entry} />
    </article>
  );
}

function CardHeader({
  entry,
  accent,
  denied,
}: {
  entry: ChainEntry;
  accent: string;
  denied: boolean;
}) {
  const tsAbsolute = entry.ts;
  const tsRelative = relativeTs(entry.ts);
  return (
    <header
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 10,
        flexWrap: "wrap",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: denied ? "var(--wb-color-red, #B23A2D)" : accent,
          fontWeight: 600,
        }}
      >
        {entry.kind}
        {entry.phase ? ` · ${entry.phase}` : ""}
      </span>
      {denied ? (
        <span
          data-testid="chain-gate-denied-pill"
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            padding: "1px 6px",
            border: "1px solid var(--wb-color-red, #B23A2D)",
            color: "var(--wb-color-red, #B23A2D)",
            background: "transparent",
          }}
        >
          GATE DENIED
        </span>
      ) : null}
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        seq#{entry.seq}
      </span>
      <span
        className="wb-mono"
        title={tsAbsolute}
        style={{
          fontSize: 11,
          color: "var(--wb-color-hash-gray)",
          marginLeft: "auto",
        }}
      >
        {tsRelative}
      </span>
    </header>
  );
}

function CardDetail({ entry }: { entry: ChainEntry }) {
  switch (entry.kind) {
    case "agent_query":
      return <AgentQueryDetail entry={entry} />;
    case "inference_served":
      return <InferenceServedDetail entry={entry} />;
    case "credential":
      return <CredentialDetail entry={entry} />;
    case "query_correction_suggested":
      return <QueryCorrectionSuggestedDetail entry={entry} />;
    case "query_outcome_recorded":
      return <QueryOutcomeRecordedDetail entry={entry} />;
    default:
      // One-shot envelopes with no special renderer — render the raw
      // payload as a single-line summary so nothing renders blank.
      return <RawSummary entry={entry} />;
  }
}

function AgentQueryDetail({ entry }: { entry: ChainEntry }) {
  const p = entry.payload;
  const mcpTool = stringOr(p.mcp_tool, "(unknown tool)");
  const routeMode = stringOr(p.route_mode, "broker");
  const rowCount = numberOrNull(p.row_count);
  const cost = stringOrNull(p.cost_usd);
  const latency = numberOrNull(p.latency_ms);
  const causedBy = stringOrNull(p.caused_by);
  return (
    <dl
      data-testid="chain-detail-agent_query"
      style={detailGridStyle}
    >
      <DetailItem label="mcp_tool" value={mcpTool} mono />
      <DetailItem label="route" value={routeMode} mono />
      {rowCount !== null ? (
        <DetailItem label="row_count" value={rowCount.toLocaleString()} mono />
      ) : null}
      {latency !== null ? (
        <DetailItem label="latency" value={`${latency}ms`} mono />
      ) : null}
      {cost !== null ? (
        <DetailItem label="cost" value={`$${cost}`} mono />
      ) : null}
      {causedBy !== null ? (
        <DetailItem
          label="caused_by"
          value={shortId(causedBy)}
          title={causedBy}
          mono
        />
      ) : null}
    </dl>
  );
}

function InferenceServedDetail({ entry }: { entry: ChainEntry }) {
  const p = entry.payload;
  const servedBy = stringOr(p.served_by, "(unknown model)");
  const latency = numberOrNull(p.latency_ms);
  const cost = stringOrNull(p.cost_usd);
  const cacheHit = p.served_by === "cache";
  return (
    <dl data-testid="chain-detail-inference_served" style={detailGridStyle}>
      <DetailItem label="model" value={servedBy} mono />
      {cacheHit ? (
        <DetailItem label="cache" value="hit" mono />
      ) : null}
      {latency !== null ? (
        <DetailItem label="latency" value={`${latency}ms`} mono />
      ) : null}
      {cost !== null ? (
        <DetailItem label="cost" value={`$${cost}`} mono />
      ) : null}
    </dl>
  );
}

function CredentialDetail({ entry }: { entry: ChainEntry }) {
  const p = entry.payload;
  const credentialKind = stringOr(p.credential_kind, "data");
  const target = stringOr(p.target, "(unknown target)");
  const ttlIso = stringOr(p.ttl_expires_at, "");
  const status = stringOr(p.status, "active");
  return (
    <dl data-testid="chain-detail-credential" style={detailGridStyle}>
      <DetailItem label="kind" value={credentialKind} mono />
      <DetailItem
        label="target"
        value={shortTarget(target)}
        title={target}
        mono
      />
      {ttlIso ? <DetailItem label="ttl_expires" value={ttlIso} mono /> : null}
      <DetailItem label="status" value={status} mono />
    </dl>
  );
}

function QueryCorrectionSuggestedDetail({ entry }: { entry: ChainEntry }) {
  const p = entry.payload;
  const failureKind = stringOr(p.failure_kind, "(unknown)");
  const failureDetail = stringOr(p.failure_detail, "");
  const originalQueryId = stringOrNull(p.original_query_id);
  return (
    <dl
      data-testid="chain-detail-query_correction_suggested"
      style={detailGridStyle}
    >
      <DetailItem label="failure" value={failureKind} mono />
      {failureDetail ? (
        <DetailItem
          label="detail"
          value={failureDetail.length > 80 ? failureDetail.slice(0, 80) + "…" : failureDetail}
          title={failureDetail}
        />
      ) : null}
      {originalQueryId !== null ? (
        <DetailItem
          label="original"
          value={shortId(originalQueryId)}
          title={originalQueryId}
          mono
        />
      ) : null}
    </dl>
  );
}

function QueryOutcomeRecordedDetail({ entry }: { entry: ChainEntry }) {
  const p = entry.payload;
  const used = Boolean(p.used);
  const useful = Boolean(p.useful);
  const quality = stringOrNull(p.quality_score);
  const correction = stringOrNull(p.user_correction);
  return (
    <dl
      data-testid="chain-detail-query_outcome_recorded"
      style={detailGridStyle}
    >
      <DetailItem label="used" value={used ? "yes" : "no"} mono />
      <DetailItem label="useful" value={useful ? "yes" : "no"} mono />
      {quality !== null ? (
        <DetailItem label="quality" value={quality} mono />
      ) : null}
      {correction !== null ? (
        <DetailItem label="user_correction" value={correction} />
      ) : null}
    </dl>
  );
}

function RawSummary({ entry }: { entry: ChainEntry }) {
  // Best-effort fallback: surface the first scalar string-valued field
  // we find, plus the envelope kind. Never errors on weird shapes.
  const items: Array<[string, string]> = [];
  for (const [k, v] of Object.entries(entry.payload ?? {})) {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      items.push([k, String(v)]);
    }
    if (items.length >= 4) break;
  }
  return (
    <dl data-testid="chain-detail-raw" style={detailGridStyle}>
      {items.map(([k, v]) => (
        <DetailItem key={k} label={k} value={v} mono />
      ))}
    </dl>
  );
}

function CardFooter({ entry }: { entry: ChainEntry }) {
  return (
    <footer
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
      }}
    >
      <CopyHashButton hash={entry.hashHex} kind={entry.kind} seq={entry.seq} />
      {entry.auditTrailId ? (
        <span
          className="wb-mono"
          title={entry.auditTrailId}
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          audit_trail · {shortId(entry.auditTrailId)}
        </span>
      ) : null}
    </footer>
  );
}

// ─── DetailItem + Copy + helpers ──────────────────────────────────────────

const detailGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
  margin: 0,
};

function DetailItem({
  label,
  value,
  title,
  mono = false,
}: {
  label: string;
  value: string;
  title?: string;
  mono?: boolean;
}) {
  return (
    <div
      data-testid={`chain-detail-item-${label}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
    >
      <dt
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </dt>
      <dd
        className={mono ? "wb-mono" : undefined}
        title={title}
        style={{
          margin: 0,
          fontSize: 12,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {value}
      </dd>
    </div>
  );
}

function CopyHashButton({
  hash,
  kind,
  seq,
}: {
  hash: string;
  kind: string;
  seq: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  async function copy() {
    try {
      if (
        typeof navigator !== "undefined" &&
        navigator.clipboard?.writeText
      ) {
        await navigator.clipboard.writeText(hash);
      } else if (typeof window !== "undefined") {
        window.prompt("Copy this hash:", hash);
      }
      setState("copied");
      setTimeout(() => setState("idle"), 1500);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 1500);
    }
  }

  const shortHash = hash.length > 14 ? `${hash.slice(0, 10)}…` : hash;
  const label =
    state === "copied"
      ? "copied ✓"
      : state === "error"
        ? "copy failed"
        : `#${shortHash}`;
  return (
    <button
      type="button"
      onClick={copy}
      data-testid={`chain-copy-hash-${kind}-${seq}`}
      data-state={state}
      title={`Copy full hash: ${hash}`}
      className="wb-mono"
      style={{
        fontSize: 10,
        letterSpacing: "0.04em",
        padding: "3px 7px",
        border: "1px solid var(--wb-color-aged-ink)",
        background:
          state === "copied"
            ? "var(--wb-color-botanical-green-soft, #D7EFC9)"
            : "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        cursor: "pointer",
        borderRadius: 0,
      }}
    >
      {label}
    </button>
  );
}

// ─── Coercion helpers ─────────────────────────────────────────────────────

function stringOr(v: unknown, fallback: string): string {
  return typeof v === "string" && v.length > 0 ? v : fallback;
}

function stringOrNull(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function numberOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function shortId(id: string): string {
  return id.length > 12 ? id.slice(0, 8) + "…" : id;
}

function shortTarget(target: string): string {
  // Snowflake URIs / dbt artifact URLs can be long; show a compact form
  // while the full target stays in the title attribute.
  if (target.length <= 40) return target;
  return target.slice(0, 18) + "…" + target.slice(-18);
}

function relativeTs(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const diffMs = Date.now() - t;
  const absSec = Math.floor(Math.abs(diffMs) / 1000);
  if (absSec < 60) return `${absSec}s ago`;
  const absMin = Math.floor(absSec / 60);
  if (absMin < 60) return `${absMin}m ago`;
  const absHr = Math.floor(absMin / 60);
  if (absHr < 24) return `${absHr}h ago`;
  const absDay = Math.floor(absHr / 24);
  return `${absDay}d ago`;
}
