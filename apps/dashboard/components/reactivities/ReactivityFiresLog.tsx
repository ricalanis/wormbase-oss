"use client";
/**
 * ReactivityFiresLog — drilldown of the last N fires for one Reactivity
 * (W5.A5).
 *
 * Mounted inside ReactivityCard when the admin clicks "Show fires".
 * Fetches /api/v1/reactivities/{id}/fires (proxied to worm-core) and
 * renders rows in the editorial wb-mono table style with a deep-link
 * to /trace?kind=emit_reactivity_fired&seq=<seq> for each row.
 *
 * Honest empty: "no fires yet" (rather than a phantom row) when the
 * registry has no fires recorded. Errors fall through as the same
 * empty state with a small inline alert above.
 */

import { useEffect, useState } from "react";
import type { ReactivityFire } from "../../lib/ledger-client.types";

const ROW_STYLE: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 80px 1fr 90px",
  gap: 10,
  padding: "4px 0",
  borderBottom: "1px dashed var(--wb-color-paper-edge)",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  color: "var(--wb-color-aged-ink)",
};

export interface ReactivityFiresLogProps {
  reactivityId: string;
  /** Optional initial rows for tests; production fetches on mount. */
  initialFires?: ReactivityFire[];
  /** Override the default 50; useful for tests. */
  limit?: number;
}

export function ReactivityFiresLog({
  reactivityId,
  initialFires,
  limit = 50,
}: ReactivityFiresLogProps) {
  const [fires, setFires] = useState<ReactivityFire[] | null>(
    initialFires ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialFires !== undefined) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/v1/reactivities/${encodeURIComponent(reactivityId)}/fires?limit=${limit}`,
          { cache: "no-store" },
        );
        if (!res.ok) {
          throw new Error(`fetch failed (${res.status})`);
        }
        const body = (await res.json()) as { fires?: ReactivityFire[] };
        if (cancelled) return;
        setFires(body.fires ?? []);
      } catch (err) {
        if (cancelled) return;
        setError((err as Error).message);
        setFires([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reactivityId, limit, initialFires]);

  if (fires === null) {
    return (
      <div
        data-testid={`reactivity-fires-loading-${reactivityId}`}
        className="wb-mono"
        style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
      >
        Loading fires…
      </div>
    );
  }

  return (
    <section
      data-testid={`reactivity-fires-log-${reactivityId}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginTop: 8,
        padding: "10px 12px",
        background: "var(--wb-color-paper-deep)",
        border: "1px solid var(--wb-color-paper-edge)",
      }}
    >
      <header
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Recent fires · {fires.length}
      </header>
      {error ? (
        <div
          data-testid={`reactivity-fires-error-${reactivityId}`}
          role="alert"
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-sepia-warning-deep)" }}
        >
          {error}
        </div>
      ) : null}
      {fires.length === 0 ? (
        <div
          data-testid={`reactivity-fires-empty-${reactivityId}`}
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            fontStyle: "italic",
          }}
        >
          no fires yet
        </div>
      ) : (
        <div
          style={{
            ...ROW_STYLE,
            color: "var(--wb-color-hash-gray)",
            fontWeight: 600,
            borderBottom: "1px solid var(--wb-color-aged-ink)",
          }}
        >
          <span>seq</span>
          <span>source</span>
          <span>budget</span>
          <span>ts</span>
        </div>
      )}
      {fires.map((fire) => (
        <div
          key={fire.seq}
          data-testid={`reactivity-fire-row-${fire.seq}`}
          style={ROW_STYLE}
        >
          <a
            href={`/trace?kind=emit_reactivity_fired&seq=${fire.seq}`}
            style={{
              color: "var(--wb-color-botanical-green-deep)",
              textDecoration: "none",
            }}
          >
            #{fire.seq}
          </a>
          <span data-testid={`reactivity-fire-source-${fire.seq}`}>
            #{fire.sourceSeq}
          </span>
          <span data-testid={`reactivity-fire-budget-${fire.seq}`}>
            {Object.entries(fire.budgetUsed)
              .map(([k, v]) => `${k}=${v}`)
              .join(" · ") || "(none)"}
          </span>
          <span style={{ color: "var(--wb-color-hash-gray)" }}>
            {fire.ts.slice(11, 19)}
          </span>
        </div>
      ))}
    </section>
  );
}
