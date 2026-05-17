/**
 * GET /onboarding/oauth/{platform}/start — initiate the real OAuth flow.
 *
 * Replaces the previous "POST /onboarding/oauth/{platform}" route that
 * synthesized fake ``dev://`` grants. This handler:
 *
 *   1. Validates the requested platform is in the day-one set.
 *   2. Reads ``{PLATFORM}_CLIENT_ID`` from env. If unset → redirect to
 *      ``/onboarding?error=...&hint=...`` so the operator sees an
 *      honest "Slack not configured" message instead of a fake success.
 *   3. Generates a CSRF state token, sets it as an httpOnly cookie
 *      (``wormbase-oauth-state``, sameSite=lax, 10-minute expiry).
 *   4. Redirects to the platform's authorize endpoint.
 *
 * The matching callback handler at ``../callback/route.ts`` verifies
 * the state cookie + handles the code exchange.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { randomBytes } from "node:crypto";

export const dynamic = "force-dynamic";

const SUPPORTED_PLATFORMS = new Set(["slack", "discord", "teams"]);

const STATE_COOKIE = "wormbase-oauth-state";
const STATE_COOKIE_MAX_AGE_S = 600; // 10 minutes

const SLACK_BOT_SCOPES = [
  "channels:read",
  "channels:history",
  "channels:join",
  "chat:write",
  "chat:write.customize",
  "chat:write.public",
  "files:read",
  "files:write",
  "users:read",
  "users:read.email",
  "groups:read",
  "groups:history",
  "im:history",
  "im:read",
  "im:write",
];

const SLACK_USER_SCOPES = ["identity.basic", "identity.email"];

const DISCORD_SCOPES = ["bot", "identify", "email"];

const TEAMS_SCOPES = [
  "https://graph.microsoft.com/User.Read",
  "https://graph.microsoft.com/Channel.ReadBasic.All",
  "https://graph.microsoft.com/ChannelMessage.Read.All",
  "https://graph.microsoft.com/ChannelMessage.Send",
  "offline_access",
];

interface ProviderConfig {
  clientIdEnv: string;
  authUrl: string;
  scopes: string[];
  userScopes?: string[];
  configHint: string;
}

const PROVIDERS: Record<string, ProviderConfig> = {
  slack: {
    clientIdEnv: "SLACK_CLIENT_ID",
    authUrl: "https://slack.com/oauth/v2/authorize",
    scopes: SLACK_BOT_SCOPES,
    userScopes: SLACK_USER_SCOPES,
    configHint:
      "Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET per docs/setup/slack-oauth.md",
  },
  discord: {
    clientIdEnv: "DISCORD_CLIENT_ID",
    authUrl: "https://discord.com/api/oauth2/authorize",
    scopes: DISCORD_SCOPES,
    configHint:
      "Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET; see docs/setup/slack-oauth.md for the equivalent flow",
  },
  teams: {
    clientIdEnv: "TEAMS_CLIENT_ID",
    authUrl:
      "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    scopes: TEAMS_SCOPES,
    configHint:
      "Set TEAMS_CLIENT_ID and TEAMS_CLIENT_SECRET; see docs/setup/slack-oauth.md for the equivalent flow",
  },
};

/** Read the dashboard's public base URL — required to compute the
 *  redirect URI Slack/Discord/Teams will call back. */
function dashboardBaseUrl(req: NextRequest): string {
  const env = (process.env.WORMBASE_DASHBOARD_URL ?? "").trim();
  if (env) return env.replace(/\/+$/, "");
  // Fall back to the request's own origin — dev-mode convenience.
  return new URL(req.url).origin;
}

function redirectUriFor(req: NextRequest, platform: string): string {
  return `${dashboardBaseUrl(req)}/onboarding/oauth/${platform}/callback`;
}

function generateStateToken(): string {
  return randomBytes(32).toString("hex");
}

function configErrorRedirect(
  req: NextRequest,
  platform: string,
  hint: string,
): NextResponse {
  const url = new URL("/onboarding", new URL(req.url).origin);
  url.searchParams.set("error", `${platform}_not_configured`);
  url.searchParams.set("hint", hint);
  return NextResponse.redirect(url, { status: 303 });
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ platform: string }> },
): Promise<NextResponse> {
  const { platform } = await ctx.params;
  if (!SUPPORTED_PLATFORMS.has(platform)) {
    return NextResponse.json(
      {
        error: "unsupported_platform",
        message: `platform "${platform}" not in the day-one set`,
      },
      { status: 400 },
    );
  }

  const provider = PROVIDERS[platform];
  if (!provider) {
    return configErrorRedirect(
      req,
      platform,
      `no provider config for ${platform}`,
    );
  }

  const clientId = (process.env[provider.clientIdEnv] ?? "").trim();
  if (!clientId) {
    return configErrorRedirect(req, platform, provider.configHint);
  }

  const state = generateStateToken();
  const redirectUri = redirectUriFor(req, platform);

  // Build the authorize URL.
  const authUrl = new URL(provider.authUrl);
  authUrl.searchParams.set("client_id", clientId);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("state", state);
  if (platform === "slack") {
    authUrl.searchParams.set("scope", provider.scopes.join(","));
    if (provider.userScopes) {
      authUrl.searchParams.set("user_scope", provider.userScopes.join(","));
    }
  } else if (platform === "discord") {
    authUrl.searchParams.set("response_type", "code");
    authUrl.searchParams.set("scope", provider.scopes.join(" "));
    // Permissions: allow read/send messages + view channels.
    authUrl.searchParams.set("permissions", "0");
  } else if (platform === "teams") {
    authUrl.searchParams.set("response_type", "code");
    authUrl.searchParams.set("scope", provider.scopes.join(" "));
    authUrl.searchParams.set("response_mode", "query");
  }

  const res = NextResponse.redirect(authUrl, { status: 303 });
  res.cookies.set(STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: STATE_COOKIE_MAX_AGE_S,
    secure: dashboardBaseUrl(req).startsWith("https://"),
  });
  return res;
}
