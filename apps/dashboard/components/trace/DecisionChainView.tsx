"use client";
/**
 * DecisionChainView — vertical chain visualisation for the Decision →
 * Bytes audit page (Phase 3 Task 3C).
 *
 * Walks five steps from the decision the operator clicked through to the
 * raw bronze hash that originated the data feeding it. Each step shows
 * its ledger entry sequence, kind, full hash (with copy-to-clipboard),
 * and a brief payload summary. Botanical-green connectors render between
 * adjacent steps; missing intermediate steps display an honest "not
 * extracted yet" pill rather than a fabricated link.
 *
 * Field Notebook visual language: paper background, aged-ink text,
 * botanical-green accents, monospaced ledger ids. No icons; this is
 * audit-grade — clarity beats cleverness.
 *
 * 2026-05-07 (W4-B) — Steps that originate from chatter (the
 * decision_recorded entry, derived from chat_received evidence
 * messages) surface a small ``PlatformBadge`` in their header so the
 * auditor sees at a glance which channel platform the chain rooted
 * back to. Platform is read from the entry payload's ``platform``
 * field when present, with channel-id-shape inference as a
 * back-compat fallback for pre-provenance entries. Steps without a
 * resolvable platform render no badge — no fabrication.
 */
import { useState } from "react";
import type {
  ChainStep,
  ChainStepKind,
  DecisionChain,
} from "../../lib/decision-chain";
import { PlatformBadge } from "../shared/PlatformBadge";

const STEP_ORDER: ReadonlyArray<{ key: keyof DecisionChain; kind: ChainStepKind; label: string; }> = [
  { key: "decision", kind: "decision_recorded", label: "Decision" },
  { key: "processMap", kind: "process_map_proposed", label: "Process map" },
  { key: "kpi", kind: "kpi_node", label: "KPI" },
  { key: "source", kind: "source_proposed", label: "Source" },
  { key: "bronze", kind: "source_bronzed", label: "Bronze bytes" },
];

export interface DecisionChainViewProps {
  chain: DecisionChain;
}

