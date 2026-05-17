"use client";
/**
 * InstallCascadePanel — live SSE feed of the install cascade (W1.A3).
 *
 * Subscribes (via the browser's native EventSource API) to
 * `/api/v1/ledger/stream?since=<sinceSeq>&kinds=execute,verify,resolve`
 * and renders a checkmark per PEVR cycle as each entry lands. The
 * cascade has nine canonical steps:
 *
 *   1. install_completed                — Tier 1 OAuth landed
 *   2. setup_mode_chosen                — wizard or bot picked (or skipped)
 *   3. local_lake_provisioned           — default lake source proposed (provision_local_lake)
 *   4. lake_bronze                      — bronze tier published (medallion)
 *   5. lake_silver                      — silver scrubbed + tagged (medallion)
 *   6. lake_gold                        — gold mart published (medallion)
 *   7. concept_proposed                 — first ontology concept seen
 *   8. ramp_recompute                   — knowledge ramp first-moved
 *   9. autoresearch_loop_armed          — overnight loop is armed
 *
 * The 4 lake cycles in steps 3-6 are written by ``provision_local_lake``
 * (step 3) and the ``MedallionCascade`` (steps 4-6). Steps 7-9 are
 * written by the worm's reactivity loops as they pick up the
 * freshly-provisioned lake.
 *
 * Emitter-name alignment (2026-05-30, Sub-wave A F1 correctness fix):
 * each step matches the ACTUAL ledger tool a real producer writes. The
 * earlier `emit_default_lake_provisioned` / `emit_lake_bronze_ingested`
 * / `emit_lake_silver_promoted` / `emit_lake_gold_published` /
 * `emit_autoresearch_armed` names had NO producer — five of nine cells
 * never checked off in production. Real producers (audited via
 * `grep -rn "tool=.emit_" apps/worm-core packages`):
 *   - provision_local_lake → emit_source_proposed/confirmed/connected/profiled
 *   - MedallionCascade     → emit_source_bronzed/silvered/golded
 *   - ramp                 → emit_memory_written
 *   - autoresearch         → emit_experiment_proposed
 * The renamed cells preserve the welcome page narrative "every
 * checkmark is a real PEVR cycle landing".
 *
 * Empty state: when SSE cannot connect we render an honest "live feed
 * unavailable" affordance with a manual /trace link rather than a
 * silent skeleton. Per CLAUDE.md: silent panels are demo seams.
 *
 * No React Query, no SWR — keep deps minimal. The component owns its
 * EventSource lifecycle and closes it on unmount.
 */

import { useEffect, useMemo, useState } from "react";

export interface InstallCascadePanelProps {
  /** install_id to filter the SSE stream by. Empty string means
   *  "render the cascade as not-yet-seeded" — all rows pending. */
  installId: string;
  /** Seq value to start streaming from (exclusive). Usually the seq of
   *  the install_completed entry — anything earlier is replayed history
   *  the panel doesn't care about. */
  sinceSeq: number | null;
  /** SSE endpoint base. Tests override to a stub server; production
   *  defaults to the dashboard's own SSE proxy at
   *  `/api/v1/ledger/stream`. */
  streamUrl?: string;
}

interface CascadeStep {
  id: string;
  label: string;
  detail: string;
  /** Match function — receives the parsed ledger row and returns true
   *  when this step is satisfied. */
  matches: (entry: LedgerStreamEntry) => boolean;
}

interface LedgerStreamEntry {
  seq: number;
  kind: string;
  ts: string;
  payload: {
    tool?: string;
    args?: Record<string, unknown>;
  };
  hash: string;
}

const CASCADE_STEPS: ReadonlyArray<CascadeStep> = [
  {
    id: "install_completed",
    label: "Install completed",
    detail: "OAuth grant landed; tenant + installer Person + tenancy roles written.",
    matches: (e) => e.payload.tool === "emit_install_completed",
  },
  {
    id: "setup_mode_chosen",
    label: "Setup mode picked",
    detail: "Wizard or bot path chosen — may also flush past on minimal-friction tenants.",
    matches: (e) => e.payload.tool === "emit_setup_mode_chosen",
  },
  {
    id: "local_lake_provisioned",
    label: "Default lake provisioned",
    detail:
      "Local lake source proposed — provision_local_lake confirmed + connected + profiled.",
    // provision_local_lake fires a 4-cycle chain
    // (proposed/confirmed/connected/profiled). Match on profiled so the
    // cell only lights after the full chain lands — that's the moment
    // the lake is actually usable. Provider audited 2026-05-30:
    // apps/worm-core/src/wormbase_core/source_builder.py emits each tool.
    matches: (e) => e.payload.tool === "emit_source_profiled",
  },
  {
    id: "lake_bronze",
    label: "Bronze tier published",
    detail: "Medallion bronze cycle landed — raw rows are queryable.",
    // Producer: MedallionCascade (apps/worm-core/src/wormbase_core/medallion.py:518).
    matches: (e) => e.payload.tool === "emit_source_bronzed",
  },
  {
    id: "lake_silver",
    label: "Silver scrubbed",
    detail: "Bronze promoted to silver with classification + ontology tags.",
    // Producer: MedallionCascade (medallion.py:556).
    matches: (e) => e.payload.tool === "emit_source_silvered",
  },
  {
    id: "lake_gold",
    label: "Gold published",
    detail: "First gold-tier mart published — KPI candidates available.",
    // Producer: MedallionCascade (medallion.py:594).
    matches: (e) => e.payload.tool === "emit_source_golded",
  },
  {
    id: "concept_proposed",
    label: "First concept proposed",
    detail: "The worm matched its first ontology concept against this tenant.",
    matches: (e) => e.payload.tool === "emit_concept_proposed",
  },
  {
    id: "ramp_recompute",
    label: "Knowledge ramp moved",
    detail: "First ramp axis nudged — the worm has begun learning this tenant.",
    matches: (e) => e.payload.tool === "emit_memory_written",
  },
  {
    id: "autoresearch_armed",
    label: "Autoresearch loop armed",
    detail: "Overnight loop is wired and waiting on the next run window.",
    // Producer: research-loop reactivities (packages/wormbase-research-loop)
    // write emit_experiment_proposed on the first proposal that lands
    // post-install. No `emit_autoresearch_armed` producer exists in
    // production today; the cell matches the experiment-proposed signal
    // (the worm has begun running experiments).
    matches: (e) => e.payload.tool === "emit_experiment_proposed",
  },
];

