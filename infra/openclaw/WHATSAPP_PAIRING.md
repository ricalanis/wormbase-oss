# WhatsApp pairing for OpenClaw

This document is the operator runbook for bringing a WhatsApp account
online inside the WormBase OpenClaw gateway.

**Status:** preview. WhatsApp transport in OpenClaw rides on Baileys
(WhatsApp Web protocol). Production WhatsApp transport via the Meta
Cloud API is pending OpenClaw issue #73016. Use the procedure below
only on a dedicated test number.

---

## ToS notice — read first

OpenClaw's WhatsApp adapter uses [Baileys](https://github.com/WhiskeySockets/Baileys),
an unofficial reverse-engineered client of the WhatsApp Web protocol.
This violates WhatsApp's Terms of Service:

- Account bans are possible — sometimes within hours, sometimes never.
- Bans propagate from the device (phone) WhatsApp identifies as the
  primary; if that's a CEO's personal number, the ban hits there.
- WhatsApp does not preannounce bans, does not give a reason, and the
  appeal path through the official app is functionally a coin flip.

**Operating rules:**

1. Only pair a dedicated test number — a SIM you can lose tomorrow.
2. Never pair an executive or customer-success personal number.
3. Treat any working pairing as ephemeral; don't build flows that
   assume a 90-day uptime.
