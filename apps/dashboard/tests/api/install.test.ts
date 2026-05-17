/**
 * OAuth start + callback route-handler tests.
 *
 * Covers:
 *   - GET /onboarding/oauth/slack/start — env-set + env-unset paths,
 *     state cookie set, redirect URL has correct scopes.
 *   - GET /onboarding/oauth/slack/callback — state mismatch, missing
 *     code, happy-path code-exchange (Slack APIs mocked), worm-core
 *     install API failure surfaces as an error redirect.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Module mocks. The callback handler imports cookies() and completeInstall;
// we mock both so the tests stay hermetic.
// ---------------------------------------------------------------------------

const completeInstallMock = vi.fn();

vi.mock("../../lib/server/install", () => ({
  completeInstall: completeInstallMock,
}));

const cookieMap = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => {
      const v = cookieMap.get(name);
      return v ? { name, value: v } : undefined;
    },
  })),
}));

beforeEach(() => {
  vi.clearAllMocks();
  cookieMap.clear();
  delete process.env.SLACK_CLIENT_ID;
  delete process.env.SLACK_CLIENT_SECRET;
  delete process.env.WORMBASE_DASHBOARD_URL;
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

interface Ctx {
  params: Promise<{ platform: string }>;
}

function ctxFor(platform: string): Ctx {
  return { params: Promise.resolve({ platform }) };
}

// ---------------------------------------------------------------------------
// Start handler
// ---------------------------------------------------------------------------

describe("GET /onboarding/oauth/[platform]/start", () => {
  it("redirects to /onboarding with config error when SLACK_CLIENT_ID is unset", async () => {
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/start",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding");
    expect(location).toContain("error=slack_not_configured");
    expect(location).toContain("SLACK_CLIENT_ID");
  });

  it("redirects to slack.com authorize URL with state cookie when configured", async () => {
    process.env.SLACK_CLIENT_ID = "test-client-id";
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/start",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("https://slack.com/oauth/v2/authorize");
    expect(location).toContain("client_id=test-client-id");
    expect(location).toContain("state=");
    expect(location).toContain("scope=");
    expect(location).toContain("channels%3Aread");
    expect(location).toContain("user_scope=");
    // State cookie must be set, httpOnly, sameSite=lax.
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("wormbase-oauth-state=");
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("samesite=lax");
  });

  it("returns 400 for an unsupported platform", async () => {
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/nonsense/start",
    );
    const res = await GET(req as never, ctxFor("nonsense"));
    expect(res.status).toBe(400);
  });

  it("for discord without DISCORD_CLIENT_ID, redirects to error", async () => {
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/start/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/discord/start",
    );
    const res = await GET(req as never, ctxFor("discord"));
    expect(res.status).toBe(303);
    expect(res.headers.get("location") ?? "").toContain(
      "error=discord_not_configured",
    );
  });
});

// ---------------------------------------------------------------------------
// Callback handler
// ---------------------------------------------------------------------------

describe("GET /onboarding/oauth/[platform]/callback", () => {
  it("returns 400 when the state cookie is missing", async () => {
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/callback?code=abc&state=xyz",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(400);
    const j = (await res.json()) as { error: string };
    expect(j.error).toBe("state_mismatch");
  });

  it("returns 400 when the state cookie does not match", async () => {
    cookieMap.set("wormbase-oauth-state", "expected-state");
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/callback?code=abc&state=different",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(400);
  });

  it("returns 400 when code is missing", async () => {
    cookieMap.set("wormbase-oauth-state", "S");
    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/callback?state=S",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(400);
    const j = (await res.json()) as { error: string };
    expect(j.error).toBe("missing_code");
  });

  it("happy-path: exchanges code, calls completeInstall, redirects to /onboarding/welcome", async () => {
    process.env.SLACK_CLIENT_ID = "client-id";
    process.env.SLACK_CLIENT_SECRET = "client-secret";
    cookieMap.set("wormbase-oauth-state", "S");

    // Mock the Slack OAuth + users.info responses.
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes("oauth.v2.access")) {
        return new Response(
          JSON.stringify({
            ok: true,
            access_token: "xoxb-bot-token",
            team: { id: "T123", name: "Demo Co" },
            bot_user_id: "UBOT",
            scope: "channels:read,chat:write",
            authed_user: { id: "UCAROL" },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (urlStr.includes("users.info")) {
        return new Response(
          JSON.stringify({
            ok: true,
            user: {
              real_name: "Carol Reyes",
              profile: {
                email: "carol@x.co",
                real_name: "Carol Reyes",
                image_192: "https://avatars.example/c.png",
              },
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      throw new Error(`unexpected fetch: ${urlStr}`);
    });
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    completeInstallMock.mockResolvedValueOnce({
      installId: "install-id-123",
      installerPersonId: "person-id-123",
      oauthGrantRef: "vault://local-dev/install-id-123",
      entryIds: [],
    });

    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/callback?code=abc&state=S",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding/welcome");

    expect(completeInstallMock).toHaveBeenCalledTimes(1);
    const callArg = completeInstallMock.mock.calls[0][0] as {
      tenantSlug: string;
      installerEmail: string;
      installerName: string;
      botToken: string;
      botUserId: string;
      platformUserId: string;
      platform: string;
    };
    expect(callArg.tenantSlug).toBe("slack_team_t123");
    expect(callArg.installerEmail).toBe("carol@x.co");
    expect(callArg.installerName).toBe("Carol Reyes");
    expect(callArg.botToken).toBe("xoxb-bot-token");
    expect(callArg.botUserId).toBe("UBOT");
    expect(callArg.platformUserId).toBe("UCAROL");
    expect(callArg.platform).toBe("slack");
  });

  it("redirects to /onboarding with error when completeInstall throws", async () => {
    process.env.SLACK_CLIENT_ID = "client-id";
    process.env.SLACK_CLIENT_SECRET = "client-secret";
    cookieMap.set("wormbase-oauth-state", "S");

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            ok: true,
            access_token: "xoxb-bot-token",
            team: { id: "T1", name: "Co" },
            bot_user_id: "UBOT",
            scope: "channels:read",
            authed_user: { id: "UC" },
          }),
          { status: 200 },
        ),
      ) as unknown as typeof fetch,
    );

    // First fetch returns OK; second (users.info) also returns OK.
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL | Request) => {
        calls += 1;
        if (calls === 1) {
          return new Response(
            JSON.stringify({
              ok: true,
              access_token: "xoxb-bot-token",
              team: { id: "T1", name: "Co" },
              bot_user_id: "UBOT",
              scope: "channels:read",
              authed_user: { id: "UC" },
            }),
            { status: 200 },
          );
        }
        return new Response(
          JSON.stringify({
            ok: true,
            user: {
              real_name: "X",
              profile: { email: "x@y.co", real_name: "X" },
            },
          }),
          { status: 200 },
        );
      }) as unknown as typeof fetch,
    );

    completeInstallMock.mockRejectedValueOnce(new Error("worm-core unreachable"));

    const { GET } = await import(
      "../../app/onboarding/oauth/[platform]/callback/route"
    );
    const req = new Request(
      "http://localhost:3000/onboarding/oauth/slack/callback?code=abc&state=S",
    );
    const res = await GET(req as never, ctxFor("slack"));
    expect(res.status).toBe(303);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/onboarding");
    expect(location).toContain("error=oauth_callback_failed");
    expect(location).toContain("worm-core+unreachable");
  });
});