type ConnectionState = "connecting" | "open" | "error" | "closed";

export function InstallCascadePanel({
  installId,
  sinceSeq,
  streamUrl,
}: InstallCascadePanelProps) {
  const [seenStepIds, setSeenStepIds] = useState<Set<string>>(new Set());
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [errorReason, setErrorReason] = useState<string | null>(null);

  const url = useMemo(() => {
    const base = streamUrl ?? "/api/v1/ledger/stream";
    const params = new URLSearchParams();
    if (sinceSeq !== null && Number.isFinite(sinceSeq)) {
      params.set("since", String(sinceSeq));
    }
    params.set("kinds", "execute,verify,resolve");
    if (installId) {
      params.set("filter_install", installId);
    }
    const qs = params.toString();
    return qs ? `${base}?${qs}` : base;
  }, [streamUrl, sinceSeq, installId]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setConnection("error");
      setErrorReason("EventSource API not available in this runtime.");
      return;
    }
    let source: EventSource | null = null;
    try {
      source = new EventSource(url);
    } catch (err) {
      setConnection("error");
      setErrorReason((err as Error).message ?? String(err));
      return;
    }
    setConnection("connecting");

    source.onopen = () => setConnection("open");

    source.onmessage = (ev: MessageEvent<string>) => {
      let entry: LedgerStreamEntry;
      try {
        entry = JSON.parse(ev.data) as LedgerStreamEntry;
      } catch {
        return; // tolerate malformed frames
      }
      if (!entry || typeof entry !== "object") return;
      setSeenStepIds((prev) => {
        const next = new Set(prev);
        for (const step of CASCADE_STEPS) {
          if (step.matches(entry)) next.add(step.id);
        }
        if (next.size === prev.size) return prev;
        return next;
      });
    };

    source.onerror = () => {
      // EventSource auto-retries on error; surface the state but do not
      // close — let the browser reconnect.
      setConnection((prev) => (prev === "open" ? "error" : prev));
      if (!errorReason) {
        setErrorReason("Live feed connection interrupted; retrying.");
      }
    };

    return () => {
      if (source) {
        source.close();
        setConnection("closed");
      }
    };
    // errorReason intentionally not a dep — onerror manages it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  return (
    <section
      data-testid="install-cascade-panel"
      data-connection-state={connection}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 20,
        background: "var(--wb-color-paper)",
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
          install cascade · live ledger feed
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          The worm is wiring your tenant
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          Each row below corresponds to a real ledger entry. Checkmarks
          appear as the entries land — no faking, no placeholders.
        </p>
      </header>

      <ol
        data-testid="install-cascade-steps"
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {CASCADE_STEPS.map((step, idx) => {
          const seen = seenStepIds.has(step.id);
          return (
            <li
              key={step.id}
              data-testid={`cascade-step-${step.id}`}
              data-seen={seen ? "true" : "false"}
              style={{
                display: "flex",
                gap: 12,
                alignItems: "flex-start",
                padding: "8px 12px",
                border: "1px solid var(--wb-color-rule-line)",
                background: seen
                  ? "var(--wb-color-botanical-green-soft)"
                  : "var(--wb-color-paper-deep)",
              }}
            >
              <span
                aria-hidden="true"
                data-testid={`cascade-step-${step.id}-mark`}
                className="wb-mono"
                style={{
                  fontSize: 14,
                  width: 20,
                  textAlign: "center",
                  color: seen
                    ? "var(--wb-color-aged-ink)"
                    : "var(--wb-color-hash-gray)",
                }}
              >
                {seen ? "✓" : String(idx + 1).padStart(2, "0")}
              </span>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    color: "var(--wb-color-aged-ink)",
                  }}
                >
                  {step.label}
                </span>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 12,
                    color: "var(--wb-color-hash-gray)",
                    lineHeight: 1.45,
                  }}
                >
                  {step.detail}
                </span>
              </div>
            </li>
          );
        })}
      </ol>

      <footer
        data-testid="install-cascade-footer"
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {connection === "open" ? (
          <span data-testid="cascade-connection-open">live · streaming</span>
        ) : connection === "connecting" ? (
          <span data-testid="cascade-connection-connecting">
            connecting to ledger stream…
          </span>
        ) : connection === "closed" ? (
          <span data-testid="cascade-connection-closed">stream closed</span>
        ) : (
          <span
            data-testid="cascade-connection-error"
            style={{ color: "var(--wb-color-sepia-warning-deep)" }}
          >
            live feed unavailable —
            {errorReason ? ` ${errorReason}` : null} fall back to{" "}
            <a
              href="/trace"
              style={{ color: "inherit", textDecoration: "underline" }}
            >
              /trace
            </a>{" "}
            for the manual view.
          </span>
        )}
      </footer>
    </section>
  );
}

export const __INSTALL_CASCADE_STEPS__ = CASCADE_STEPS;
