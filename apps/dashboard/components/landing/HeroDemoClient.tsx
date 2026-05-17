"use client";

/**
 * HeroDemoClient — replay-in-browser viewer (Phase 4 Task 4B).
 *
 * Receives a deterministic replay payload from the parent server
 * component (``HeroDemo``) and progressively reveals the rows in a
 * Slack-thread-style scaffold, with each row's hash receipt visible.
 * The "Replay again" button re-fires the SSR replay via the
 * ``/api/v1/landing/replay`` endpoint; visitors see the same hashes
 * the second time — that's the institutional-AI thesis on screen.
 *
 * Anti-pattern guard: this component never invents content. Every
 * message body, role, and hash comes verbatim from the server payload
 * (which itself reads ledger entries with stored hashes). The only
 * client-side state is a step counter + a ``replay`` payload that gets
 * swapped on refetch.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

export type LandingReplayRole = "actor" | "worm" | "system";
export type LandingReplayStop = "ok" | "end_of_data";

export interface LandingReplayEntry {
  id: string;
  ts: string;
  who: string;
  role: LandingReplayRole;
  body: string;
  kind: string;
  hashShort: string;
}

export interface LandingReplay {
  tenantSlug: string;
  companyId: string;
  untilTs: string;
  terminalHashHex: string;
  entries: LandingReplayEntry[];
  stop: LandingReplayStop;
}

interface Props {
  initial: LandingReplay;
  /** Override the fetch endpoint (used by tests). */
  endpoint?: string;
  /** Override the per-row reveal delay in ms (used by tests). */
  stepDelayMs?: number;
}

const DEFAULT_ENDPOINT = "/api/v1/landing/replay";
const DEFAULT_STEP_DELAY_MS = 900;

export function HeroDemoClient({
  initial,
  endpoint = DEFAULT_ENDPOINT,
  stepDelayMs = DEFAULT_STEP_DELAY_MS,
}: Props) {
  const [replay, setReplay] = useState<LandingReplay>(initial);
  const [step, setStep] = useState<number>(1);
  const [isReplaying, setIsReplaying] = useState<boolean>(false);
  const [runId, setRunId] = useState<number>(0);
  // Track the latest run so a slow refetch doesn't overwrite a newer one.
  const latestRun = useRef<number>(0);

  const totalRows = replay.entries.length;
  const reachedEnd = step >= totalRows;

  // Progressive reveal: increment ``step`` every ``stepDelayMs`` until
  // every row is visible.
  useEffect(() => {
    if (reachedEnd) return;
    const t = setTimeout(() => setStep((n) => Math.min(n + 1, totalRows)), stepDelayMs);
    return () => clearTimeout(t);
  }, [step, totalRows, stepDelayMs, reachedEnd, runId]);

  const onReplayAgain = useCallback(async () => {
    if (isReplaying) return;
    const myRun = latestRun.current + 1;
    latestRun.current = myRun;
    setIsReplaying(true);
    try {
      const res = await fetch(endpoint, { cache: "no-store" });
      if (!res.ok) {
        // Honest failure mode: keep the existing payload. The button
        // becomes available again immediately.
        return;
      }
      const next = (await res.json()) as LandingReplay;
      if (latestRun.current === myRun) {
        setReplay(next);
        setStep(1);
        setRunId((n) => n + 1);
      }
    } finally {
      if (latestRun.current === myRun) {
        setIsReplaying(false);
      }
    }
  }, [endpoint, isReplaying]);

  const visibleEntries = useMemo(
    () => replay.entries.slice(0, Math.max(1, Math.min(step, totalRows))),
    [replay.entries, step, totalRows],
  );

  return (
    <section
      data-testid="hero-demo"
      aria-label="Replay-in-browser preview — institutional AI in conversation"
      style={containerStyle}
    >
      <header style={headerStyle}>
        <span className="wb-mono" style={kickerStyle}>
          plate ii · wire-replay · hash-stable
        </span>
        <span className="wb-mono" style={tickerStyle}>
          tenant: {replay.tenantSlug} · until: {replay.untilTs.slice(0, 10)}
        </span>
      </header>

      <div data-testid="hero-demo-thread" style={threadStyle}>
        {visibleEntries.map((entry) => (
          <Row key={entry.id} entry={entry} />
        ))}
        {reachedEnd ? (
          <StopState stop={replay.stop} />
        ) : null}
      </div>

      <footer
        data-testid="hero-demo-receipt"
        style={receiptStyle}
        className="wb-mono"
      >
        <span>
          terminal hash{" "}
          <code style={hashCodeStyle}>{replay.terminalHashHex}</code> ·
          tenant <code style={hashCodeStyle}>{replay.tenantSlug}</code>
        </span>
        <button
          data-testid="hero-demo-replay-again"
          type="button"
          onClick={onReplayAgain}
          disabled={isReplaying}
          aria-label="Replay this thread — same hashes, same outputs"
          style={replayButtonStyle(isReplaying)}
        >
          {isReplaying ? "replaying…" : "↻ Replay again"}
        </button>
      </footer>
    </section>
  );
}

