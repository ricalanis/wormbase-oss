/**
 * GET /onboarding/oauth/{platform}/callback — real OAuth callback.
 *
 * The provider redirects here after the installer authenticates. Flow:
 *
 *   1. Verify the ``wormbase-oauth-state`` cookie matches the ``state``
 *      query param (CSRF check). 400 on mismatch.
 *   2. Run the platform-specific code exchange against the provider's
 *      token endpoint. Returns a typed envelope: bot token + team id +
 *      bot user id + scopes + installer's user info.
 *   3. Resolve a tenant slug from the team/workspace id (single-tenant-
 *      per-workspace default). Set ``wormbase-tenant-slug`` cookie.
 *   4. Hand the bot token to ``completeInstall`` which KMS/vault-wraps
 *      it and calls worm-core ``POST /api/v1/installs``.
 *   5. Redirect to ``/onboarding/welcome`` — the post-OAuth landing
 *      that subscribes to the live ledger feed and lets the user watch
 *      the install cascade fire in real time. The previous redirect to
 *      ``/onboarding/tier2`` skipped the celebratory beat and surfaced
 *      a domain-pack form before the install was visibly grounded;
 *      W1.A3 introduces ``/onboarding/welcome`` to fix that.
 *
 * Failure modes:
 *   - 400 on state mismatch / missing code
 *   - 502 on provider token-exchange failure or worm-core API failure
 *
 * No synthesized identities. No fake grants. If the provider isn't
 * configured, ``../start/route.ts`` already redirected to an error
 * surface — we never get here in that case.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { completeInstall } from "../../../../../lib/server/install";
import { TENANT_COOKIE_NAME } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

const STATE_COOKIE = "wormbase-oauth-state";
const SUPPORTED_PLATFORMS = new Set(["slack", "discord", "teams"]);

interface OAuthEnvelope {
  /** Raw bot token from the provider — wrapped by ``completeInstall``. */
  botToken: string;
  /** Provider-native workspace/team id; we derive a tenant slug from this. */
  workspaceId: string;
  /** Provider-native bot user id. */
  botUserId: string;
  /** Granted bot scopes. */
  scopes: string[];
  /** Provider-native installer user id. */
  installerPlatformUserId: string;
  /** Installer's email, if the provider returned one. */
  installerEmail: string;
  /** Installer's display name. */
  installerName: string;
  /** Installer avatar URL, if available. */
  installerAvatarUrl: string | null;
  /** Provider-side workspace name; useful for the tenant display. */
  workspaceName: string;
}

function dashboardBaseUrl(req: NextRequest): string {
  const env = (process.env.WORMBASE_DASHBOARD_URL ?? "").trim();
  if (env) return env.replace(/\/+$/, "");
  return new URL(req.url).origin;
}

function redirectUriFor(req: NextRequest, platform: string): string {
  return `${dashboardBaseUrl(req)}/onboarding/oauth/${platform}/callback`;
}

/** Slack OAuth v2 code-exchange. POSTs application/x-www-form-urlencoded
 *  to slack.com/api/oauth.v2.access; returns the canonical envelope. */
async function exchangeSlack(
  code: string,
  redirectUri: string,
): Promise<OAuthEnvelope> {
  const clientId = (process.env.SLACK_CLIENT_ID ?? "").trim();
  const clientSecret = (process.env.SLACK_CLIENT_SECRET ?? "").trim();
  if (!clientId || !clientSecret) {
    throw new Error(
      "SLACK_CLIENT_ID / SLACK_CLIENT_SECRET unset; cannot exchange code",
    );
  }
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    code,
    redirect_uri: redirectUri,
  });
  const res = await fetch("https://slack.com/api/oauth.v2.access", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`slack oauth.v2.access HTTP ${res.status}: ${text}`);
  }
  let json: Record<string, unknown>;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(
      `slack oauth.v2.access returned non-JSON: ${text.slice(0, 200)}`,
    );
  }
  if (json["ok"] !== true) {
    throw new Error(`slack oauth.v2.access error: ${JSON.stringify(json)}`);
  }
  const team = (json["team"] ?? {}) as { id?: string; name?: string };
  const authedUser = (json["authed_user"] ?? {}) as { id?: string };
  const botToken = String(json["access_token"] ?? "");
  const botUserId = String(json["bot_user_id"] ?? "");
  const scopes = String(json["scope"] ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const workspaceId = String(team.id ?? "");
  const workspaceName = String(team.name ?? "");
  const installerPlatformUserId = String(authedUser.id ?? "");
  if (!botToken || !botUserId || !workspaceId || !installerPlatformUserId) {
    throw new Error(
      `slack oauth.v2.access missing required fields: ${JSON.stringify(json)}`,
    );
  }
  // Fetch the installer's profile (name + email + avatar) via users.info
  // using the freshly-issued bot token. users:read.email scope required.
  const userInfo = await fetchSlackUser(botToken, installerPlatformUserId);
  return {
    botToken,
    workspaceId,
    workspaceName,
    botUserId,
    scopes,
    installerPlatformUserId,
    installerEmail: userInfo.email,
    installerName: userInfo.name,
    installerAvatarUrl: userInfo.avatarUrl,
  };
}

