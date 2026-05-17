# Slack OAuth setup (Tier 1 install flow)

## Overview

Two paths land an `Install` row in the ledger; choose the one that
matches your situation:

* **Production install** — driven by the dashboard's
  `/onboarding/oauth/{platform}/start` → `/onboarding/oauth/{platform}/callback`
  chain. Used by real customers and by a demo operator who wants to
  exercise the full UX. Requires `SLACK_CLIENT_ID` +
  `SLACK_CLIENT_SECRET` and a tunnel reachable from Slack's servers.
* **Dev/CI seed** — `wormbase demo seed --install-from-env` runs the
  same `/api/v1/installs` orchestrator but using a pre-issued bot
  token from the environment. Used when you already control a Slack
  app (e.g. the long-lived "WormBase Sim" app) and want to skip the
  OAuth UI. The button on `/onboarding` continues to be the
  customer-facing path.

There is **no synthesized "dev mode" OAuth path**. Either the platform
is configured (real OAuth runs) or the start handler redirects to
`/onboarding?error=...&hint=...` so the operator sees an honest
"platform not configured" message. The CLI seed mirrors the rule —
unset env, non-zero exit.

## Slack — production

1. Create a Slack app at <https://api.slack.com/apps>. "From an app
   manifest" is fastest; paste the manifest under
   `docs/slack-sim-manifest.json` and adjust the redirect URL.
2. Under "OAuth & Permissions" set the redirect URL to
   `${WORMBASE_DASHBOARD_URL}/onboarding/oauth/slack/callback`. The
   dashboard URL must be reachable from Slack's servers — for
   localhost development use ngrok or a similar tunnel.
3. Bot scopes (already in the manifest):
   `channels:read,channels:history,channels:join,chat:write,
   chat:write.customize,chat:write.public,files:read,files:write,
   users:read,users:read.email,groups:read,groups:history,
   im:history,im:read,im:write`.
4. User scopes: `identity.basic,identity.email`.
5. Copy the **Client ID** and **Client Secret** to your environment:

   ```env
   SLACK_CLIENT_ID=...
   SLACK_CLIENT_SECRET=...
   WORMBASE_DASHBOARD_URL=https://your-tunnel.ngrok.io
   ```

6. Set the worm-core API token (used by the dashboard to call
   `POST /api/v1/installs`):

   ```env
   WORMBASE_LEDGER_API_TOKEN=<bearer>
   WORMBASE_LEDGER_API_BASE=http://worm-core:8910  # default
   ```

### Testing the flow

Visit `${WORMBASE_DASHBOARD_URL}/onboarding`. Click "Connect to Slack".

* If `SLACK_CLIENT_ID` is unset: the button surfaces a disabled
  "Configure SLACK_CLIENT_ID + SLACK_CLIENT_SECRET" state and
  `/onboarding/oauth/slack/start` redirects with
  `?error=slack_not_configured`. No silent fallback; honest empty.
* If `SLACK_CLIENT_ID` is set: redirect to Slack auth, approve scopes,
  redirect back to `/onboarding/oauth/slack/callback?code=...`,
  exchange the code for a bot token, KMS-wrap it, and call worm-core
  `POST /api/v1/installs`. Success lands you on `/onboarding/tier2`.

After a successful install the ledger contains a real `Person`,
`tenancy.installer + tenancy.admin` grants, and an
`emit_install_completed` entry whose `oauth_grant_ref` is a `kms://`
(or `vault://` in dev) reference — never the raw token.

### Production hardening

Production REQUIRES `WORMBASE_KMS_KEY_ID` be set so the OAuth callback
wraps the bot token under a real KMS key:

```env
WORMBASE_KMS_KEY_ID=arn:aws:kms:us-east-1:...:key/...
WORMBASE_REQUIRE_KMS=1   # refuse vault://local-dev fallback
```

Until `WORMBASE_KMS_KEY_ID` is set, the dashboard falls back to
`vault://local-dev/<id>` (a Postgres `_secrets` row holding the token
as `bytea`); this is acceptable for local development but must NOT
ship to production. Setting `WORMBASE_REQUIRE_KMS=1` makes the
dashboard refuse the fallback explicitly.

## Slack — local development

Same steps as production, except the tunnel target points at your
local dashboard and the KMS env vars stay unset (see the
"Production hardening" note above for the fallback semantics):

```env
WORMBASE_DASHBOARD_URL=http://localhost:3000
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
# WORMBASE_KMS_KEY_ID intentionally unset — the install helper falls
# back to a Postgres `_secrets` table addressed by `vault://local-dev/...`
```

## Slack — dev seed (CLI alternative)

If you have a pre-issued bot token (e.g. a long-lived "WormBase Sim"
token from a Slack app you already control), you can install via the
sim-harness CLI instead of the OAuth UI:

```bash
export SLACK_BOT_TOKEN_BASEWORM=xoxb-...
wormbase demo seed --reset-first --install-from-env
```

The CLI calls Slack's `auth.test` to derive the team id / bot user id,
calls `users.info` to derive the installer's name + email, then calls
`POST /api/v1/installs` with the same KMS/vault-wrapped token. Same
ledger writes as the OAuth UI; just a different driver.

When `--install-from-env` is NOT passed, `wormbase demo seed` runs the
warmup + history without writing an install. The dashboard will redirect
to `/onboarding` on first visit because no `Install` row exists. That
is correct production behavior — the ledger must contain a real
install before the dashboard chrome renders.

## Discord

Same shape:

```env
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...
```

Add a redirect URI on the Discord app settings page:
`${WORMBASE_DASHBOARD_URL}/onboarding/oauth/discord/callback`.

## Microsoft Teams

```env
TEAMS_CLIENT_ID=...
TEAMS_CLIENT_SECRET=...
```

Register an app in the Azure portal; redirect URI:
`${WORMBASE_DASHBOARD_URL}/onboarding/oauth/teams/callback`.

## Failure modes

| Scenario | Surface | Fix |
|---|---|---|
| `SLACK_CLIENT_ID` unset | Tier 0 redirects to `/onboarding?error=slack_not_configured&hint=...` | Set the env var |
| State cookie mismatch | 400 `state_mismatch` JSON | Restart the install — the cookie is 10-min lived |
| `code_exchange` fails | `/onboarding?error=oauth_callback_failed&hint=<message>` | Check Slack app redirect URI matches `WORMBASE_DASHBOARD_URL` |
| `users.info` returns no email | `/onboarding?error=oauth_callback_failed&hint=...` | Add `users:read.email` scope to the Slack app and reinstall |
| `WORMBASE_LEDGER_API_TOKEN` unset | Same as above | Set the token; restart the dashboard |
| `oauth_grant_ref` rejected | 422 from worm-core | Check the install helper isn't setting a `dev://` prefix; the validator only accepts `kms://` and `vault://` |
