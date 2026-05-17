"use client";
/**
 * KeepRateChart — per-scope (Person / Team / Company) 7-day keep-rate
 * baseline chart (Demo-day P1).
 *
 * Reads a flat list of `KeepRateSample` rows from
 * `getKeepRateSeries`, groups by scope, and renders one row per
 * scope with a small bar chart. Days carrying `synthetic=true` are
 * tagged with a "synthetic baseline" badge so the chart never lies
 * about its sample size.
 *
 * Empty state: when the publisher has not yet emitted any
 * `metrics_keep_rate_published` entries, the chart renders a brief
 * honest empty message (no fixture fallback per CLAUDE.md ¶9).
 */

import type {
  KeepRateSample,
  KeepRateScope,
} from "../../lib/ledger-client.types";

const SCOPES: ReadonlyArray<KeepRateScope> = ["person", "team", "company"];
const SCOPE_LABEL: Record<KeepRateScope, string> = {
  person: "Person",
  team: "Team",
  company: "Company",
};

const BAR_W = 26;
const BAR_GAP = 6;
const BAR_H = 56;

export interface KeepRateChartProps {
  rows: KeepRateSample[];
}

export function KeepRateChart({ rows }: KeepRateChartProps) {
  const hasRows = rows.length > 0;

  // Group by scope; keep day order ascending.
  const byScope = new Map<KeepRateScope, KeepRateSample[]>();
  for (const r of rows) {
    if (!byScope.has(r.scope)) byScope.set(r.scope, []);
    byScope.get(r.scope)!.push(r);
  }
  for (const arr of byScope.values()) {
    arr.sort((a, b) => a.day.localeCompare(b.day));
  }

  return (
    <section
      data-testid="keep-rate-chart"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderTop: "1px solid var(--wb-color-rule-line)",
        paddingTop: 24,
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
          Pl. IX.c · keep-rate baseline · trailing 7d · per-scope
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
          Keep-rate baseline
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Per-scope nightly publication: kept / total over 24h. Days with
          fewer than 3 resolutions are tagged synthetic — the chart still
          renders the ratio, but the badge makes the small sample explicit.
        </p>
      </header>

      {!hasRows ? (
        <p
          data-testid="keep-rate-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No keep-rate publications yet. The nightly publisher writes
          per-scope rows once experiments resolve.
        </p>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 18,
          }}
        >
          {SCOPES.map((scope) => {
            const samples = byScope.get(scope) ?? [];
            return (
              <div
                key={scope}
                data-testid={`keep-rate-row-${scope}`}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                  }}
                >
                  <strong
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-aged-ink)",
                    }}
                  >
                    {SCOPE_LABEL[scope]}
                  </strong>
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    {samples.length} d
                  </span>
                </div>
                {samples.length === 0 ? (
                  <p
                    data-testid={`keep-rate-row-${scope}-empty`}
                    style={{
                      margin: 0,
                      fontFamily: "var(--wb-font-serif)",
                      fontStyle: "italic",
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    No published rows for this scope.
                  </p>
                ) : (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "row",
                      alignItems: "flex-end",
                      gap: BAR_GAP,
                      height: BAR_H + 24,
                    }}
                  >
                    {samples.map((s) => {
                      const h = Math.max(2, BAR_H * Math.max(0, Math.min(1, s.ratio)));
                      return (
                        <figure
                          key={`${scope}-${s.day}`}
                          data-testid={`keep-rate-bar-${scope}-${s.day}`}
                          data-synthetic={s.synthetic ? "true" : "false"}
                          style={{
                            margin: 0,
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            gap: 2,
                            width: BAR_W,
                          }}
                        >
                          <div
                            style={{
                              width: BAR_W,
                              height: BAR_H,
                              display: "flex",
                              alignItems: "flex-end",
                            }}
                          >
                            <div
                              style={{
                                width: BAR_W,
                                height: h,
                                background: s.synthetic
                                  ? "var(--wb-color-rule-line)"
                                  : "var(--wb-color-botanical-green-deep, #4a6b3a)",
                                opacity: s.synthetic ? 0.55 : 1,
                              }}
                              title={`${SCOPE_LABEL[scope]} · ${s.day} · ${s.kept}/${s.total} = ${(s.ratio * 100).toFixed(0)}%${s.synthetic ? " (synthetic)" : ""}`}
                            />
                          </div>
                          <figcaption
                            className="wb-mono"
                            style={{
                              fontSize: 8,
                              letterSpacing: "0.04em",
                              color: "var(--wb-color-hash-gray)",
                            }}
                          >
                            {s.day.slice(5)}
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                )}
                {samples.some((s) => s.synthetic) && (
                  <span
                    data-testid={`keep-rate-synthetic-badge-${scope}`}
                    className="wb-mono"
                    style={{
                      alignSelf: "flex-start",
                      fontSize: 9,
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-hash-gray)",
                      padding: "2px 6px",
                      border: "1px dashed var(--wb-color-rule-line)",
                    }}
                  >
                    synthetic baseline
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