async function fetchSlackUser(
  botToken: string,
  userId: string,
): Promise<{ email: string; name: string; avatarUrl: string | null }> {
  const params = new URLSearchParams({ user: userId });
  const res = await fetch(
    `https://slack.com/api/users.info?${params.toString()}`,
    {
      headers: { Authorization: `Bearer ${botToken}` },
      cache: "no-store",
    },
  );
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`slack users.info HTTP ${res.status}: ${text}`);
  }
  let json: Record<string, unknown>;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(
      `slack users.info non-JSON: ${text.slice(0, 200)}`,
    );
  }
  if (json["ok"] !== true) {
    throw new Error(`slack users.info error: ${JSON.stringify(json)}`);
  }
  const user = (json["user"] ?? {}) as {
    profile?: {
      email?: string;
      real_name?: string;
      display_name?: string;
      image_192?: string;
      image_72?: string;
    };
    real_name?: string;
    name?: string;
  };
  const email = user.profile?.email ?? "";
  const name =
    user.profile?.real_name ??
    user.real_name ??
    user.profile?.display_name ??
    user.name ??
    "";
  const avatarUrl =
    user.profile?.image_192 ?? user.profile?.image_72 ?? null;
  if (!email) {
    throw new Error(
      "slack users.info returned no email; users:read.email scope required for the install flow",
    );
  }
  if (!name) {
    throw new Error("slack users.info returned no name");
  }
  return { email, name, avatarUrl };
}

/** Discord OAuth2 code-exchange. */
async function exchangeDiscord(
  code: string,
  redirectUri: string,
): Promise<OAuthEnvelope> {
  const clientId = (process.env.DISCORD_CLIENT_ID ?? "").trim();
  const clientSecret = (process.env.DISCORD_CLIENT_SECRET ?? "").trim();
  if (!clientId || !clientSecret) {
    throw new Error(
      "DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET unset; cannot exchange code",
    );
  }
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
  });
  const res = await fetch("https://discord.com/api/oauth2/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`discord oauth2/token HTTP ${res.status}: ${text}`);
  }
  let json: Record<string, unknown>;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(
      `discord oauth2/token non-JSON: ${text.slice(0, 200)}`,
    );
  }
  const botToken = String(json["access_token"] ?? "");
  const scopes = String(json["scope"] ?? "")
    .split(" ")
    .map((s) => s.trim())
    .filter(Boolean);
  const guild = (json["guild"] ?? {}) as { id?: string; name?: string };
  if (!botToken || !guild.id) {
    throw new Error(
      `discord oauth2/token missing required fields: ${JSON.stringify(json)}`,
    );
  }
  // Fetch the installer's user info via /users/@me.
  const userRes = await fetch("https://discord.com/api/users/@me", {
    headers: { Authorization: `Bearer ${botToken}` },
    cache: "no-store",
  });
  const userText = await userRes.text();
  if (!userRes.ok) {
    throw new Error(
      `discord users/@me HTTP ${userRes.status}: ${userText}`,
    );
  }
  const user = JSON.parse(userText) as {
    id?: string;
    username?: string;
    email?: string;
    avatar?: string;
  };
  if (!user.id || !user.email || !user.username) {
    throw new Error(
      `discord /users/@me missing required fields: ${userText.slice(0, 200)}`,
    );
  }
  return {
    botToken,
    workspaceId: String(guild.id),
    workspaceName: String(guild.name ?? ""),
    botUserId: String(guild.id),
    scopes,
    installerPlatformUserId: String(user.id),
    installerEmail: String(user.email),
    installerName: String(user.username),
    installerAvatarUrl: user.avatar
      ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
      : null,
  };
}

