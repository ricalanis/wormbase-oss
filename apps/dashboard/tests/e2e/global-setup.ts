/**
 * Global setup (W6.A5).
 *
 * Invariant: the E2E + visual suites are only meaningful when the dashboard
 * is reachable and the worm-core stack is hot. We probe the dashboard's
 * `/api/v1/ops/health` proxy (which itself fans out to worm-core) and write
 * a sentinel file the per-test fixtures consult. When the probe fails the
 * fixture short-circuits each test with `test.skip(...)` and an honest
 * message — no flaky timeout, no false-positive screenshot.
 *
 * Override knob: `WORMBASE_HARNESS_UP=1` skips the probe entirely. The
 * operator drove `make tutorial` and knows the stack is up; we trust them.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import type { FullConfig } from "@playwright/test";

const SENTINEL_DIR = ".playwright-state";
const SENTINEL_FILE = "harness.json";

interface HarnessSentinel {
  reachable: boolean;
  baseUrl: string;
  reason: string;
  probedAt: string;
}

async function probeHealth(baseUrl: string): Promise<HarnessSentinel> {
  if (process.env.WORMBASE_HARNESS_UP === "1") {
    return {
      reachable: true,
      baseUrl,
      reason: "WORMBASE_HARNESS_UP=1 (operator-asserted)",
      probedAt: new Date().toISOString(),
    };
  }
  const url = `${baseUrl.replace(/\/+$/, "")}/api/v1/ops/health`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5_000);
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    clearTimeout(timer);
    // 200 — fully up. 502/503 — dashboard up but worm-core down; we still
    // want to run the dashboard-only specs. 401 — dashboard up but tenant
    // cookie missing (ok, fixtures plant one). Anything else (network err,
    // 404) → unreachable.
    const tolerant = [200, 401, 502, 503];
    return {
      reachable: tolerant.includes(res.status),
      baseUrl,
      reason: `health probe → ${res.status}`,
      probedAt: new Date().toISOString(),
    };
  } catch (err) {
    return {
      reachable: false,
      baseUrl,
      reason: err instanceof Error ? err.message : String(err),
      probedAt: new Date().toISOString(),
    };
  }
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseUrl =
    process.env.WORMBASE_DASHBOARD_URL ??
    config.projects[0]?.use?.baseURL ??
    "http://localhost:3000";

  const sentinel = await probeHealth(baseUrl);
  mkdirSync(SENTINEL_DIR, { recursive: true });
  writeFileSync(
    join(SENTINEL_DIR, SENTINEL_FILE),
    JSON.stringify(sentinel, null, 2),
    "utf-8",
  );
  if (!sentinel.reachable) {
     
    console.warn(
      `[playwright global-setup] dashboard not reachable at ${baseUrl}: ` +
        `${sentinel.reason} — specs will skip with a clear message.`,
    );
  } else {
     
    console.log(
      `[playwright global-setup] dashboard reachable: ${sentinel.reason}`,
    );
  }
}

export { SENTINEL_DIR, SENTINEL_FILE };
export type { HarnessSentinel };
