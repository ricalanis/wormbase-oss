# OpenClaw Gateway — multi-channel chat gateway (Slack today; Discord/Teams in scope).
#
# Per CLAUDE.md "Channel layer: OpenClaw + Channel Ledger Adapter":
# OpenClaw is the Gateway control plane. Our `apps/channel-adapter/` service
# subscribes to its events and writes ledger entries tagged with `company_id`.
#
# Multi-tenant: a single OpenClaw container serves many tenants via
# `channels.slack.accounts.<companyId>` config blocks. Tenant tokens are
# injected from `.env` (`SLACK_APP_TOKEN_<COMPANY_ID>`,
# `SLACK_BOT_TOKEN_<COMPANY_ID>`).
#
# Install method: npm global install of the `openclaw` package
# (https://www.npmjs.com/package/openclaw, MIT license, 23+ channels).

FROM node:24-alpine

# Baileys (the WhatsApp Web client transitively pulled in by
# @openclaw/whatsapp) declares its libsignal dependency as a git URL, and
# its media-message path shells out to ffmpeg for audio/video transcoding.
# `node:24-alpine` ships with neither tool, so npm install of the WhatsApp
# plugin fails at git-clone time and runtime media handling silently drops
# transcodes. python3/make/g++ are needed because openclaw transitively
# pulls tree-sitter-bash, which has a node-gyp native build step.
RUN apk add --no-cache git ffmpeg python3 make g++

# Pin OpenClaw to the latest at build time. Bump deliberately when we
# upgrade — see infra/openclaw/UPGRADE.md.
#
# Retry config tunes npm for slow / flaky network hops (e.g. OrbStack VM
# routing on first boot). Idle timeout previously fired at 651s on a
# fresh install; bumping retries + max timeout to 10min, skipping audit
# and fund metadata that aren't needed for runtime.
RUN npm config set fetch-retries 5 \
 && npm config set fetch-retry-mintimeout 30000 \
 && npm config set fetch-retry-maxtimeout 600000 \
 && npm config set fetch-timeout 600000 \
 && npm install -g --no-audit --no-fund --prefer-online openclaw@latest

# `@openclaw/whatsapp` is a separate npm package — OpenClaw core does not
# bundle the WhatsApp transport. Installing it globally alongside `openclaw`
# lets the gateway register the `channels.whatsapp` config block at startup
# (see entrypoint.sh's render_whatsapp_block). Reuses the npm retry/timeout
# settings configured immediately above; no new config is needed.
RUN npm install -g --no-audit --no-fund @openclaw/whatsapp@latest

# Working dir is where the gateway reads its config + writes runtime state.
# We mount the config in via docker-compose; runtime state stays in-container
# (ephemeral by design — replay the ledger to reconstruct anything that matters).
WORKDIR /etc/openclaw

# Gateway default port. Bind 0.0.0.0 so the channel-adapter container can
# reach it on the docker network at openclaw:18789.
EXPOSE 18789

# Health endpoint OpenClaw exposes by default.
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=5 \
  CMD wget --quiet --spider http://localhost:18789/health || exit 1

# Entrypoint script applies WormBase config via `openclaw config set`
# (using OpenClaw's native SecretRef pattern for env-bound credentials)
# and then exec's the gateway. Idempotent across restarts.
COPY entrypoint.sh /usr/local/bin/wormbase-entrypoint.sh
RUN chmod +x /usr/local/bin/wormbase-entrypoint.sh

# Silent-mode gate-6 plugin: baked into the image at a neutral path so
# `openclaw plugins install --link` (called from entrypoint.sh) can
# symlink it into the extensions dir at runtime. Was previously a bind
# mount in docker-compose; moved to COPY 2026-05-25 because the bind
# mount path didn't resolve correctly under Coolify deploys.
COPY silent-mode-plugin /opt/wormbase/silent-mode-plugin

ENTRYPOINT ["/usr/local/bin/wormbase-entrypoint.sh"]