/** Microsoft Teams (Graph) OAuth2 code-exchange. */
async function exchangeTeams(
  code: string,
  redirectUri: string,
): Promise<OAuthEnvelope> {
  const clientId = (process.env.TEAMS_CLIENT_ID ?? "").trim();
  const clientSecret = (process.env.TEAMS_CLIENT_SECRET ?? "").trim();
  if (!clientId || !clientSecret) {
    throw new Error(
      "TEAMS_CLIENT_ID / TEAMS_CLIENT_SECRET unset; cannot exchange code",
    );
  }
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    scope:
      "https://graph.microsoft.com/User.Read https://graph.microsoft.com/ChannelMessage.Send offline_access",
  });
  const res = await fetch(
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      cache: "no-store",
    },
  );
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`teams oauth2/v2.0/token HTTP ${res.status}: ${text}`);
  }
  const json = JSON.parse(text) as Record<string, unknown>;
  const botToken = String(json["access_token"] ?? "");
  if (!botToken) {
    throw new Error(
      `teams oauth2/v2.0/token missing access_token: ${text.slice(0, 200)}`,
    );
  }
  // Fetch the installer's profile via Graph /me.
  const meRes = await fetch("https://graph.microsoft.com/v1.0/me", {
    headers: { Authorization: `Bearer ${botToken}` },
    cache: "no-store",
  });
  const meText = await meRes.text();
  if (!meRes.ok) {
    throw new Error(`teams graph /me HTTP ${meRes.status}: ${meText}`);
  }
  const me = JSON.parse(meText) as {
    id?: string;
    mail?: string;
    userPrincipalName?: string;
    displayName?: string;
  };
  const email = me.mail ?? me.userPrincipalName ?? "";
  if (!me.id || !email || !me.displayName) {
    throw new Error(
      `teams graph /me missing required fields: ${meText.slice(0, 200)}`,
    );
  }
  // Tenant id (workspace id) lives in id_token claims; for now we use
  // the user's id-domain as the workspace id surrogate. A future Teams
  // refinement reads the tid claim properly.
  const workspaceId = String(me.id).split("-").slice(-1)[0];
  return {
    botToken,
    workspaceId,
    workspaceName: String(me.displayName),
    botUserId: String(me.id),
    scopes: ["ChannelMessage.Send", "User.Read"],
    installerPlatformUserId: String(me.id),
    installerEmail: email,
    installerName: String(me.displayName),
    installerAvatarUrl: null,
  };
}

async function exchangeCode(
  platform: string,
  code: string,
  redirectUri: string,
): Promise<OAuthEnvelope> {
  if (platform === "slack") return exchangeSlack(code, redirectUri);
  if (platform === "discord") return exchangeDiscord(code, redirectUri);
  if (platform === "teams") return exchangeTeams(code, redirectUri);
  throw new Error(`unsupported platform: ${platform}`);
}

/** Resolve a tenant slug from the workspace id. Single-tenant-per-
 *  workspace by default — admins can override at install time post-MVP. */
function tenantSlugFor(platform: string, workspaceId: string): string {
  return `${platform}_team_${workspaceId.toLowerCase()}`;
}

function errorRedirect(req: NextRequest, message: string): NextResponse {
  const url = new URL("/onboarding", new URL(req.url).origin);
  url.searchParams.set("error", "oauth_callback_failed");
  url.searchParams.set("hint", message.slice(0, 200));
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
        message: `platform "${platform}" not supported`,
      },
      { status: 400 },
    );
  }

  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const stateFromQuery = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) {
    return errorRedirect(req, `${platform} returned: ${errorParam}`);
  }
  if (!code) {
    return NextResponse.json(
      { error: "missing_code", message: "code query param required" },
      { status: 400 },
    );
  }

  // CSRF check: state cookie must match query param.
  const cookieStore = await cookies();
  const stateCookie = cookieStore.get(STATE_COOKIE)?.value;
  if (!stateCookie || !stateFromQuery || stateCookie !== stateFromQuery) {
    return NextResponse.json(
      {
        error: "state_mismatch",
        message: "OAuth CSRF state cookie mismatch; restart the install",
      },
      { status: 400 },
    );
  }

  const redirectUri = redirectUriFor(req, platform);
  let envelope: OAuthEnvelope;
  try {
    envelope = await exchangeCode(platform, code, redirectUri);
  } catch (err) {
    return errorRedirect(req, (err as Error).message);
  }

  const tenantSlug = tenantSlugFor(platform, envelope.workspaceId);

  // Run the install orchestrator (KMS-wrap token + worm-core API call).
  let installResult: Awaited<ReturnType<typeof completeInstall>>;
  try {
    installResult = await completeInstall({
      tenantSlug,
      platform,
      installerName: envelope.installerName,
      installerEmail: envelope.installerEmail,
      installerAvatarUrl: envelope.installerAvatarUrl,
      platformUserId: envelope.installerPlatformUserId,
      botToken: envelope.botToken,
      scopes: envelope.scopes,
      botUserId: envelope.botUserId,
    });
  } catch (err) {
    return errorRedirect(req, (err as Error).message);
  }

  // Success: clear the state cookie, set the tenant cookie, redirect.
  // /onboarding/welcome lights up the post-OAuth UX (hero + live install
  // cascade panel + CTA to /sources). It supersedes the previous direct
  // redirect to /onboarding/tier2 — the domain-pack form is reachable
  // from welcome's secondary CTA.
  const welcomeUrl = new URL(
    "/onboarding/welcome",
    new URL(req.url).origin,
  );
  const res = NextResponse.redirect(welcomeUrl, { status: 303 });
  res.cookies.set(STATE_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  res.cookies.set(TENANT_COOKIE_NAME, tenantSlug, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  // Stash the install id in a transient cookie so /onboarding/tier2
  // can render the receipt without re-querying the ledger.
  res.cookies.set("wormbase-last-install-id", installResult.installId, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 30,
  });
  return res;
}
