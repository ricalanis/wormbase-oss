#!/bin/sh
# WormBase OpenClaw entrypoint.
#
# Strategy: render the full openclaw.json config from container env in one
# atomic write, place it at OpenClaw's expected location, then exec the
# gateway. Avoids the per-`config set` schema-validation churn that kept
# rejecting partial provider blocks.
#
# Tokens are inlined from env vars at startup. Config file lives in
# the openclaw-state volume; gateway will rotate its own auth.token at
# first boot but our other keys survive across restarts.
#
# Multi-tenant: each Slack tenant is a JSON block under
# channels.slack.accounts.<companyId>. Add a new tenant by appending the
# matching SLACK_APP_TOKEN_<UPPER> + SLACK_BOT_TOKEN_<UPPER> env vars
# + a new render_tenant_block call.

set -e

log() { echo "[wormbase-entrypoint] $*" >&2; }

render_tenant_block() {
  tenant="$1"
  upper="$(echo "$tenant" | tr '[:lower:]' '[:upper:]')"
  app_var="SLACK_APP_TOKEN_${upper}"
  bot_var="SLACK_BOT_TOKEN_${upper}"
  eval "app_val=\${${app_var}:-}"
  eval "bot_val=\${${bot_var}:-}"

  if [ -z "$app_val" ] || [ -z "$bot_val" ]; then
    log "tenant $tenant: skipping (missing $app_var or $bot_var)"
    return 0
  fi

  log "tenant $tenant: tokens present, rendering account block"
  # allowBots=true so the WormBase Sim app's persona posts get
  # captured by Path 3. The channel-adapter's bot-id echo guard
  # (writer.py — keyed off the running OpenClaw bot's auth.test
  # response) prevents the agent's OWN replies from looping;
  # third-party bots (sim, observer apps, etc.) flow through.
  cat <<EOF
        "${tenant}": {
          "appToken": "${app_val}",
          "botToken": "${bot_val}",
          "groupPolicy": "open",
          "allowBots": true
        }
EOF
}

# WhatsApp tenant block. Unlike Slack (OAuth tokens at config-time),
# WhatsApp via OpenClaw uses Baileys (WhatsApp Web protocol) with QR
# pairing — credentials are negotiated at runtime via
# `openclaw channels login` and persisted under
# ~/.openclaw/credentials/whatsapp/<accountId>/. The config block is
# therefore policy-shaped (dmPolicy / groupPolicy / allowFrom /
# groupAllowFrom), NOT token-shaped. See infra/openclaw/WHATSAPP_PAIRING.md.
#
# Defaults: emit nothing unless WHATSAPP_ENABLED_<TENANT>=true. This
# preserves byte-identical behavior for existing Slack-only deploys.
render_whatsapp_block() {
  tenant="$1"
  upper="$(echo "$tenant" | tr '[:lower:]' '[:upper:]')"
  enabled_var="WHATSAPP_ENABLED_${upper}"
  dm_var="WHATSAPP_DM_POLICY_${upper}"
  group_var="WHATSAPP_GROUP_POLICY_${upper}"
  allow_var="WHATSAPP_ALLOW_FROM_${upper}"
  group_allow_var="WHATSAPP_GROUP_ALLOW_FROM_${upper}"

  eval "enabled_val=\${${enabled_var}:-}"
  if [ "$enabled_val" != "true" ]; then
    log "tenant $tenant: whatsapp disabled (set ${enabled_var}=true to enable)"
    return 0
  fi

  eval "dm_val=\${${dm_var}:-pairing}"
  eval "group_val=\${${group_var}:-allowlist}"
  eval "allow_val=\${${allow_var}:-}"
  eval "group_allow_val=\${${group_allow_var}:-}"

  # Convert comma-separated env values to JSON arrays. Whitespace is
  # trimmed per element so "5511..., 5599..." round-trips clean.
  if [ -n "$allow_val" ]; then
    allow_json=$(echo "$allow_val" | awk -F',' '{
      printf "[";
      for (i=1; i<=NF; i++) { gsub(/^ +| +$/, "", $i); printf "%s\"%s\"", (i>1?",":""), $i }
      printf "]"
    }')
  else
    allow_json="[]"
  fi
  if [ -n "$group_allow_val" ]; then
    group_allow_json=$(echo "$group_allow_val" | awk -F',' '{
      printf "[";
      for (i=1; i<=NF; i++) { gsub(/^ +| +$/, "", $i); printf "%s\"%s\"", (i>1?",":""), $i }
      printf "]"
    }')
  else
    group_allow_json="[]"
  fi

  log "tenant $tenant: whatsapp enabled (dmPolicy=$dm_val, allowFrom=$allow_val)"
  # OpenClaw 2026.5.6 dropped the multi-tenant accounts.<id> shape for
  # WhatsApp. The schema is now flat: enabled / selfChatMode / dmPolicy /
  # allowFrom at top-level under channels.whatsapp. Single account only;
  # creds live at credentials/whatsapp/default/ regardless of tenant.
  # The tenant arg is preserved for env-var keying (WHATSAPP_*_<TENANT>)
  # but no longer renders an accounts.<tenant> block.
  cat <<EOF
"selfChatMode": false,
      "dmPolicy": "${dm_val}",
      "allowFrom": ${allow_json}
EOF
}

