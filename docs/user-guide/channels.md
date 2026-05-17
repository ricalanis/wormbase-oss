# `/channels` — User guide

## What it does

The Channels tab is per-platform install management — promoted from
`/settings/channels` to a top-level surface in the production rewrite
(D3 of the dashboard plan).

Three sections:

1. **Installed platforms** — one card per `Install`. Shows platform,
   installer Person, install timestamp, status, granted scopes, bot
   user.
2. **Channel roster** — per platform, the list of channels the worm is
   in. Per-channel toggles: lurker / responsive / proactive.
3. **Connect another platform** — buttons for every supported
   `ChannelAdapter`. Slack is production; Discord, Teams, Signal,
   WhatsApp render with a "preview" or "coming soon" badge.

This is the admin's daily surface during rollout.

## First action

Connect a second chat platform:

1. Click **Connect Discord** (or Teams / Signal / WhatsApp). If the
   platform's OAuth credentials aren't configured, the button is
   disabled with a hint.
2. OAuth flow runs through `/onboarding/oauth/discord/callback` — same
   shape as Slack. On success, a new `Install` row writes
   `emit_install_completed {platform: discord}`.
3. The dashboard returns to `/channels`. The new installed platform
   card appears alongside Slack.
4. The worm joins channels per the auto-join policy (default: every
   public channel for ≤ 50 members; opt-in per channel for > 50). The
   channel roster section populates within ~30s.

To set per-channel talkativeness:

1. In the channel roster, find any channel.
2. Click the **dial** column. Three states: **lurker** (ingest only,
   no speech), **responsive** (replies to mentions only), **proactive**
   (initiates on relevance gate fires).
3. Toggle. Writes `emit_channel_talkativeness_changed`.

## Advanced

- **Mute a channel** — for HR-confidential or board-only channels.
  Click the channel → **Mute**. Writes `emit_channel_muted`. The worm
  stops both ingest and send for this channel; data already in the
  ledger stays.
- **Revoke an install** — admin-only, confirmable destructive action.
  Writes `emit_install_revoked`. Bot leaves all channels; the
  `Install` row stays for audit but `status=revoked`.
- **Reinstall after revoke** — re-run OAuth. A new `Install` row writes;
  the old one stays archived. Personally-discovered identities reattach
  automatically.
- **Per-channel classification** — each channel inherits a default
  classification from the connected platform (`internal`). Admins can
  raise it (e.g. `confidential` for `#hr`). Affects what the worm will
  ingest into bronze and how `/trace` redacts.
- **Channel ownership** — admin proposes a Person as channel owner via
  the channel detail drawer. Writes
  `emit_resource_role_assigned {resource_type: channel, role: maintainer}`.
  Useful for "who do I ask about this channel?" audits.

## Behind the scenes

Reads from `projection_installs` (folds of
`emit_install_completed` / `emit_install_revoked`) and `projection_channels`
(folds of `emit_channel_joined` / `emit_channel_left` /
`emit_channel_talkativeness_changed` / `emit_channel_muted`).

Each `ChannelAdapter` implementation handles the platform's OAuth,
listen, send specifics. The dashboard reasons only about
`channel_id` (WormBase-internal UUID) and `person_id`; raw
`platform_channel_id` and `platform_user_id` only render in this tab
and `/people`.

The talkativeness dial governs the relevance-gate thresholds at the
worm-core layer. Lurker = gate always blocks send; responsive = gate
allows on `@-mention`; proactive = gate runs the full archetype-match
chain.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Channel roster empty after install | `ChannelAdapter.list_workspace_members` failed | Check OAuth scopes; reinstall |
| Worm not joining new channels | Bot needs invite (Slack policy) | Invite the bot via Slack `/invite @WormBase` |
| Talkativeness dial silent | `WORMBASE_LEDGER_API_TOKEN` mismatch | Re-set; restart |
| Discord install button disabled | `DISCORD_CLIENT_ID` empty | Set in `.env`; restart |
| Revoke "stuck" | Install marked `revoked` but bot still in channels | Run `wormbase channel-adapter cleanup --tenant <id> --platform <p>` |
