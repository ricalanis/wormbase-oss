/**
 * WS5 S3 — getTopics fold.
 *
 * Strategy: mock the `pg` module to drive controlled rows through
 * `getTopics`. Verifies the cluster-by-channel + naive-keyword fold
 * yields the expected message counts, top participants, latest excerpts,
 * and ordering.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

interface FakeChatRow {
  channel_id: string;
  channel_name: string;
  text: string;
  sender_person: string;
  ts: Date;
}

function chat(
  channelId: string,
  channelName: string,
  text: string,
  senderPerson: string,
  ts = "2026-04-26T10:00:00Z",
): FakeChatRow {
  return {
    channel_id: channelId,
    channel_name: channelName,
    text,
    sender_person: senderPerson,
    ts: new Date(ts),
  };
}

describe("getTopics (WS5 S3)", () => {
  const queryMock = vi.fn();
  const releaseMock = vi.fn();
  const connectMock = vi.fn(async () => ({
    query: queryMock,
    release: releaseMock,
  }));
  const onMock = vi.fn();

  beforeEach(() => {
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

  it("returns [] when no chat rows exist", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics).toEqual([]);
  });

  it("clusters rows by channel and counts messages per cluster", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        // Newest first (DESC by seq) — shape mirrors the real query.
        chat("C-data", "data-eng", "should we double-check the revenue methodology?", "p-alice", "2026-04-26T10:00:00Z"),
        chat("C-data", "data-eng", "I think the revenue numbers look off again", "p-bob", "2026-04-26T09:30:00Z"),
        chat("C-data", "data-eng", "revenue dashboard broken", "p-alice", "2026-04-26T09:00:00Z"),
        chat("C-fin", "finance", "we agreed to push close to Friday", "p-carol", "2026-04-25T14:00:00Z"),
      ],
      rowCount: 4,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics).toHaveLength(2);

    const dataTopic = topics.find((t) => t.channelId === "C-data")!;
    expect(dataTopic).toBeTruthy();
    expect(dataTopic.messageCount).toBe(3);
    expect(dataTopic.channelName).toBe("data-eng");
    // Top keyword should be "revenue" (appears in all three messages, length>=4, not stopword).
    expect(dataTopic.label).toBe("revenue");

    const finTopic = topics.find((t) => t.channelId === "C-fin")!;
    expect(finTopic).toBeTruthy();
    expect(finTopic.messageCount).toBe(1);
  });

  it("orders topics by message count descending", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        chat("C-low", "low", "alpha alpha alpha alpha", "p-1"),
        chat("C-high", "high", "beta beta beta beta", "p-2"),
        chat("C-high", "high", "beta beta beta beta", "p-2"),
        chat("C-high", "high", "beta beta beta beta", "p-2"),
      ],
      rowCount: 4,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics[0].channelId).toBe("C-high");
    expect(topics[1].channelId).toBe("C-low");
  });

  it("surfaces the latest excerpt and trims to ≤140 chars", async () => {
    const longText = "x".repeat(200);
    queryMock.mockResolvedValueOnce({
      rows: [
        chat("C-data", "data-eng", longText, "p-alice", "2026-04-26T10:00:00Z"),
        chat("C-data", "data-eng", "older message", "p-bob", "2026-04-26T09:00:00Z"),
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics).toHaveLength(1);
    expect(topics[0].latestExcerpt.length).toBeLessThanOrEqual(140);
    expect(topics[0].latestExcerpt.endsWith("...")).toBe(true);
  });

  it("returns top participants (≤3) by message count", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        chat("C-data", "data-eng", "msg one", "p-alice"),
        chat("C-data", "data-eng", "msg two", "p-alice"),
        chat("C-data", "data-eng", "msg three", "p-bob"),
        chat("C-data", "data-eng", "msg four", "p-carol"),
        chat("C-data", "data-eng", "msg five", "p-dave"),
      ],
      rowCount: 5,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics).toHaveLength(1);
    expect(topics[0].topPersons.length).toBeLessThanOrEqual(3);
    // Alice has 2 — should be first.
    expect(topics[0].topPersons[0]).toBe("p-alice");
  });

  it("respects the limit parameter", async () => {
    const rows: FakeChatRow[] = [];
    for (let i = 0; i < 30; i++) {
      rows.push(chat(`C-${i}`, `chan-${i}`, `msg in ${i}`, `p-${i}`));
    }
    queryMock.mockResolvedValueOnce({ rows, rowCount: rows.length });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID, 5);
    expect(topics.length).toBeLessThanOrEqual(5);
  });

  it("falls back to the channel id when channel_name is missing", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          channel_id: "C-fallback",
          channel_name: null,
          text: "alpha alpha alpha alpha alpha",
          sender_person: "p-1",
          ts: new Date("2026-04-26T10:00:00Z"),
        },
      ],
      rowCount: 1,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID);
    expect(topics).toHaveLength(1);
    expect(topics[0].channelName).toBe("C-fallback");
  });

  // ── W4-A platform filter ───────────────────────────────────────────────
  //
  // The platform parameter pushes a SQL-side filter on channel_id shape
  // (WhatsApp jids end in @s.whatsapp.net or @g.us; Slack channel ids
  // do not). Pass-through behavior is byte-identical when ``platform`` is
  // undefined.

  it("emits no platform clause when platform is undefined (default)", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    await mod.getTopics(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).not.toContain("@s.whatsapp.net");
    expect(sql).not.toContain("@g.us");
  });

  it("filters to WhatsApp jids when platform=whatsapp", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        chat(
          "521555000@s.whatsapp.net",
          "+521555000",
          "should we double-check the revenue methodology?",
          "p-alice",
          "2026-04-26T10:00:00Z",
        ),
        chat(
          "group-xyz@g.us",
          "team-wa",
          "revenue dashboard broken",
          "p-bob",
          "2026-04-26T09:30:00Z",
        ),
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID, 20, "whatsapp");

    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("@s.whatsapp.net");
    expect(sql).toContain("@g.us");
    expect(sql).not.toContain("NOT LIKE");

    expect(topics).toHaveLength(2);
    const channels = topics.map((t) => t.channelId).sort();
    expect(channels).toEqual(["521555000@s.whatsapp.net", "group-xyz@g.us"]);
  });

  it("excludes WhatsApp jids when platform=slack", async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        chat("C-data", "data-eng", "revenue check now", "p-alice"),
        chat("C-fin", "finance", "close pushed", "p-carol"),
      ],
      rowCount: 2,
    });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID, 20, "slack");

    expect(queryMock).toHaveBeenCalledTimes(1);
    const sql = String(queryMock.mock.calls[0][0]);
    expect(sql).toContain("NOT LIKE '%@s.whatsapp.net'");
    expect(sql).toContain("NOT LIKE '%@g.us'");

    expect(topics).toHaveLength(2);
    const channels = topics.map((t) => t.channelId).sort();
    expect(channels).toEqual(["C-data", "C-fin"]);
  });

  it("returns [] when platform filter yields no rows", async () => {
    queryMock.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    const mod = await import("../../lib/ledger-client");
    const topics = await mod.getTopics(COMPANY_ID, 20, "whatsapp");
    expect(topics).toEqual([]);
  });
});

describe("inferPlatformFromChannelId (W4-A)", () => {
  it("classifies WhatsApp DM jids as whatsapp", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.inferPlatformFromChannelId("521555000@s.whatsapp.net")).toBe(
      "whatsapp",
    );
  });

  it("classifies WhatsApp group jids as whatsapp", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.inferPlatformFromChannelId("121231-12@g.us")).toBe("whatsapp");
  });

  it("classifies Slack-shaped channel ids as slack", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.inferPlatformFromChannelId("C0123ABCD")).toBe("slack");
    expect(mod.inferPlatformFromChannelId("D012ABCDEF")).toBe("slack");
  });

  it("returns undefined for missing/null/empty channel ids", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.inferPlatformFromChannelId(null)).toBeUndefined();
    expect(mod.inferPlatformFromChannelId(undefined)).toBeUndefined();
    expect(mod.inferPlatformFromChannelId("")).toBeUndefined();
  });

  it("returns undefined for unknown shapes (forward-compat)", async () => {
    const mod = await import("../../lib/ledger-client");
    expect(mod.inferPlatformFromChannelId("unknown-shape")).toBeUndefined();
  });
});