CONFIG_DIR=/root/.openclaw
CONFIG_FILE="${CONFIG_DIR}/openclaw.json"

mkdir -p "$CONFIG_DIR"

log "rendering ${CONFIG_FILE} from env…"

TENANTS_JSON=$(render_tenant_block baseworm)

# WhatsApp tenant block. Empty when WHATSAPP_ENABLED_BASEWORM is not
# "true" — in that case WHATSAPP_BLOCK below stays empty and the
# rendered config has no `channels.whatsapp` key, preserving the
# Slack-only shape byte-for-byte.
WHATSAPP_INNER=$(render_whatsapp_block baseworm)
WHATSAPP_BLOCK=""
WHATSAPP_BINDING=""
if [ -n "$WHATSAPP_INNER" ]; then
  WHATSAPP_BLOCK=",
    \"whatsapp\": {
      \"enabled\": true,
      ${WHATSAPP_INNER}
    }"
  # Bind the WhatsApp channel to the same agent as Slack. accountId=default
  # because OpenClaw 2026.5.6 uses single-account WhatsApp; if multi-account
  # support returns upstream, bind per accountId.
  WHATSAPP_BINDING=',
    { "type": "route", "agentId": "main", "match": { "channel": "whatsapp", "accountId": "default" } }'
fi

if [ -n "${OLLAMA_API_KEY:-}" ]; then
  MODELS_JSON=$(cat <<'EOF'
  ,
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "https://ollama.com",
        "api": "ollama",
        "apiKey": "__OLLAMA_API_KEY_PLACEHOLDER__",
        "models": [
          { "id": "kimi-k2.6:cloud", "name": "kimi-k2.6:cloud", "input": ["text", "image"], "contextWindow": 256000, "maxTokens": 8192 },
          { "id": "gpt-oss:120b",   "name": "gpt-oss:120b",   "input": ["text"],          "contextWindow": 128000, "maxTokens": 8192 }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/kimi-k2.6:cloud",
        "fallbacks": ["ollama/gpt-oss:120b"]
      }
    },
    "list": [
      {
        "id": "main",
        "name": "WormBase",
        "systemPromptOverride": "You are WormBase — an institutional AI data agent that lives inside this company's Slack and (when connected) its data sources.\n\nGuidelines:\n- Respond conversationally, in plain text. Keep replies brief and direct.\n- Do NOT call tools (no file reads, no shell, no code execution) unless the user explicitly asks. For greetings or chit-chat, just answer.\n- If you don't have access to a data source needed to answer, say so plainly.\n- You are NOT a generic AI or coding assistant. You are WormBase, specific to this workspace."
      }
    ]
  }
EOF
)
  # Substitute the placeholder with the real env value (heredoc was 'EOF'
  # quoted to preserve the system prompt's literal text).
  MODELS_JSON=$(printf '%s' "$MODELS_JSON" | sed "s|__OLLAMA_API_KEY_PLACEHOLDER__|${OLLAMA_API_KEY}|")
else
  log "OLLAMA_API_KEY not set — skipping models block"
  MODELS_JSON=""
fi

GATEWAY_AUTH_JSON=""
if [ -n "${OPENCLAW_ADMIN_TOKEN:-}" ]; then
  GATEWAY_AUTH_JSON=",
    \"auth\": {
      \"mode\": \"token\",
      \"token\": \"${OPENCLAW_ADMIN_TOKEN}\"
    }"
fi

cat > "$CONFIG_FILE" <<EOF
{
  "gateway": {
    "controlUi": {
      "allowedOrigins": ["http://localhost:18789", "http://127.0.0.1:18789"]
    }${GATEWAY_AUTH_JSON}
  },
  "channels": {
    "defaults": { "groupPolicy": "allowlist" },
    "slack": {
      "enabled": true,
      "mode": "socket",
      "dmPolicy": "pairing",
      "accounts": {
${TENANTS_JSON}
      }
    }${WHATSAPP_BLOCK}
  },
  "bindings": [
    { "type": "route", "agentId": "main", "match": { "channel": "slack", "accountId": "baseworm" } }${WHATSAPP_BINDING}
  ]${MODELS_JSON}
}
EOF

log "config rendered. Validating…"
if openclaw config validate; then
  log "✓ config valid"
else
  log "✗ config validation failed — see content below:"
  cat "$CONFIG_FILE"
  exit 1
fi

# OpenClaw 2026.5.6+ requires WhatsApp plugin to be explicitly registered
# in plugins.entries.<name>.enabled=true (channels.whatsapp.enabled alone
# is necessary but not sufficient — without the plugins entry, the gateway
# loads channels but never instantiates the Baileys transport).
if [ -n "$WHATSAPP_INNER" ]; then
  log "registering whatsapp plugin entry…"
  openclaw config set plugins.entries.whatsapp.enabled true >/dev/null \
    && log "✓ plugins.entries.whatsapp.enabled=true" \
    || log "⚠ failed to register whatsapp plugin (channel may not start)"
fi

log "starting gateway on :18789…"
log "NODE_OPTIONS=${NODE_OPTIONS:-(unset)}"
# NODE_OPTIONS is sourced from docker-compose environment so it's
# present before openclaw starts. See infra/docker-compose.yml.
exec openclaw gateway --port 18789 --verbose --allow-unconfigured
