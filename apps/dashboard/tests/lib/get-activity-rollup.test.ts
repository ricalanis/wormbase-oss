/**
 * W4-C — getActivityRollup accessor.
 *
 * Strategy: mock the `pg` module to drive controlled rows through
 * `getActivityRollup`. Verifies:
 *
 *   - chat_received entries grouped by inferPlatformFromChannelId fold
 *   - process_map_proposed + kpi_proposed counts surface as separate fields
 *   - per-platform sort is count DESC; ties broken by canonical PLATFORMS order
 *   - zero-count platforms are OMITTED (not rendered as 0)
 *   - isSilent=true when every counter is 0 (honest empty state)
 *   - 24h interval clause makes it into the SQL
 *   - windowSeconds is bounded
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

describe("getActivityRollup (W4-C)", () => {
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

  it("returns an honest-empty (isSilent) rollup when no rows exist", async () => {
    // Three queries: chat, process-maps, kpis. All empty.
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.isSilent).toBe(true);
    expect(r.totalMessages).toBe(0);
    expect(r.processMaps).toBe(0);
    expect(r.kpiProposals).toBe(0);
    expect(r.perPlatform).toEqual([]);
  });

  it("groups chat_received rows by inferred platform", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          { channel_id: "C0FINANCE", n: 8 },
          { channel_id: "C0DATAENG", n: 4 },
          { channel_id: "521555000@s.whatsapp.net", n: 3 },
          { channel_id: "group-xyz@g.us", n: 1 },
        ],
        rowCount: 4,
      })
      .mockResolvedValueOnce({ rows: [{ n: 1 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);

    expect(r.isSilent).toBe(false);
    expect(r.totalMessages).toBe(16);
    expect(r.perPlatform).toHaveLength(2);

    const slack = r.perPlatform.find((p) => p.platform === "slack");
    const wa = r.perPlatform.find((p) => p.platform === "whatsapp");
    expect(slack?.count).toBe(12);
    expect(slack?.unitLabel).toBe("messages");
    expect(wa?.count).toBe(4);
    expect(wa?.unitLabel).toBe("DMs");

    expect(r.processMaps).toBe(1);
    expect(r.kpiProposals).toBe(0);
  });

  it("orders per-platform by count DESC", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          { channel_id: "C0FINANCE", n: 4 },
          { channel_id: "521555000@s.whatsapp.net", n: 7 },
        ],
        rowCount: 2,
      })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.perPlatform.map((p) => p.platform)).toEqual(["whatsapp", "slack"]);
  });

  it("omits zero-count platforms (Slack-only deployment stays clean)", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [{ channel_id: "C0FINANCE", n: 12 }],
        rowCount: 1,
      })
      .mockResolvedValueOnce({ rows: [{ n: 1 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    // No WhatsApp segment; only Slack.
    expect(r.perPlatform).toHaveLength(1);
    expect(r.perPlatform[0].platform).toBe("slack");
    // WhatsApp is not present at all (omitted, not rendered as 0).
    expect(r.perPlatform.find((p) => p.platform === "whatsapp")).toBeUndefined();
  });

  it("counts unknown-shape channel ids toward totalMessages but omits the platform", async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          { channel_id: "C0DATAENG", n: 5 },
          { channel_id: "weird-shape-id", n: 7 },
        ],
        rowCount: 2,
      })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.totalMessages).toBe(12);
    expect(r.perPlatform).toHaveLength(1);
    expect(r.perPlatform[0].platform).toBe("slack");
    expect(r.perPlatform[0].count).toBe(5);
  });

  it("uses NOW() - INTERVAL filter in the SQL", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    await mod.getActivityRollup(COMPANY_ID);
    expect(queryMock).toHaveBeenCalledTimes(3);
    const chatSql = String(queryMock.mock.calls[0][0]);
    expect(chatSql).toContain("NOW()");
    expect(chatSql).toContain("interval");
    // chat tool is filtered to chat_received variants.
    expect(chatSql).toContain("emit_chat_received");
  });

  it("default windowSeconds is 24h (86400)", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.windowSeconds).toBe(86400);
    // The interval param is the second SQL bind on every aggregate.
    const params = queryMock.mock.calls[0][1];
    expect(params[1]).toBe("86400");
  });

  it("respects an explicit windowSeconds", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID, { windowSeconds: 3600 });
    expect(r.windowSeconds).toBe(3600);
    expect(queryMock.mock.calls[0][1][1]).toBe("3600");
  });

  it("clamps absurdly large windows", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID, {
      windowSeconds: 10_000_000_000,
    });
    // Capped at 30d.
    expect(r.windowSeconds).toBe(30 * 24 * 60 * 60);
  });

  it("clamps absurdly small windows", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID, { windowSeconds: 1 });
    // Floored at 60s.
    expect(r.windowSeconds).toBe(60);
  });

  it("isSilent=false when only process maps moved (no chat, no kpi)", async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [], rowCount: 0 })
      .mockResolvedValueOnce({ rows: [{ n: 2 }], rowCount: 1 })
      .mockResolvedValueOnce({ rows: [{ n: 0 }], rowCount: 1 });
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.isSilent).toBe(false);
    expect(r.processMaps).toBe(2);
    expect(r.totalMessages).toBe(0);
  });

  it("returns the empty fallback when DATABASE_URL is unset", async () => {
    delete process.env.DATABASE_URL;
    const mod = await import("../../lib/ledger-client");
    const r = await mod.getActivityRollup(COMPANY_ID);
    expect(r.isSilent).toBe(true);
    expect(r.totalMessages).toBe(0);
    expect(queryMock).not.toHaveBeenCalled();
  });
});