4. When Meta Cloud API support lands upstream (OpenClaw #73016), retire
   the Baileys path. Until then, WhatsApp ships at `status="preview"`
   with the caveat surfaced in the dashboard channels picker.

---

## Configuration env vars

Set these on the `openclaw` service in `infra/docker-compose.yml` (the
defaults already declared) via `.env`:

| Var | Required | Default | Meaning |
|---|---|---|---|
| `WHATSAPP_ENABLED_<TENANT>` | yes (must be `true`) | unset (disabled) | Master switch. The `channels.whatsapp` config block is omitted entirely unless this is `true`, so existing Slack-only deploys are byte-identical when WhatsApp is left disabled. |
| `WHATSAPP_DM_POLICY_<TENANT>` | no | `pairing` | DM admit policy. `pairing` (require explicit pairing approve), `open` (any DM is admitted), `allowlist` (only `WHATSAPP_ALLOW_FROM_<TENANT>` numbers). |
| `WHATSAPP_GROUP_POLICY_<TENANT>` | no | `allowlist` | Group admit policy. `allowlist` (only group jids in `WHATSAPP_GROUP_ALLOW_FROM_<TENANT>`) or `open`. |
| `WHATSAPP_ALLOW_FROM_<TENANT>` | no | empty | Comma-separated E.164 numbers permitted to DM the worm (e.g. `5511999999999,5511888888888`). Whitespace per element is trimmed. |
| `WHATSAPP_GROUP_ALLOW_FROM_<TENANT>` | no | empty | Comma-separated WhatsApp group jids the worm is admitted into (e.g. `120363012345678901@g.us`). |

`<TENANT>` is the upper-case tenant id (today: `BASEWORM`).

### Bot-phone resolution (`WORMBASE_WHATSAPP_BOT_PHONE_*`)

The worm needs to know its OWN WhatsApp phone number to:

1. Drop self-echoes (so its outbound posts don't round-trip as fresh
   inbound `chat_received`).
2. Match `@worm` mentions in WhatsApp messages (Baileys delivers mentions
   as a list of `<phone>@s.whatsapp.net` jids; the worm matches by phone).
3. Key per-tenant rate-limit buckets (`<tenant>:<phone>`).
4. Write the `install_completed` ledger entry on first pairing.

A SINGLE resolver (Phase F1, 2026-05-06) consults the env vars in this
precedence order — set ONE of these per tenant; the rest are optional:

| # | Env var | Notes |
|---|---|---|
| 1 | `WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>` | Tenant slug upper-cased. Multi-tenant deployments — preferred form. Example: `WORMBASE_WHATSAPP_BOT_PHONE_BASEWORM=5511888888888`. |
| 2 | `WORMBASE_WHATSAPP_BOT_PHONE_<COMPANY_ID_UPPER>` | Company UUID upper-cased, dashes preserved. Used when only `company_id` is in scope (e.g. the `MentionsWorm` predicate at match-time). Example: `WORMBASE_WHATSAPP_BOT_PHONE_6F7C4B1D-3F0A-5B2C-9D8E-1A4B5C6D7E8F=5511888888888`. |
| 3 | `WORMBASE_WHATSAPP_BOT_PHONE` | Single-tenant fallback (no suffix). Example: `WORMBASE_WHATSAPP_BOT_PHONE=5511888888888`. |

Resolution returns the first non-empty match, with leading `+`
defensively stripped. If none resolve, the worm logs a warning and
skips the install/echo/mention paths until the env is set.

**Operational guidance:**

- Single-tenant pilots: set only `WORMBASE_WHATSAPP_BOT_PHONE`.
- Multi-tenant production: set `WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>`
  per tenant (one env var per tenant).
- Setting both (1) and (2) for the same tenant is supported and
  back-compatible with deployments that pre-date F1's consolidation;
  precedence picks (1) first.

The pinned-mirror contract test
`tests/contract/test_whatsapp_bot_phone_env_resolver.py` enforces
byte-equivalent resolution between the chat-presence predicate and the
channel-adapter (per CLAUDE.md §1.5 rule 3, the resolver is duplicated
module-locally — the contract test is the only reconciliation gate).

---

## QR pairing flow

Once `WHATSAPP_ENABLED_BASEWORM=true` is set in `.env` and the openclaw
container is healthy:

```sh
# 1. Register a WhatsApp account slot for this tenant.
docker exec -it wormbase-openclaw \
  openclaw channels add --channel whatsapp --account baseworm

# 2. Initiate the QR-pairing handshake. This prints a QR code to the
#    container logs that you scan with the test number's phone:
#       WhatsApp → Settings → Linked Devices → Link a Device.
docker exec -it wormbase-openclaw \
  openclaw channels login --channel whatsapp --account baseworm

# 3. Watch the gateway log until "QR scanned, awaiting approval" appears.
docker compose logs -f openclaw

# 4. Approve the pairing. The pairing-code list shows pending requests;
#    approve the one that just arrived.
docker exec -it wormbase-openclaw \
  openclaw pairing list whatsapp

docker exec -it wormbase-openclaw \
  openclaw pairing approve whatsapp <CODE>
```

After step 4 the gateway logs `whatsapp: account baseworm online` and
the channel-adapter starts seeing `whatsapp: allow channel <jid>` lines
in its log-tail consumer (subject to Phase 4 of the WhatsApp rollout
plan landing the regex generalization).

---

## Credential persistence

Baileys credentials (the auth blob WhatsApp issues after QR scan) are
written to:

```
/root/.openclaw/credentials/whatsapp/<accountId>/creds.json
```

Inside the openclaw container. That path lives under the
`openclaw-state` named volume (declared in `infra/docker-compose.yml`),
so credentials survive container restarts and image rebuilds.

To force a re-pair (e.g. after a WhatsApp ban or when rotating the
test number), delete the credentials and re-run the login flow:

```sh
docker exec -it wormbase-openclaw \
  rm -rf /root/.openclaw/credentials/whatsapp/baseworm

docker exec -it wormbase-openclaw \
  openclaw channels login --channel whatsapp --account baseworm
```

---

## Troubleshooting

### "QR code expired" before scan

WhatsApp QR codes rotate every ~20s. Re-run `openclaw channels login`
to get a fresh one. If it still expires before you scan, the
container's clock may be drifting; check `docker exec wormbase-openclaw date -u`
against host time.

### Pairing succeeds but no messages arrive

Two likely causes:

1. The number's WhatsApp app silently demoted the linked device after
   ban / inactivity. Check the phone's "Linked Devices" panel — if the
   OpenClaw entry is gone, the pairing was revoked. Re-pair.
2. The `groupPolicy` is `allowlist` (default) and the group jid isn't
   in `WHATSAPP_GROUP_ALLOW_FROM_BASEWORM`. Add it and restart the
   openclaw container so the rendered config picks up the new env.

### "messaging-history.set" floods after reconnect

Expected. Baileys replays unsynced history on every reconnect — that
is precisely what the `delivery_mode="history_sync"` provenance field
on InfraEvent (Phase 1 of this rollout) captures, and what the
`conversation_sync` ledger entry kind (Phase 1) records as one PEVR
cycle per reconnect. After Phase 3 of the rollout lands the
WhatsAppChannelAdapter's sync state machine, history replays will not
trigger speak-path reactivities (gated by `LiveOnly`).

### Account banned

Pull the credentials from the volume, archive them for forensics, then
delete and rotate to a fresh test number. Do not appeal — appeals on
Baileys-detected bans are very rarely granted, and the appeal path
itself can rate-limit the appealing number.

---

## Re-pair flow when creds expire

WhatsApp linked-device sessions are not eternal. They end when the user
manually unlinks the worm device on the primary phone, when WhatsApp
invalidates the session for inactivity / suspected abuse, or when
Baileys' stored creds desync from the server.

**Symptoms:**

- The openclaw log shows `session ended` (or Baileys `Connection Closed`
  with `reason=loggedOut`) and never re-emits `connection_open`.
- The channel-adapter log-tail consumer stops writing `chat_received`
  ledger entries — no traffic, even when you message the bot from the
  paired phone.
- `/channels/<id>` sync history panel stops appending new
  `conversation_sync` rows after the last reconnect.

**Recovery:**

```sh
# 1. Log the channel out cleanly so OpenClaw drops its in-memory session.
docker exec -it wormbase-openclaw \
  openclaw channels logout --channel whatsapp --account baseworm

# 2. Back up the existing creds before wiping (see "Creds backup +
#    restore" below). This preserves forensics if you need to diagnose
#    why the session ended.
docker cp wormbase-openclaw:/root/.openclaw/credentials/whatsapp/baseworm/creds.json \
  ./baseworm-creds-$(date +%Y%m%d).json
chmod 600 ./baseworm-creds-*.json

# 3. Wipe stale creds inside the volume.
docker exec -it wormbase-openclaw \
  rm -rf /root/.openclaw/credentials/whatsapp/baseworm

# 4. Re-run the QR pairing flow from the top of this doc (channels add
#    is idempotent if the slot already exists; channels login prints a
#    fresh QR).
docker exec -it wormbase-openclaw \
  openclaw channels login --channel whatsapp --account baseworm
```

**Expected ledger side effect:** re-pair triggers a fresh
`connection_open`. The first-time install detection (per B3 + B3.1)
fires and writes a NEW `install_completed` ledger entry. This is
expected and audited — the synthesized `installer_person_id` is
deterministic from `(tenant_id, bot_jid)`, so a re-pair on the same
bot jid produces an entry that ledger-fold idempotency recognizes;
a re-pair on a fresh bot phone produces a genuinely new install.
Either way, `/channels/<id>` shows the new install row in its history.

---

## Creds backup + restore

Baileys persists two files at
`/root/.openclaw/credentials/whatsapp/<accountId>/`:

| File | Role |
|---|---|
| `creds.json` | Live linked-device session keys. Loaded on startup; written-through on every Baileys keystate transition. |
| `creds.json.bak` | Atomic-rename safety copy. Baileys writes the new state to a temp file, fsyncs, then renames over `creds.json` and copies the previous `creds.json` to `creds.json.bak`. Use this only if `creds.json` is truncated / corrupted on disk. |

`.bak` is not a "yesterday's snapshot" — it's a one-step undo for a
torn write. If you need a real backup, take it manually.

**Manual backup:**

```sh
docker cp wormbase-openclaw:/root/.openclaw/credentials/whatsapp/baseworm/creds.json \
  ./baseworm-creds-$(date +%Y%m%d).json
chmod 600 ./baseworm-creds-*.json
```

**Restore (e.g. after rolling back a bad image build):**

```sh
# 1. Stop the openclaw container so Baileys is not holding the file open.
docker compose -f infra/docker-compose.yml stop openclaw

# 2. Copy the backup back into the credentials volume.
docker cp ./baseworm-creds-<date>.json \
  wormbase-openclaw:/root/.openclaw/credentials/whatsapp/baseworm/creds.json

# 3. Fix ownership inside the container (Baileys runs as root in the
#    openclaw image; the docker cp may have stamped host uid).
docker compose -f infra/docker-compose.yml run --rm --entrypoint sh openclaw \
  -c "chown root:root /root/.openclaw/credentials/whatsapp/baseworm/creds.json && chmod 600 /root/.openclaw/credentials/whatsapp/baseworm/creds.json"

# 4. Start the container and watch for connection_open.
docker compose -f infra/docker-compose.yml start openclaw
docker compose -f infra/docker-compose.yml logs -f openclaw | grep -E "connection_open|session"
```

If the restored creds were written before the linked-device session was
revoked, restore succeeds and traffic resumes. If the session was
revoked between backup and restore, you'll see immediate
`connection_close` with `reason=loggedOut` — fall through to the
re-pair flow above.

**Security note:** `creds.json` contains the linked-device session
keys. Anyone with that file can impersonate the worm on WhatsApp until
the session is revoked. Treat it as a credential at rest:

- chmod 600, never world-readable.
- Never commit to git. The repo's `.gitignore` does not exclude
  arbitrary `*.json` files; do not write the backup inside the repo
  tree.
- Never paste in Slack / email / chat. If a creds file leaks, the
  remediation is the re-pair flow (which invalidates the leaked
  session) plus rotating the test number.
- Store backups encrypted at rest if they leave the operator's laptop.

---

## Troubleshooting "session ended on another device"

WhatsApp's primary phone shows a "Linked Devices" screen
(Settings → Linked Devices). Up to **4 linked devices** are allowed
per WhatsApp account. Devices older than 14 days of inactivity are
auto-revoked.

Two patterns end a worm's session unexpectedly:

1. The user (or a colleague with phone access) manually removed the
   OpenClaw entry from "Linked Devices".
2. WhatsApp invalidated the session — abuse heuristics, ToS-violation
   scoring on the Baileys client, or a server-side rotation. WhatsApp
   does not announce these and gives no reason.

**Symptom signature:**

- One `connection_open` log line on initial pairing.
- Immediate (or within minutes) `connection_close` with
  `reason="loggedOut"` (Baileys' explicit signal that the server told
  the client to stop).
- The "Linked Devices" screen no longer shows the OpenClaw entry, or
  shows it with a stale `last seen` timestamp.

**Fix:** re-pair (see "Re-pair flow when creds expire" above). The
session cannot be resurrected — there is no refresh-token equivalent
in the WhatsApp Web protocol once the server has rejected the keys.

If the same number is being revoked repeatedly within hours, treat it
as a soft ban precursor: rotate to a fresh dedicated test number per
the ToS-notice operating rules at the top of this doc.

---

## Operator checklist (post-pair)

After every successful pair / re-pair, run through this list before
declaring the channel healthy:

- [ ] **Verification harness** — run the OpenClaw log-grammar regression
      to confirm the channel-adapter's log-tail consumer recognizes the
      Baileys output shape. Test path: TBD when A3 lands at
      `tests/integration/test_openclaw_whatsapp_log_lines.py` (sister
      task in this dispatch wave). If A3 has not pushed yet, watch
      `docker compose logs -f openclaw` manually for the
      `whatsapp: allow channel <jid>` line on the first inbound
      message.
- [ ] **Person proposal** — message the bot from a phone number not
      previously seen by the worm. Open `/people` in the dashboard and
      confirm a `proposed` Person row appears with the friend's
      WhatsApp jid as a `PersonIdentity` row pointing at it.
- [ ] **Conversation_sync entry** — open `/channels/<id>` and confirm
      the sync history panel has appended a new `conversation_sync`
      row with `status=completed`, `message_count` matching the
      messages exchanged during the session, and `delivery_mode=push`
      on the per-message references.

If any item fails, the pairing is not production-clean. Either re-pair,
or roll back to the previous creds backup, before exposing the channel
to real users.

---

## Verifying log-line grammar

The channel-adapter consumes OpenClaw's daily log via the regex
`^(slack|whatsapp): allow channel (\S+) ` in
`apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py`.
The Slack form is empirically verified; the WhatsApp form is **assumed
symmetric pending live verification**. After completing the pairing
flow above, run the verification harness against a paired instance:

```sh
WORMBASE_LIVE_OPENCLAW_TEST=1 \
WORMBASE_OPENCLAW_LOG_DIR=/var/log/openclaw \
uv run pytest tests/integration/test_openclaw_whatsapp_log_lines.py -v
```

The harness tails the log file for ~30s and asserts the production
regex matches at least one observed line. Default pytest runs skip
this test cleanly (no live OpenClaw needed).

**Discovery mode** — when verification fails or the grammar is
unknown, dump the first 10 observed `whatsapp`-tagged lines without
asserting:

```sh
WORMBASE_LIVE_OPENCLAW_TEST=1 \
WORMBASE_LIVE_OPENCLAW_DISCOVER=1 \
WORMBASE_OPENCLAW_LOG_DIR=/var/log/openclaw \
uv run pytest tests/integration/test_openclaw_whatsapp_log_lines.py -v -s
```

**5-minute feedback loop on failure:**

1. The failure message embeds the actual observed line (and the full
   set is dumped to `/tmp/wormbase-openclaw-whatsapp-loglines-<ts>.txt`).
2. Paste the observed line into the next conversation.
3. Update the regex `_ALLOW_CHANNEL_RE` in `openclaw_log_tail.py` —
   one-line patch.
4. Re-run the harness to confirm the patch matches.

Tip: the test only sees lines emitted *during* its 30s window
(starts at end-of-file). If you have no naturally-arriving messages,
send one to the paired bot while the test is running.

---

## OpenClaw outbound discovery (Wave C1, 2026-05-06)

When wiring WhatsApp send (Wave C2), we ran an empirical probe of
OpenClaw's HTTP surface inside a paired live container to find the
canonical outbound route. **Headline finding: there is no plain HTTP
send route. The outbound surface is the WebSocket Gateway, accessed
via the bundled `openclaw message send` CLI.**

### Probe trail

The full sequence run from the channel-adapter container against
`http://openclaw:18789` (token-authenticated where needed):

```sh
# 1. Health: 200, {"ok":true,"status":"live"}.
GET /health

# 2. OpenAPI / Swagger / docs: not exposed. /docs returns the SPA
#    shell. /openapi.json, /api/v1/openapi.json, /swagger.json all 404.
GET /openapi.json
GET /api/v1/openapi.json
GET /swagger.json
GET /docs                       # 200 — SPA HTML
GET /api/v1                     # 404
GET /api                        # 404

# 3. Candidate send routes (without auth → 401 means route exists; 404
#    means route does not exist):
POST /api/whatsapp/send                  # 404
POST /api/v1/whatsapp/send               # 404
POST /channels/whatsapp/send             # 404
POST /messages/whatsapp/send             # 404
POST /whatsapp/messages                  # 404
POST /whatsapp/send                      # 404
POST /api/messages                       # 404
POST /api/messages/send                  # 404
POST /api/send                           # 404
POST /api/channels/whatsapp/send         # 401 — looked promising

# 4. With Authorization: Bearer <gateway.auth.token>:
POST /api/channels/whatsapp/send         # 404 — auth check happens BEFORE
                                         #       routing; the 401 was a
                                         #       false positive. The
                                         #       route does not exist.
```

The `PROTECTED_PLUGIN_ROUTE_PREFIXES = ["/api/channels"]` in
`/usr/local/lib/node_modules/openclaw/dist/security-path-*.js` confirms
the prefix is reserved for plugin-registered routes — but `@openclaw/whatsapp`
does not register an HTTP send route. Its outbound surface is exposed
exclusively through the gateway's WebSocket protocol via the
`sendMessageWhatsApp` runtime function (in
`/usr/local/lib/node_modules/@openclaw/whatsapp/dist/send-*.js`).

### CLI probe (the canonical path)

```sh
# Discovery: the CLI's message-send subcommand is the documented
# outbound surface for every channel OpenClaw supports.
docker exec wormbase-openclaw openclaw message send --help

# Dry-run smoke (no actual send):
docker exec wormbase-openclaw openclaw message send \
  --channel whatsapp \
  --target "+5511999999999" \
  --message "C1 probe" \
  --dry-run \
  --json
# → {"action":"send","channel":"whatsapp","dryRun":true,
#    "handledBy":"core","payload":{"channel":"whatsapp","to":"+5511999999999",
#    "via":"gateway","mediaUrl":null,"dryRun":true}}
```

Live invocation requires the calling device to hold operator-write
scopes on the gateway. Today's pre-paired device (registered at
`/root/.openclaw/devices/paired.json`) holds only `operator.read`,
so any non-dry-run send fails with:

```
gateway connect failed: GatewayClientRequestError: scope upgrade pending approval
GatewayTransportError: gateway closed (1008): pairing required:
  device is asking for more scopes than currently approved
```

The scope upgrade lands via Control UI approval (`http://localhost:18789`
in the dashboard) — operator-friction by design, not automatable from
inside the container without the operator's signed approval.

### Adapter wire — `WhatsAppChannelAdapter._do_send`

C2 implements `_do_send` via `asyncio.create_subprocess_exec`:

```python
argv = [
    "docker", "exec", os.environ.get(
        "WORMBASE_WHATSAPP_OPENCLAW_CONTAINER", "wormbase-openclaw",
    ),
    "openclaw", "message", "send",
    "--channel", "whatsapp",
    "--account", account_id,
    "--target", channel.platform_channel_id,
    "--message", msg.text or "",
    "--json",
]
if token := os.environ.get("WORMBASE_WHATSAPP_OPENCLAW_TOKEN"):
    argv.extend(["--token", token])
```

Returns a `MessageRef` with `platform_message_id` extracted from
`payload.messageId` in the JSON stdout. The rate-limit decorator
(Wave E2) wraps the call path automatically; rate-limit-shaped
stderr (`"rate limit"`, `"429"`, `"Too Many Requests"`,
`"retry-after"`) is mapped to `RateLimitedError` so the surrounding
backoff retries.

