"use client";
/**
 * OpsLiveView — client wrapper that polls /api/v1/ops/health every 5s and
 * re-renders the four observability cards (W2.A10).
 *
 * Polling cadence rationale: 5s matches the worm-core heartbeat
 * (`WORM_CORE_LOOP_INTERVAL_S=5`). Faster polling would just waste server
 * cycles since the source-of-truth tick is 5s. Slower polling would lose
 * the "live counts" feel the /ops tab is supposed to provide.
 *
 * Polling > SSE here on purpose: the payload is small, all four panels
 * change together (one round-trip = one consistent snapshot), and SSE
 * adds reconnect-handling + back-pressure complexity for no observable
 * benefit at this scale. The same trade-off was made for /dashboard's
 * RampGauges. SSE remains in use for the cascade panel because the
 * cascade specifically wants per-row `event:` framing — /ops does not.
 *
 * The component renders the previous successful payload while a new fetch
 * is in flight, so a transient 502 doesn't blank the entire panel — the
 * red banner only appears when no good snapshot is available.
 */

import { useCallback } from "react";

import { usePoll } from "../../lib/use-poll";
import type {
  OpsHealthError,
  OpsHealthPayload,
} from "../../lib/ledger-client.types";

import { AgentLoopStatusCard } from "./AgentLoopStatusCard";
import { LedgerThroughputCard } from "./LedgerThroughputCard";
import { MCPRateLimitCard } from "./MCPRateLimitCard";
import { PostgresHealthCard } from "./PostgresHealthCard";

const POLL_INTERVAL_MS = 5_000;

interface OpsLiveViewProps {
  initial: OpsHealthPayload | OpsHealthError;
}

function isPayload(
  v: OpsHealthPayload | OpsHealthError,
): v is OpsHealthPayload {
  return (v as OpsHealthError).ok !== false;
}

export function OpsLiveView({ initial }: OpsLiveViewProps) {
  const fetcher = useCallback(async (): Promise<
    OpsHealthPayload | OpsHealthError
  > => {
    const res = await fetch("/api/v1/ops/health", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const body = (await res.json().catch(() => null)) as
      | OpsHealthPayload
      | OpsHealthError
      | null;
    if (!body) {
      return {
        ok: false,
        error: "bad_json",
        message: "ops health proxy returned non-JSON",
        status: res.status,
      };
    }
    return body;
  }, []);

  const { data, lastTickAt, error } = usePoll(fetcher, {
    intervalMs: POLL_INTERVAL_MS,
    initial,
  });

  const current = data ?? initial;
  const liveBadge =
    lastTickAt != null
      ? `live · refreshed ${Math.max(0, Math.round((Date.now() - lastTickAt) / 1000))}s ago`
      : "loading";

  if (!isPayload(current)) {
    return (
      <ProxyErrorBanner err={current} liveBadge={liveBadge} />
    );
  }

  return (
    <>
      {error ? <TransientErrorChip err={error} /> : null}
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          className="wb-mono"
          data-testid="ops-live-badge"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {liveBadge}
        </span>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
          }}
          data-testid="ops-generated-at"
        >
          generated {current.generatedAt}
        </span>
      </header>
      <PostgresHealthCard health={current.postgres} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <LedgerThroughputCard throughput={current.ledgerThroughput} />
        <AgentLoopStatusCard loops={current.agentLoops} />
      </div>
      <MCPRateLimitCard rateLimits={current.mcpRateLimits} />
    </>
  );
}

function ProxyErrorBanner({
  err,
  liveBadge,
}: {
  err: OpsHealthError;
  liveBadge: string;
}) {
  return (
    <section
      data-testid="ops-proxy-error"
      data-error={err.error}
      style={{
        border: "2px solid #9c1f1f",
        background: "#fde7e7",
        color: "#7a0e0e",
        padding: "20px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "#9c1f1f",
        }}
      >
        Ops proxy · {liveBadge}
      </span>
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 22,
          fontWeight: 500,
          color: "#7a0e0e",
        }}
      >
        Ops health is unavailable.
      </h2>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: 13,
        }}
      >
        {err.message ?? err.error}
      </p>
      <p
        className="wb-mono"
        style={{
          margin: 0,
          fontSize: 11,
          color: "#7a0e0e",
        }}
      >
        error code · {err.error}
        {typeof err.status === "number" ? ` · upstream ${err.status}` : ""}
      </p>
    </section>
  );
}

function TransientErrorChip({ err }: { err: Error }) {
  return (
    <p
      data-testid="ops-transient-error"
      className="wb-mono"
      style={{
        margin: 0,
        fontSize: 11,
        color: "#7a0e0e",
        padding: "4px 8px",
        border: "1px dashed #9c1f1f",
        background: "#fde7e7",
      }}
    >
      transient fetch error: {err.message}
    </p>
  );
}
