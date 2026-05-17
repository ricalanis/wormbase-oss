# Slack App Manifest — WormBase / OpenClaw

When you onboard a new tenant, create a Slack app from this manifest. One app per tenant workspace.

## How to use

1. Create a Slack workspace for the tenant (or use an existing one).
2. Go to https://api.slack.com/apps → **Create New App** → **From a manifest** → select the workspace.
3. Paste the JSON below (rename `display_information.name` to the tenant's flavor if useful — `WormBase`, `WormBase (Acme)`, etc.).
4. Click **Create**.
5. Generate **App-Level Token** under *Basic Information* → *App-Level Tokens* → scope `connections:write`. Save as `xapp-...`.
6. Click **Install to Workspace** under *Install App*. Approve. Copy the **Bot User OAuth Token** (`xoxb-...`).
7. Add to `.env`:
   ```
   SLACK_APP_TOKEN_<COMPANY_ID>=xapp-...
   SLACK_BOT_TOKEN_<COMPANY_ID>=xoxb-...
   ```
   (Use the tenant's `company_id` as the suffix, all-caps. For the demo: `DEMOCORP`.)
8. Add a matching `accounts.<companyId>` block to `infra/openclaw-config/config.json5`.
9. `make openclaw-restart` to pick up the new tenant.

## Manifest

```json
{
  "display_information": {
    "name": "WormBase",
    "description": "Institutional AI for your company's data and processes"
  },
  "features": {
    "bot_user": {
      "display_name": "WormBase",
      "always_online": true
    },
    "app_home": {
      "messages_tab_enabled": true,
      "messages_tab_read_only_enabled": false
    },
    "slash_commands": [
      {
        "command": "/wormbase",
        "description": "Talk to WormBase",
        "should_escape": false
      }
    ]
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "assistant:write",
        "channels:history",
        "channels:read",
        "chat:write",
        "commands",
        "emoji:read",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "mpim:write",
        "pins:read",
        "pins:write",
        "reactions:read",
        "reactions:write",
        "users:read"
      ]
    }
  },
  "settings": {
    "socket_mode_enabled": true,
    "event_subscriptions": {
      "bot_events": [
        "app_mention",
        "channel_rename",
        "member_joined_channel",
        "member_left_channel",
        "message.channels",
        "message.groups",
        "message.im",
        "message.mpim",
        "pin_added",
        "pin_removed",
        "reaction_added",
        "reaction_removed"
      ]
    }
  }
}
```

## Why these scopes

Same scope set as upstream OpenClaw's recommended Slack manifest, with WormBase branding. Covers:

- **Inbound events**: `app_mentions:read`, `*.history` (read messages in DMs / channels / groups / MPIMs), `reactions:read`, `pins:read`, `members:joined/left` for membership changes.
- **Outbound write**: `chat:write`, `files:write`, `*:write`, `assistant:write` (for streaming).
- **Read scopes** for resolution: `users:read`, `*.read`, `commands` for slash command parsing.

These are also the 8+ scopes captured in the wave-2 plan review notes (`docs/superpowers/notes/2026-04-22-wave2-plan-review.md` §"Slack API scopes") plus OpenClaw's full set.

## Multi-tenant note

The same manifest is used across all tenants — only the workspace install + tokens differ. The `company_id` lives in our `.env` + `config.json5`, NOT in the Slack app itself. Slack has no concept of "tenant"; we map workspace ↔ company_id at the OpenClaw config layer.