### Operator example

```sh
# Once the operator approves write scopes on the paired CLI device:
docker exec wormbase-openclaw openclaw message send \
  --channel whatsapp \
  --account default \
  --target "+5511999999999" \
  --message "Hello from WormBase" \
  --token "$OPENCLAW_GATEWAY_TOKEN" \
  --json
# → {"messageId":"BAEABCD12345","toJid":"5511999999999@s.whatsapp.net",...}
```

### Future: HTTP route from OpenClaw issue #73016

Upstream `openclaw/openclaw#73016` tracks Meta Cloud API support for
WhatsApp; landing it will also add a plain HTTP `/api/v1/channels/whatsapp/send`
route for sandbox-friendly outbound. When that ships, the `_do_send`
body in `packages/channel-adapters/src/wormbase_channel_adapters/whatsapp.py`
flips from subprocess to `aiohttp.ClientSession.post(...)` without any
public-surface change. The capability set, the rate-limit decorator,
the echo-guard, the InstallEmitter contract — all stay byte-identical.

---

## See also

- `infra/openclaw/entrypoint.sh` — `render_whatsapp_block` function
- `infra/docker-compose.yml` — `openclaw` service env block
- `docs/superpowers/plans/2026-05-05-whatsapp-and-conversation-provenance.md` — full rollout plan
- `docs/superpowers/plans/2026-05-06-whatsapp-first-class.md` §3 Wave A3 — verification harness origin
- `docs/superpowers/plans/2026-05-06-whatsapp-first-class.md` §3 Wave C — outbound send rollout
- `tests/integration/test_openclaw_whatsapp_log_lines.py` — the harness
- `packages/channel-adapters/tests/test_whatsapp_send.py` — Wave C2 send round-trip + edge cases
- OpenClaw upstream: https://github.com/openclaw/openclaw
- Baileys upstream: https://github.com/WhiskeySockets/Baileys