export function DecisionChainView({ chain }: DecisionChainViewProps) {
  return (
    <ol
      data-testid="decision-chain"
      style={{
        listStyle: "none",
        padding: 0,
        margin: 0,
        display: "flex",
        flexDirection: "column",
        gap: 0,
      }}
    >
      {STEP_ORDER.map((meta, idx) => {
        const step = chain[meta.key] as ChainStep | null;
        const isLast = idx === STEP_ORDER.length - 1;
        return (
          <li
            key={meta.kind}
            data-testid={`chain-row-${meta.kind}`}
            data-resolved={step ? "true" : "false"}
            style={{
              display: "grid",
              gridTemplateColumns: "44px 1fr",
              gap: 16,
            }}
          >
            <Connector
              filled={step !== null}
              isFirst={idx === 0}
              isLast={isLast}
            />
            {step ? (
              <ChainStepCard step={step} label={meta.label} />
            ) : (
              <ChainStepMissing kind={meta.kind} label={meta.label} />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ─── Connector spine ─────────────────────────────────────────────────────

function Connector({
  filled,
  isFirst,
  isLast,
}: {
  filled: boolean;
  isFirst: boolean;
  isLast: boolean;
}) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "relative",
        minHeight: 88,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      {/* upward stem (hidden on first row) */}
      <span
        style={{
          flex: "0 0 18px",
          width: 2,
          background: isFirst
            ? "transparent"
            : filled
              ? "var(--wb-color-botanical-green)"
              : "var(--wb-color-paper-edge)",
        }}
      />
      {/* node dot */}
      <span
        style={{
          width: 14,
          height: 14,
          borderRadius: 0,
          border: `2px solid ${
            filled
              ? "var(--wb-color-botanical-green-deep)"
              : "var(--wb-color-hash-gray)"
          }`,
          background: filled
            ? "var(--wb-color-botanical-green)"
            : "var(--wb-color-paper)",
          margin: "2px 0",
        }}
      />
      {/* downward stem */}
      <span
        style={{
          flex: 1,
          width: 2,
          minHeight: 18,
          background: isLast
            ? "transparent"
            : filled
              ? "var(--wb-color-botanical-green)"
              : "var(--wb-color-paper-edge)",
        }}
      />
    </div>
  );
}

// ─── Step card (resolved) ────────────────────────────────────────────────

/**
 * Extract a platform slug from a chain step's payload, falling back to
 * channel-id-shape inference. Returns the explicit ``platform`` field
 * when present (post-provenance entries from the WhatsApp/Slack ingest
 * paths) or the inferred slug from a Slack ``C…`` / ``D…`` id or a
 * WhatsApp ``@s.whatsapp.net`` jid. ``null`` for entries with neither —
 * the badge then renders nothing (honest empty state).
 *
 * Today, only the ``decision_recorded`` step carries a chatter-derived
 * channel id directly. The chain's other resolved steps (process_map,
 * kpi_node, source_proposed, source_bronzed) describe data artefacts
 * not bound to a channel; this helper falls through to ``null`` for
 * them and the badge correctly renders nothing — by design.
 */
function platformOfStep(
  step: ChainStep,
): { platform: string | null; channelId: string | null } {
  const args = step.payload ?? {};
  const platform =
    typeof args.platform === "string" && args.platform.length > 0
      ? args.platform
      : null;
  const channelId =
    typeof args.channel_id === "string" && args.channel_id.length > 0
      ? args.channel_id
      : null;
  return { platform, channelId };
}

function ChainStepCard({
  step,
  label,
}: {
  step: ChainStep;
  label: string;
}) {
  const { platform, channelId } = platformOfStep(step);
  return (
    <article
      data-testid={`chain-step-${step.kind}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "14px 16px",
        margin: "8px 0 16px",
        background: "var(--wb-color-paper)",
        border: "1px solid var(--wb-color-paper-edge)",
        borderLeft: "3px solid var(--wb-color-botanical-green-deep)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {label}
          {step.inferred ? " · inferred link" : ""}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink)",
            letterSpacing: "0.04em",
          }}
        >
          seq#{step.entrySeq}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {step.kind}
        </span>
        <PlatformBadge
          platform={platform}
          channelId={channelId}
          testId={`chain-platform-${step.kind}`}
        />
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            marginLeft: "auto",
          }}
        >
          {step.ts}
        </span>
      </header>

      <p
        data-testid={`chain-summary-${step.kind}`}
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 15,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {step.summary}
      </p>

      <footer
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <CopyHashButton hash={step.entryHash} kind={step.kind} />
        {step.linkHref ? (
          <a
            data-testid={`chain-link-${step.kind}`}
            href={step.linkHref}
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.04em",
              color: "var(--wb-color-botanical-green-deep)",
              borderBottom: "1px dotted var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
              padding: "2px 0",
            }}
          >
            open {label.toLowerCase()} →
          </a>
        ) : null}
        <a
          data-testid={`chain-trace-${step.kind}`}
          href={`/trace?kind=${encodeURIComponent(step.kind)}`}
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.04em",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
            borderBottom: "1px dotted var(--wb-color-paper-edge)",
            padding: "2px 0",
          }}
        >
          filter /trace
        </a>
      </footer>
    </article>
  );
}

// ─── Step card (missing) ─────────────────────────────────────────────────

function ChainStepMissing({
  kind,
  label,
}: {
  kind: ChainStepKind;
  label: string;
}) {
  return (
    <article
      data-testid={`chain-step-missing-${kind}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "12px 16px",
        margin: "8px 0 16px",
        background: "var(--wb-color-paper-deep)",
        border: "1px dashed var(--wb-color-paper-edge)",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label} · not extracted yet
      </span>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: 13,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No <code className="wb-mono">{kind}</code> entry resolves for this
        decision yet. The chain continues with the next downstream step
        when one is available.
      </p>
    </article>
  );
}

// ─── Copy-to-clipboard button ────────────────────────────────────────────

function CopyHashButton({ hash, kind }: { hash: string; kind: ChainStepKind }) {
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

  const shortHash = hash.length > 16 ? `${hash.slice(0, 12)}…` : hash;
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
      data-testid={`chain-copy-${kind}`}
      data-state={state}
      title={`Copy full hash: ${hash}`}
      className="wb-mono"
      style={{
        fontSize: 11,
        letterSpacing: "0.04em",
        padding: "4px 8px",
        border: "1px solid var(--wb-color-aged-ink)",
        background:
          state === "copied"
            ? "var(--wb-color-botanical-green-soft)"
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
