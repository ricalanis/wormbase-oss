"use client";

/**
 * TimeToAhaPanel — Step 2 (proactivity hook).
 *
 * Six-node horizontal stepper showing the canonical onboarding milestones
 * the worm hits on a fresh tenant:
 *
 *    T+0    install                       (first company_warmup_completed)
 *    T+5    first source proposed         (drop / mention / discovery)
 *    T+15   first concept confirmed       (column class / domain owner)
 *    T+30   first gold KPI computed       (source_golded / kpi_proposed)
 *    T+24h  first process map / question  (process_map / recurring_question)
 *    T+24h  first autoresearch experiment (heuristic_experiment)
 *
 * Lit nodes carry an absolute timestamp + duration since install. Pending
 * nodes render gray. No fixture fallback — this surface is live-only.
 *
 * Source: ``getOnboardingMilestones`` in ``lib/ledger-client.ts``. Polls
 * /api/onboarding-milestones/refresh on a 5s cadence so the demo audience
 * sees milestones light up in real time as the worm progresses.
 *
 * On-thesis criteria hit (per ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``):
 *  - C1 unprompted action     (worm hits these without explicit prompts)
 *  - C3 compounding state     (gauge persists across sessions)
 *  - C6 auditable governance  (every milestone is a ledger MIN(ts) query)
 */

import type { OnboardingMilestones } from "../../lib/ledger-client.types";
import { usePoll } from "../../lib/use-poll";

interface Milestone {
  key: keyof OnboardingMilestones;
  label: string;
  target: string; // human-readable T+x label
  hint: string;
}

const MILESTONES: ReadonlyArray<Milestone> = [
  {
    key: "installAt",
    label: "Install",
    target: "T+0",
    hint: "worm joined",
  },
  {
    key: "firstSourceAt",
    label: "First source",
    target: "T+5m",
    hint: "drop / mention / discovery",
  },
  {
    key: "firstConceptAt",
    label: "First concept",
    target: "T+15m",
    hint: "column classified or domain owned",
  },
  {
    key: "firstGoldAt",
    label: "First gold KPI",
    target: "T+30m",
    hint: "gold artifact or KPI proposal",
  },
  {
    key: "firstProcessMapAt",
    label: "First process map",
    target: "T+24h",
    hint: "process map or recurring question",
  },
  {
    key: "firstExperimentAt",
    label: "First experiment",
    target: "T+24h",
    hint: "autoresearch loop ran",
  },
] as const;

function formatDuration(installIso: string | null, hitIso: string): string {
  if (!installIso) return "live";
  const install = new Date(installIso).getTime();
  const hit = new Date(hitIso).getTime();
  if (Number.isNaN(install) || Number.isNaN(hit) || hit < install) {
    return "live";
  }
  const diffMs = hit - install;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `+${diffSec}s`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `+${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  const remMin = diffMin % 60;
  if (remMin === 0) return `+${diffHr}h`;
  return `+${diffHr}h${remMin}m`;
}

function formatAbsolute(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // hh:mm:ss UTC, e.g. "12:04:11Z"
  const h = String(d.getUTCHours()).padStart(2, "0");
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  const s = String(d.getUTCSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}Z`;
}

export interface TimeToAhaPanelProps {
  milestones: OnboardingMilestones;
  /** When true, the eyebrow + frame mimic the ramp/onboarding plate look. */
  framed?: boolean;
  /** Override polling interval (ms). Defaults to 5000. Pass 0 to disable. */
  pollIntervalMs?: number;
}

async function _fetchMilestones(): Promise<OnboardingMilestones> {
  const res = await fetch("/api/onboarding-milestones/refresh", {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`milestones refresh ${res.status}`);
  }
  const body = (await res.json()) as { milestones: OnboardingMilestones };
  return body.milestones;
}

export function TimeToAhaPanel({
  milestones,
  framed = true,
  pollIntervalMs = 5000,
}: TimeToAhaPanelProps) {
  const polled = usePoll<OnboardingMilestones>(_fetchMilestones, {
    intervalMs: pollIntervalMs > 0 ? pollIntervalMs : 60_000,
    initial: milestones,
    paused: pollIntervalMs <= 0,
  });
  const live = polled.data ?? milestones;
  const installIso = live.installAt;

  return (
    <section
      data-testid="time-to-aha-panel"
      aria-label="time to aha milestones"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: framed ? 16 : 0,
        border: framed ? "1px solid var(--wb-color-paper-edge)" : "none",
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
          Plate · Time-to-Aha
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          Onboarding milestones · live
        </h2>
      </header>
      <ol
        data-testid="time-to-aha-stepper"
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gap: 10,
        }}
      >
        {MILESTONES.map((m, idx) => {
          const ts = live[m.key];
          const lit = Boolean(ts);
          const duration = lit ? formatDuration(installIso, ts as string) : "";
          const abs = lit ? formatAbsolute(ts as string) : "";
          return (
            <li
              key={m.key}
              data-testid={`milestone-${m.key}`}
              data-state={lit ? "lit" : "pending"}
              data-index={idx}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                padding: 10,
                border: "1px solid var(--wb-color-paper-edge)",
                background: lit
                  ? "var(--wb-color-paper-deep)"
                  : "transparent",
              }}
            >
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.16em",
                  textTransform: "uppercase",
                  color: lit
                    ? "var(--wb-color-aged-ink)"
                    : "var(--wb-color-hash-gray)",
                }}
              >
                {m.target}
              </span>
              <span
                aria-hidden="true"
                data-testid={`milestone-${m.key}-bar`}
                style={{
                  height: 6,
                  background: lit
                    ? "var(--wb-color-botanical-green)"
                    : "var(--wb-color-paper-edge)",
                  border: "1px solid var(--wb-color-aged-ink)",
                }}
              />
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 14,
                  fontWeight: lit ? 600 : 400,
                  color: lit
                    ? "var(--wb-color-aged-ink)"
                    : "var(--wb-color-hash-gray)",
                }}
              >
                {m.label}
              </span>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  color: lit
                    ? "var(--wb-color-aged-ink)"
                    : "var(--wb-color-hash-gray)",
                  letterSpacing: "0.04em",
                }}
                data-testid={`milestone-${m.key}-duration`}
              >
                {lit ? duration : "pending"}
              </span>
              {lit ? (
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    color: "var(--wb-color-hash-gray)",
                    letterSpacing: "0.04em",
                  }}
                  data-testid={`milestone-${m.key}-absolute`}
                >
                  {abs}
                </span>
              ) : (
                <span
                  style={{
                    fontSize: 10,
                    color: "var(--wb-color-hash-gray)",
                    fontStyle: "italic",
                  }}
                >
                  {m.hint}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
