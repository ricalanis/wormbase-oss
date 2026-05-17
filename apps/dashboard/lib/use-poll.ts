"use client";
/**
 * usePoll — minimal polling hook for live dashboard surfaces.
 *
 * The dashboard is the demo's show-window. Steps 3a + 3b of the canonical
 * 5-step product arc want viewers to SEE the worm working — the KPI tree
 * gaining nodes, governance picking up resources, classification flipping —
 * without manual reloads. This hook is the "live polling makes the worm feel
 * alive" effect. Keep it tiny so any client component can opt in:
 *
 *     const { data, error, lastTickAt } = usePoll(
 *       () => fetch("/api/kpi-tree/refresh").then((r) => r.json()),
 *       { intervalMs: 5000, initial: serverData }
 *     );
 *
 * Design choices:
 * - Server-actions friendly: the fn argument is a plain async () => T, so
 *   either fetch() against a route handler OR a server action wrapped in a
 *   client-side caller works.
 * - Pause on `document.hidden` — no point polling while the demo tab is
 *   backgrounded; resumes on visibilitychange.
 * - One in-flight request at a time. If a previous tick is still fetching
 *   when the next interval fires, we skip — tested behaviour for slow
 *   Postgres reads during demo recovery.
 * - `lastTickAt` is exposed so the UI can render "live · 2s ago" badges that
 *   make the polling visible to the audience.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface UsePollOptions<T> {
  intervalMs: number;
  initial?: T;
  /** Skip polling entirely (e.g. when the panel is collapsed). */
  paused?: boolean;
}

export interface UsePollResult<T> {
  data: T | undefined;
  error: Error | null;
  lastTickAt: number | null;
  refresh: () => Promise<void>;
}

export function usePoll<T>(
  fn: () => Promise<T>,
  opts: UsePollOptions<T>,
): UsePollResult<T> {
  const { intervalMs, initial, paused = false } = opts;
  const [data, setData] = useState<T | undefined>(initial);
  const [error, setError] = useState<Error | null>(null);
  const [lastTickAt, setLastTickAt] = useState<number | null>(null);

  // Hold the latest fn/paused in a ref so the long-lived interval closure
  // doesn't capture stale values. This keeps us to a single setInterval
  // across the lifetime of the component.
  const fnRef = useRef(fn);
  const pausedRef = useRef(paused);
  const inFlightRef = useRef(false);

  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const tick = useCallback(async () => {
    if (pausedRef.current) return;
    if (typeof document !== "undefined" && document.hidden) return;
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const next = await fnRef.current();
      setData(next);
      setError(null);
      setLastTickAt(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  // Initial tick + interval. `paused` is a ref check inside `tick`, so we
  // don't restart the interval on pause flips.
  useEffect(() => {
    void tick();
    const id = setInterval(() => {
      void tick();
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, tick]);

  // Wake-on-focus: when the demo tab returns to foreground, refresh
  // immediately so audience-visible state is current.
  useEffect(() => {
    const onVis = () => {
      if (typeof document !== "undefined" && !document.hidden) void tick();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVis);
      return () => document.removeEventListener("visibilitychange", onVis);
    }
    return;
  }, [tick]);

  return { data, error, lastTickAt, refresh: tick };
}
