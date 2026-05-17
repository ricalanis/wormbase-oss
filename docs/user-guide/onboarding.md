# `/onboarding` — User guide

## What it does

The onboarding tab is the **first surface a fresh installer sees**. It runs
the Tier 0 flow: connect a chat platform with one tap. Tier 0 is the only
install-blocking step — every other onboarding action (domain pack picker,
co-admin invites, classification defaults, KPI definition) happens
post-install via the wizard or bot path the installer chooses.

The default local lake auto-provisions during install. By the time the
installer lands at `/onboarding/welcome`, the tenant already has bronze +
silver + gold layers playable against its own conversation history — no
external source required.

## First action

If you have not yet installed:

1. Open <http://localhost:3000/onboarding>. Three platform buttons render:
   **Slack** (production), **Discord** (preview), **Teams** (preview).
2. Click **Connect to Slack**. The dashboard redirects through Slack's
   OAuth consent screen.
3. Approve the bot scopes. Slack redirects back to
   `/onboarding/oauth/slack/callback`.
4. The dashboard exchanges the OAuth code for a bot token (KMS-wrapped via
   `WORMBASE_KMS_KEY_ID` in production, or `vault://local-dev/...` in dev),
   calls `POST /api/v1/installs` on worm-core, and lands you at
   `/onboarding/welcome`.

If you do not have Slack OAuth credentials configured, the button surfaces
**disabled** with a "Configure SLACK_CLIENT_ID + SLACK_CLIENT_SECRET" hint.
There is no synthesized "dev mode" OAuth path. See
[`docs/setup/slack-oauth.md`](../setup/slack-oauth.md) for the production
setup steps.

## Advanced

- **Skip the OAuth UI** with `wormbase demo seed --reset-first --tenant
  baseworm --domain-pack saas --install-from-env`. Requires
  `SLACK_BOT_TOKEN_BASEWORM` set in `.env`. Same ledger writes as the OAuth
  flow; just a different driver. Use this when you control a long-lived
  Slack app and want to skip the consent screen.
- **Switch setup mode** post-install at `/settings/setup-mode` — wizard or
  bot. The bot path runs `SetupConversationLoop` in worm-core, which DMs
  you the next setup question; each reply writes a ledger entry.
- **Re-enter Tier 0** on a fresh tenant by visiting `/onboarding` again —
  the page detects a missing `Install` row and renders the connector
  buttons. If an install exists, it redirects to `/dashboard`.
- **Multiple installers**: only one Install per `(tenant, platform)` is
  allowed. Subsequent users join via invite (writes
  `emit_person_proposed`); they confirm via `/login`.

## Behind the scenes

Tier 0 fires this ledger sequence:

```
emit_install_completed                       (5 PEVR cycles total)
emit_role_assigned (tenancy.installer)
emit_role_assigned (tenancy.admin)
emit_person_confirmed (the installer)
emit_chat_sent  ("hi" in #general)

# Default lake auto-provisioned (4 more PEVR cycles):
emit_source_proposed   (local-lake://{tenant_id})
emit_source_confirmed
emit_source_connected
emit_source_profiled   (added_via_flow=provisioned_at_install)
```

Total: 9 PEVR cycles, 36 entries. The `provision_local_lake` orchestrator
in `apps/worm-core/src/wormbase_core/write_actions.py` writes the lake
entries; the dashboard's `/onboarding/welcome` page subscribes to the SSE
ledger stream at `/api/v1/ledger/stream` and renders the cascade live in
the InstallCascadePanel.

The post-install banner on `/dashboard` shows the wizard-vs-bot fork — a
visible CTA, not a forced redirect.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Slack button disabled with hint | `SLACK_CLIENT_ID` empty in compose env | Set the key in `.env`, `make dashboard-restart` |
| Callback says `state_mismatch` | OAuth state cookie expired (10-min TTL) | Click Connect again |
| Callback says `oauth_callback_failed` | `WORMBASE_DASHBOARD_URL` doesn't match Slack app's redirect URI | Update Slack app's redirect URL to match `WORMBASE_DASHBOARD_URL` |
| Welcome page never renders | SSE stream blocked by reverse proxy | Check `/api/v1/ledger/stream` returns chunked events; configure proxy for SSE pass-through |
| `users.info` returns no email | Slack app missing `users:read.email` scope | Add scope, reinstall the app |
