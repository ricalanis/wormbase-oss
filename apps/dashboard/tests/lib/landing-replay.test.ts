/**
 * Phase 4 Task 4B — landing replay server helper.
 *
 * Verifies that ``getLandingReplay`` produces a deterministic, hash-stable
 * payload suitable for the above-the-fold replay viewer. The helper reads
 * a fixed ``until_ts`` window of ledger entries from the canonical demo
 * tenant (``baseworm``) — chat-received / chat-sent / propose / execute
 * etc. — and renders them as Slack-thread-style messages with hash
 * receipts.
 *
 * Determinism contract (institutional-AI thesis):
 *
 *   - Same ``until_ts`` + same ledger state → identical payload (entries
 *     in identical order, identical hashShorts, identical terminalHashHex).
 *   - Calling the helper twice in succession yields byte-equal payload.
 *
 * The helper falls back to a deterministic synthesised payload derived
 * from ``TRACE_ENTRIES`` when Postgres is unreachable or the ledger has
 * no demo-tenant entries yet — same hash semantics, same determinism.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { pgQueryMock } = vi.hoisted(() => ({ pgQueryMock: vi.fn() }));

vi.mock("../../lib/ledger-client", async () => {
  const actual: Record<string, unknown> = await vi.importActual(
    "../../lib/ledger-client",
  );
  return {
    ...actual,
    pgQuery: pgQueryMock,
  };
});

import {
  getLandingReplay,
  LANDING_REPLAY_DEMO_SLUG,
  LANDING_REPLAY_UNTIL_TS,
} from "../../lib/server/landing-replay";

describe("landing-replay helper", () => {
  beforeEach(() => {
    pgQueryMock.mockReset();
    delete process.env.DATABASE_URL;
    delete process.env.WORMBASE_LEDGER_DSN;
  });

  afterEach(() => {
    pgQueryMock.mockReset();
  });

  it("uses the canonical demo tenant slug + a fixed ``until_ts`` anchor", () => {
    expect(LANDING_REPLAY_DEMO_SLUG).toBe("baseworm");
    // Fixed anchor — never floats. The hash-stability promise depends on
    // this being constant across SSR invocations.
    expect(LANDING_REPLAY_UNTIL_TS).toMatch(/^20\d{2}-\d{2}-\d{2}T/);
  });

  it("returns a deterministic payload when DB is unavailable (fixture path)", async () => {
    const a = await getLandingReplay();
    const b = await getLandingReplay();
    expect(a).toEqual(b);
    expect(a.tenantSlug).toBe(LANDING_REPLAY_DEMO_SLUG);
    expect(a.untilTs).toBe(LANDING_REPLAY_UNTIL_TS);
    expect(a.entries.length).toBeGreaterThanOrEqual(3);
    expect(a.terminalHashHex).toMatch(/^[0-9a-f]{12,}$/);
  });

  it("renders Slack-thread-style entries with hash receipts (every row has `hashShort`)", async () => {
    const replay = await getLandingReplay();
    for (const entry of replay.entries) {
      expect(entry.hashShort).toMatch(/^[0-9a-f]{8,}$/);
      expect(typeof entry.who).toBe("string");
      expect(typeof entry.body).toBe("string");
      expect(["actor", "worm", "system"]).toContain(entry.role);
    }
  });

  it("entries are ordered by ts ascending (Slack-thread chronology)", async () => {
    const replay = await getLandingReplay();
    const tsList = replay.entries.map((e) => Date.parse(e.ts));
    const sorted = [...tsList].sort((a, b) => a - b);
    expect(tsList).toEqual(sorted);
  });

  it("marks `stop=end_of_data` so the client renders an honest stop-state", async () => {
    const replay = await getLandingReplay();
    expect(replay.stop).toBe("end_of_data");
  });

  it("reads from the ledger when DATABASE_URL is set + rows exist", async () => {
    process.env.DATABASE_URL = "postgres://noop";
    pgQueryMock.mockImplementation(async (sql: string) => {
      // Return one chat_received + one chat_sent row.
      if (/FROM ledger/.test(sql)) {
        return {
          rows: [
            {
              seq: 1,
              ts: new Date("2026-04-30T08:00:00Z"),
              kind: "execute",
              tool: "channel_adapter.emit_chat_received",
              args: {
                channel_id: "C_DEMO",
                sender_person: "p_bob_aaaa",
                text: "@worm here is sales-q3.csv — can you reconcile?",
                classification: "internal",
              },
              hash_hex:
                "deadbeefcafebabe1234567890abcdef0123456789abcdef0123456789abcdef",
            },
            {
              seq: 2,
              ts: new Date("2026-04-30T08:00:01Z"),
              kind: "execute",
              tool: "channel_adapter.emit_chat_sent",
              args: {
                channel_id: "C_DEMO",
                text: "Profiled. 4 tables proposed; bronze layer ready.",
                classification: "internal",
              },
              hash_hex:
                "abadbabe11111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
          ],
        };
      }
      return { rows: [] };
    });

    const replay = await getLandingReplay();
    expect(replay.entries.length).toBe(2);
    // chat_received → role 'actor'; chat_sent → role 'worm'.
    expect(replay.entries[0].role).toBe("actor");
    expect(replay.entries[1].role).toBe("worm");
    // Hash short is the leading 12 hex chars of the row's hash_hex.
    expect(replay.entries[0].hashShort).toBe("deadbeefcafe");
    expect(replay.entries[1].hashShort).toBe("abadbabe1111");
  });

  it("falls back to fixture path when ledger query throws", async () => {
    process.env.DATABASE_URL = "postgres://noop";
    pgQueryMock.mockRejectedValue(new Error("ECONNREFUSED"));
    const a = await getLandingReplay();
    const b = await getLandingReplay();
    expect(a).toEqual(b);
    expect(a.entries.length).toBeGreaterThanOrEqual(3);
  });
});