function Row({ entry }: { entry: LandingReplayEntry }) {
  const tone =
    entry.role === "worm"
      ? "var(--wb-color-botanical-green)"
      : entry.role === "actor"
        ? "var(--wb-color-rule-line)"
        : "var(--wb-color-hash-gray)";
  return (
    <article
      data-testid={`hero-demo-row-${entry.id}`}
      style={{ ...rowStyle, borderLeftColor: tone }}
    >
      <div style={rowHeaderStyle}>
        <span style={whoStyle}>{entry.who}</span>
        <span className="wb-mono" style={whoMetaStyle}>
          {entry.kind} · {new Date(entry.ts).toISOString().slice(11, 19)}Z
        </span>
      </div>
      <p style={bodyStyle}>{entry.body}</p>
      <p className="wb-mono" style={receiptInlineStyle}>
        ↳ hash <code style={hashCodeStyle}>{entry.hashShort}</code>
      </p>
    </article>
  );
}

function StopState({ stop }: { stop: LandingReplayStop }) {
  return (
    <div
      data-testid="hero-demo-stop-state"
      className="wb-mono"
      style={stopStateStyle}
    >
      — end of replay window · {stop} —
    </div>
  );
}

const containerStyle: CSSProperties = {
  width: "min(720px, 100%)",
  margin: "0 auto",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
  background: "var(--wb-color-paper)",
  display: "flex",
  flexDirection: "column",
};

const headerStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  padding: "10px 18px",
  borderBottom: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
};

const kickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const tickerStyle: CSSProperties = {
  fontSize: 10,
  color: "var(--wb-color-hash-gray)",
};

const threadStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 0,
};

const rowStyle: CSSProperties = {
  padding: "16px 22px",
  borderBottom: "1px solid var(--wb-color-rule-line)",
  borderLeft: "3px solid",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  textAlign: "left",
};

const rowHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 12,
  justifyContent: "space-between",
};

const whoStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontWeight: 600,
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink)",
};

const whoMetaStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--wb-color-hash-gray)",
};

const bodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-base)",
  lineHeight: 1.5,
  color: "var(--wb-color-aged-ink)",
};

const receiptInlineStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  color: "var(--wb-color-botanical-green-deep)",
  letterSpacing: "0.02em",
};

const hashCodeStyle: CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  background: "var(--wb-color-paper-deep)",
  padding: "1px 6px",
  borderRadius: 2,
  border: "1px solid var(--wb-color-rule-line)",
};

const receiptStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  padding: "10px 18px",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-hash-gray)",
  borderTop: "1px solid var(--wb-color-rule-line)",
  flexWrap: "wrap",
};

const stopStateStyle: CSSProperties = {
  padding: "12px 22px",
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-ink-faint)",
  background: "var(--wb-color-paper-deep)",
  textAlign: "center",
  borderBottom: "1px solid var(--wb-color-rule-line)",
};

function replayButtonStyle(isReplaying: boolean): CSSProperties {
  return {
    fontFamily: "var(--wb-font-mono)",
    fontSize: 11,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    border: "1px solid var(--wb-color-rule-line)",
    background: isReplaying
      ? "var(--wb-color-paper-deep)"
      : "var(--wb-color-paper)",
    color: "var(--wb-color-aged-ink)",
    padding: "6px 14px",
    borderRadius: 2,
    cursor: isReplaying ? "wait" : "pointer",
  };
}
