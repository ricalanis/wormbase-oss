/**
 * Phase D3 (WhatsApp first-class) — `getConversationSyncs` +
 * `getChatReceivedForChannel` projection tests.
 *
 * Strategy: mock the `pg` module so we can drive controlled ledger rows
 * through both accessors. These tests pin the fold semantics — the SQL
 * itself is exercised by the existing Postgres-path tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90"; // baseworm
const CHANNEL_WHATSAPP = "5511999998888@s.whatsapp.net";
const CHANNEL_SLACK = "C0AV1234567";
const SYNC_A = "11111111-1111-1111-1111-111111111111";
const SYNC_B = "22222222-2222-2222-2222-222222222222";
const SYNC_C = "33333333-3333-3333-3333-333333333333";

interface FakeRow {
  seq: number;
  ts: Date;
  args: Record<string, unknown>;
  hash_hex: string;
}

let __seq = 0;
function syncRow(args: Record<string, unknown>, ts: string): FakeRow {
  __seq += 1;
  return {
    seq: __seq,
    ts: new Date(ts),
    args,
    hash_hex: "0".repeat(56) + __seq.toString(16).padStart(8, "0"),
  };
}

describe("getConversationSyncs (Phase D3)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    __seq = 0;
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns [] when no conversation_sync entries exist (empty-state)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("folds one execute entry per sync_id into one row", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            install_id: "inst-1",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T19:30:00Z",
            completed_at: "2026-05-06T19:31:00Z",
            message_count: 50,
            earliest_ts: "2026-05-06T18:00:00Z",
            latest_ts: "2026-05-06T19:29:00Z",
            status: "completed",
          },
          "2026-05-06T19:31:00Z",
        ),
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].syncId).toBe(SYNC_A);
    expect(rows[0].platform).toBe("whatsapp");
    expect(rows[0].trigger).toBe("reconnect");
    expect(rows[0].status).toBe("completed");
    expect(rows[0].messageCount).toBe(50);
    expect(rows[0].channelIds).toEqual([CHANNEL_WHATSAPP]);
    expect(rows[0].installId).toBe("inst-1");
    expect(rows[0].startedAt).toBe("2026-05-06T19:30:00.000Z");
    expect(rows[0].completedAt).toBe("2026-05-06T19:31:00.000Z");
  });

  it("collapses repeat executes for the same sync_id (latest wins)", async () => {
    // The PEVR write surface emits an execute for each transition; the
    // ``in_progress → completed`` transition writes a fresh execute. Fold
    // semantics keep the most-recent one.
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T19:30:00Z",
            message_count: 10,
            status: "in_progress",
          },
          "2026-05-06T19:30:30Z",
        ),
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T19:30:00Z",
            completed_at: "2026-05-06T19:31:00Z",
            message_count: 50,
            status: "completed",
          },
          "2026-05-06T19:31:00Z",
        ),
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe("completed");
    expect(rows[0].messageCount).toBe(50);
  });

  it("sorts results descending by started_at", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "initial_connect",
            started_at: "2026-05-06T10:00:00Z",
            completed_at: "2026-05-06T10:01:00Z",
            message_count: 1,
            status: "completed",
          },
          "2026-05-06T10:01:00Z",
        ),
        syncRow(
          {
            sync_id: SYNC_B,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T20:00:00Z",
            completed_at: "2026-05-06T20:01:00Z",
            message_count: 5,
            status: "completed",
          },
          "2026-05-06T20:01:00Z",
        ),
        syncRow(
          {
            sync_id: SYNC_C,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T15:00:00Z",
            message_count: 2,
            status: "in_progress",
          },
          "2026-05-06T15:00:00Z",
        ),
      ],
      rowCount: 3,
    });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows.map((r) => r.syncId)).toEqual([SYNC_B, SYNC_C, SYNC_A]);
  });

  it("filters by channelId — only syncs whose channels include it survive", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T19:00:00Z",
            message_count: 7,
            status: "completed",
          },
          "2026-05-06T19:00:00Z",
        ),
        syncRow(
          {
            sync_id: SYNC_B,
            platform: "slack",
            channels: [CHANNEL_SLACK, "C0BV0000001"],
            trigger: "initial_connect",
            started_at: "2026-05-06T20:00:00Z",
            message_count: 99,
            status: "completed",
          },
          "2026-05-06T20:00:00Z",
        ),
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/ledger-client");
    const whatsappOnly = await mod.getConversationSyncs(
      COMPANY_ID,
      CHANNEL_WHATSAPP,
    );
    expect(whatsappOnly).toHaveLength(1);
    expect(whatsappOnly[0].syncId).toBe(SYNC_A);
  });

  it("rejects rows with missing sync_id (defensive)", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            // sync_id missing
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "reconnect",
            started_at: "2026-05-06T19:30:00Z",
            message_count: 0,
            status: "in_progress",
          },
          "2026-05-06T19:30:00Z",
        ),
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows).toEqual([]);
  });

  it("falls back to in_progress / initial_connect on unknown enum values", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        syncRow(
          {
            sync_id: SYNC_A,
            platform: "whatsapp",
            channels: [CHANNEL_WHATSAPP],
            trigger: "garbage_trigger",
            started_at: "2026-05-06T19:30:00Z",
            message_count: 0,
            status: "garbage_status",
          },
          "2026-05-06T19:30:00Z",
        ),
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/ledger-client");
    const rows = await mod.getConversationSyncs(COMPANY_ID);
    expect(rows).toHaveLength(1);
    expect(rows[0].trigger).toBe("initial_connect");
    expect(rows[0].status).toBe("in_progress");
  });
});

describe("getChatReceivedForChannel (Phase D3)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
    __seq = 0;
    vi.resetModules();
    queryMock.mockReset();
    releaseMock.mockReset();
    connectMock.mockClear();
    onMock.mockClear();
    process.env.DATABASE_URL = "postgresql://test:test@localhost:5432/test";

    vi.doMock("pg", () => {
      class Pool {
        connect = connectMock;
        on = onMock;
        constructor(_opts: unknown) {}
      }
      return { default: { Pool }, Pool };
    });
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
    vi.doUnmock("pg");
  });

  it("returns [] when no chat_received rows exist for the channel", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const messages = await mod.getChatReceivedForChannel(
      COMPANY_ID,
      CHANNEL_WHATSAPP,
    );
    expect(messages).toEqual([]);
  });

  it("threads channelId as $2 in the SQL params", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          ts: new Date("2026-05-06T20:00:00Z"),
          channel_id: CHANNEL_WHATSAPP,
          sender_person: "11111111-1111-1111-1111-111111111111",
          text: "hello world",
          classification: "internal",
          hash_hex: "abcdef0123456789".repeat(4),
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/ledger-client");
    const messages = await mod.getChatReceivedForChannel(
      COMPANY_ID,
      CHANNEL_WHATSAPP,
    );
    expect(messages).toHaveLength(1);
    expect(messages[0].text).toBe("hello world");
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [, params] = queryMock.mock.calls[0];
    expect(params).toEqual([COMPANY_ID, CHANNEL_WHATSAPP]);
  });

  it("appends history_sync_id as $3 when filter is provided", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    await mod.getChatReceivedForChannel(COMPANY_ID, CHANNEL_WHATSAPP, {
      historySyncId: SYNC_A,
    });
    expect(queryMock).toHaveBeenCalledTimes(1);
    const [sql, params] = queryMock.mock.calls[0];
    expect(params).toEqual([COMPANY_ID, CHANNEL_WHATSAPP, SYNC_A]);
    expect(String(sql)).toContain("history_sync_id");
    expect(String(sql)).toContain("$3");
  });

  it("does NOT include the history_sync_id clause when filter is omitted", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    await mod.getChatReceivedForChannel(COMPANY_ID, CHANNEL_WHATSAPP);
    const [sql] = queryMock.mock.calls[0];
    expect(String(sql)).not.toContain("history_sync_id");
  });

  it("clamps the limit to a sane upper bound", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    await mod.getChatReceivedForChannel(COMPANY_ID, CHANNEL_WHATSAPP, {
      limit: 9999,
    });
    const [sql] = queryMock.mock.calls[0];
    // Upper bound is 500.
    expect(String(sql)).toMatch(/LIMIT 500/);
  });
});
