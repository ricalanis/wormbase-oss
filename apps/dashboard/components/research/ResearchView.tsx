"use client";
/**
 * ResearchView — the /research dashboard tab.
 *
 * Step 5 of the canonical product arc. Composes:
 *
 *   1. ResearchOverviewCard      — tenant-wide totals + win rate + top movers
 *   2. UserSelector              — Person × Position dropdown
 *   3. HeadlineMetricSparkline   — series for the current viewer's position
 *   4. ExperimentsTable          — filtered experiments queue with
 *                                  approve / discard buttons
 *
 * Live-polls `/api/research/refresh?personId=…&position=…` every 10s.
 *
 * Uses Field Notebook tokens. No new colours; everything sits on the
 * paper background.
 */

import { useCallback, useMemo, useState } from "react";
import { usePoll } from "../../lib/use-poll";
import type {
  ExperimentRow,
  ExperimentOutcome,
  HeadlineMetricSeries,
  PositionRegistryRow,
  ResearchOverview,
} from "../../lib/ledger-client.types";
import { ResearchOverviewCard } from "./ResearchOverviewCard";
import { ExperimentsTable } from "./ExperimentsTable";
import { HeadlineMetricSparkline } from "./HeadlineMetricSparkline";
import { UserSelector } from "./UserSelector";

interface RefreshResponse {
  ok: boolean;
  overview: ResearchOverview;
  registry: PositionRegistryRow[];
  experiments: ExperimentRow[];
  history: HeadlineMetricSeries | null;
  fetchedAt: number;
}

export interface ResearchViewProps {
  initialOverview: ResearchOverview;
  initialRegistry: PositionRegistryRow[];
  initialExperiments: ExperimentRow[];
  initialPersonId: string | null;
  initialPosition: string | null;
  initialHistory: HeadlineMetricSeries | null;
}

export function ResearchView({
  initialOverview,
  initialRegistry,
  initialExperiments,
  initialPersonId,
  initialPosition,
  initialHistory,
}: ResearchViewProps) {
  const [personId, setPersonId] = useState<string | null>(initialPersonId);
  const [position, setPosition] = useState<string | null>(initialPosition);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (personId) params.set("personId", personId);
    if (position) params.set("position", position);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [personId, position]);

  const fetcher = useCallback(async (): Promise<RefreshResponse> => {
    const r = await fetch(`/api/research/refresh${queryString}`, {
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`refresh failed: ${r.status}`);
    return r.json() as Promise<RefreshResponse>;
  }, [queryString]);

  const { data, lastTickAt } = usePoll<RefreshResponse>(fetcher, {
    intervalMs: 10_000,
    initial: {
      ok: true,
      overview: initialOverview,
      registry: initialRegistry,
      experiments: initialExperiments,
      history: initialHistory,
      fetchedAt: Date.now(),
    },
  });

  const overview = data?.overview ?? initialOverview;
  const registry = data?.registry ?? initialRegistry;
  const experiments = data?.experiments ?? initialExperiments;
  const history = data?.history ?? initialHistory;

  const handleSelect = useCallback(
    (newPersonId: string | null) => {
      setPersonId(newPersonId);
      const match = registry.find((r) => r.personId === newPersonId);
      setPosition(match?.position ?? null);
    },
    [registry],
  );

  const handleResolve = useCallback(
    async (experimentId: string, outcome: ExperimentOutcome) => {
      try {
        await fetch("/api/research/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ experimentId, outcome }),
        });
      } catch (err) {
        console.warn("resolve failed", err);
      }
    },
    [],
  );

  return (
    <div
      data-testid="research-view"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 32,
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
          Pl. IX · Self-improve per user · live
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Research
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Karpathy autoresearch, role-aware. The worm runs experiments
          tailored to each user's position; wins keep, losses discard. Every
          row is a ledger receipt.
        </p>
        <span
          className="wb-mono"
          data-testid="research-tick"
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          {lastTickAt
            ? `live · last poll ${Math.max(
                0,
                Math.round((Date.now() - lastTickAt) / 1000),
              )}s ago`
            : "live · waiting for first poll"}
        </span>
      </header>

      <ResearchOverviewCard overview={overview} />

      <section
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          borderTop: "1px solid var(--wb-color-rule-line)",
          paddingTop: 24,
        }}
      >
        <UserSelector
          registry={registry}
          selectedPersonId={personId}
          onSelect={handleSelect}
        />
        {position && history ? (
          <HeadlineMetricSparkline series={history} />
        ) : (
          <p
            data-testid="sparkline-empty"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            No headline-metric samples yet for this user.
          </p>
        )}
        <ExperimentsTable
          rows={experiments}
          onResolve={handleResolve}
          filteringByPerson={Boolean(personId)}
        />
      </section>
    </div>
  );
}
