# Public tunnel for OAuth callbacks

OAuth flows (Slack, Discord, Teams, voice-agent webhooks, ElevenLabs)
need a public HTTPS URL that the upstream platform can reach. Localhost
doesn't qualify. WormBase ships a profile-gated `tunnel` sidecar that
runs Cloudflare's free `trycloudflare.com` quick-tunnel inside a
container, so you don't need a host-level install of `ngrok` or
`cloudflared`.

## TL;DR

```bash
make tunnel               # bring up the tunnel sidecar + write .env.tunnel
make dashboard-restart    # restart the dashboard with WORMBASE_DASHBOARD_URL set
# ...test OAuth flow against the printed https://*.trycloudflare.com URL...
make tunnel-down          # tear it down + drop .env.tunnel
```

`make up` does NOT start the tunnel. It is opt-in via the `oauth`
compose profile.

## How it works

```
+------------------+        +------------------+        +-----------------+
| cloudflared       | <----> | Cloudflare edge  | <----> | Slack / Discord |
| (tunnel sidecar)  |  TLS   | (trycloudflare)  |  TLS   | / browser       |
+--------+---------+         +------------------+        +-----------------+
         |
         | HTTP, on the wormbase compose network
         v
   dashboard:3000

         shared volume: wormbase-tunnel-state
         /shared/tunnel.log   (cloudflared stdout, tee-d here)
         /shared/tunnel.url   (URL extracted by wait-for-tunnel.sh)
```

`make tunnel` runs three steps:

1. `docker compose --profile oauth up -d tunnel` — boot the sidecar.
   The container runs `cloudflared tunnel --url http://dashboard:3000`
   and pipes stdout into `/shared/tunnel.log`.
2. `infra/scripts/wait-for-tunnel.sh` — polls the log for the
   assigned `https://<random>.trycloudflare.com` URL (up to 30s),
   writes it to `/shared/tunnel.url`. Idempotent: re-running after
   success is cheap and confirms the URL is still live.
3. `infra/scripts/sync-tunnel-to-env.sh` — extracts the URL and
   upserts `WORMBASE_DASHBOARD_URL=https://...` into `.env.tunnel`.

The dashboard service env-loads `.env.tunnel` on top of `.env`, so a
`make dashboard-restart` picks up the new public URL without manual
editing. (The dashboard env wiring is owned by the sister A4 task; if
your tree pre-dates A4 you can `export $(grep -v '^#' .env.tunnel | xargs)`
before `docker compose up dashboard`.)

## Trade-offs

| Option | Setup | Cost | URL stability | Use when |
|---|---|---|---|---|
| **Cloudflared quick-tunnel (this)** | `make tunnel` | free | rotates per restart | local dev, demos, hackathons |
| Cloudflared **named tunnel** | requires Cloudflare account + domain | free | stable | staging, repeat OAuth testing |
| `ngrok` (free) | host install + account | free | rotates per restart | parity with existing teams |
| `ngrok` (paid) | host install + account | $$ | stable subdomain | production-shaped staging |
| Real **production deploy** | DNS + cert + reverse proxy | infra cost | stable | prod |

WormBase prefers the in-container quick-tunnel by default per the
`feedback_in_project_not_host.md` rule: no host-level installs.
If you already have a reverse proxy or Cloudflare account, set
`WORMBASE_DASHBOARD_URL` directly in `.env` and skip `make tunnel`.

## When to opt out

If you already have a public HTTPS URL pointed at the dashboard
(reverse proxy, named tunnel, real deploy), set `WORMBASE_DASHBOARD_URL`
in your `.env` directly and never call `make tunnel`. The OAuth start
handler reads from `WORMBASE_DASHBOARD_URL` regardless of how it got
there.

If you're testing a flow that doesn't need a public callback (the
demo arc against the in-process channel-adapter, wire-replay, unit
tests), no tunnel is needed at all — `make up` is sufficient.

## What happens to OAuth without a tunnel

If `WORMBASE_DASHBOARD_URL` is unset or points at `localhost`, the
Slack OAuth start handler still emits the redirect URL — but Slack's
servers can't reach `localhost`, so the callback never lands. The
"Connect to Slack" button works up to the Slack consent screen, then
the user is left on a Slack error page. Setting
`WORMBASE_DASHBOARD_URL` is the fix; `make tunnel` is the easiest way
to set it.

There is **no** synthesized "dev mode" OAuth path — the install helper
either runs real OAuth or surfaces an honest "platform not configured"
error. (See `docs/setup/slack-oauth.md` and the
`feedback_onboarding_production_only.md` note.)

## Security considerations

* **Public exposure.** While `make tunnel` is up, your local dashboard
  is reachable by anyone who knows the URL. Quick-tunnel URLs are
  random, but treat them as semi-public — don't paste the URL into
  chat without thinking. `make tunnel-down` revokes immediately.
* **URL rotation.** Free quick tunnels mint a new URL on every
  restart. If you reload the tunnel sidecar (or it crashes and
  restarts), Slack's saved redirect URL stops matching. Workflows:
    * Hackathon: `make tunnel` once at the start, leave it up, paste
      the URL into the Slack app's redirect URL setting once.
    * Repeat testing: upgrade to a Cloudflare named tunnel
      (`cloudflared tunnel create wormbase-dev`) which gives a stable
      `*.trycloudflare.com` or your own subdomain. The container
      image bakes in `cloudflared`; mount your tunnel credentials
      file into the sidecar and update the `cloudflared tunnel run`
      args in `Dockerfile.tunnel`.
* **No credentials cross the tunnel.** Slack delivers the auth code
  to `/onboarding/oauth/slack/callback` over HTTPS, the dashboard
  exchanges it server-side for a bot token, and the token is wrapped
  via KMS or `vault://local-dev/...` before it lands in the ledger
  — same path as production. The tunnel is just the public-facing
  HTTPS hop; it does not see plaintext tokens.
* **Cloudflare ToS.** Quick tunnels are free and unauthenticated, but
  Cloudflare's terms forbid running production traffic over them.
  This is a dev / hackathon / pilot-demo facility. For production, use
  a real deploy with a real reverse proxy.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `make tunnel` says "timed out after 30s" | cloudflared can't reach Cloudflare edge (corporate firewall, captive WiFi) | check `make logs` for the tunnel service; try a different network or upgrade to a named tunnel |
| `make tunnel` succeeds but `curl <url>` 502s | dashboard service isn't ready yet | run `make dashboard-restart`, wait ~30s for pnpm install to finish, retry |
| OAuth callback says "redirect_uri_mismatch" | the URL in your Slack app's settings doesn't match the rotated tunnel URL | update Slack's redirect URL setting to the new `WORMBASE_DASHBOARD_URL` (or upgrade to a named tunnel) |
| `.env.tunnel` not picked up | dashboard service started before `make tunnel` | `make dashboard-restart` |

## Cleanup

`make tunnel-down`:

* Stops and removes the `tunnel` container.
* Drops the `wormbase-tunnel-state` named volume (best-effort —
  doesn't fail if the volume is busy or already gone).
* Removes `.env.tunnel`.

The dashboard service stays up. If you need a clean slate,
`make down` after `make tunnel-down`.
