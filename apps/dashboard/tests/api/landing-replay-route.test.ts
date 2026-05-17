/**
 * Phase 4 Task 4B — landing replay API contract.
 *
 * The landing-page hero replay is server-side rendered, but the
 * "Replay again" button in the client refetches the same payload to
 * demonstrate hash-stability across re-runs. This contract test pins
 * the GET handler at ``/api/v1/landing/replay``: same payload twice,
 * matching the helper's output, no auth required (the landing page is
 * pre-signup).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getLandingReplayMock = vi.fn();

vi.mock("../../lib/server/landing-replay", () => ({
  getLandingReplay: getLandingReplayMock,
  LANDING_REPLAY_DEMO_SLUG: "baseworm",
  LANDING_REPLAY_UNTIL_TS: "2026-04-30T09:00:00Z",
}));

describe("/api/v1/landing/replay", () => {
  beforeEach(() => {
    getLandingReplayMock.mockReset();
  });

  afterEach(() => {
    getLandingReplayMock.mockReset();
  });

  it("GET returns the helper payload as JSON", async () => {
    const payload = {
      tenantSlug: "baseworm",
      companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
      untilTs: "2026-04-30T09:00:00Z",
      terminalHashHex: "abc123def456",
      entries: [
        {
          id: "e_0001",
          ts: "2026-04-30T08:00:00Z",
          who: "Bob",
          role: "actor" as const,
          body: "hello worm",
          kind: "chat_received",
          hashShort: "deadbeefcafe",
        },
      ],
      stop: "end_of_data" as const,
    };
    getLandingReplayMock.mockResolvedValue(payload);

    const { GET } = await import("../../app/api/v1/landing/replay/route");
    const res = await GET(new Request("http://localhost/api/v1/landing/replay"));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual(payload);
  });

  it("GET returns identical payload on consecutive calls (hash-stable)", async () => {
    const payload = {
      tenantSlug: "baseworm",
      companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
      untilTs: "2026-04-30T09:00:00Z",
      terminalHashHex: "abc123def456",
      entries: [],
      stop: "end_of_data" as const,
    };
    getLandingReplayMock.mockResolvedValue(payload);

    const { GET } = await import("../../app/api/v1/landing/replay/route");

    const r1 = await (await GET(
      new Request("http://localhost/api/v1/landing/replay"),
    )).json();
    const r2 = await (await GET(
      new Request("http://localhost/api/v1/landing/replay"),
    )).json();
    expect(r1).toEqual(r2);
  });
});
