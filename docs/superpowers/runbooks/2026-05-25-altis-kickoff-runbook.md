# Altis Kickoff Runbook — Monday 2026-05-25

> Operator: Ricardo. Read this Sunday night; execute Monday morning ≥1h before the call.
> Spec: `docs/superpowers/specs/2026-05-23-altis-kickoff-readiness-design.md`.
> Customer call recording: `Altis-Wormbase-72b96c65-7eaf.srt` (135 cues, ingested in step §6).

---

## What "ready" means

By 09:00 Monday you can:

1. Show Poncho + Ruben a WhatsApp group with the WormBase bot in it.
2. Send a message in the group; show them the `chat_received` entry land in the altis ledger via `wormbase-ledger-recent --tenant altis`.
3. Confirm the bot **does NOT reply** (mechanical-turk positioning — "I'm the agent for week 1").
4. Show the May 22 prep call transcript already ingested as 53 chat_received entries — proof the listener works on real transcripts.

---

## §1. Verify the shadow-throttle is cleared (CRITICAL — do FIRST)

The May 21 incident left `+5218114822051` in WhatsApp's soft-throttle state: heartbeats fire, but inbound delivery is silently dropped. **Per `docs/known_issues.md`, re-pairing the same SIM does NOT clear the throttle — it's number-scoped.**

```bash
# From your phone, send a WhatsApp message to +5218114822051 ("kickoff prep test 1").
# Watch the openclaw logs:
make openclaw-logs | grep -E "messagesHandled|lastInboundAt|chat_received"

# Expected within ~10s: messagesHandled increments, lastInboundAt updates,
# a chat_received line appears for the message you sent.
#
# If NOTHING arrives in 30s: throttle still active. Two options:
#   (a) Wait another 30-60min, retry. (Typical recovery window 1-24h since 2026-05-21.)
#   (b) Pair a fresh SIM — see infra/openclaw/WHATSAPP_PAIRING.md for the procedure.
#
# Do NOT proceed to §2-§7 until ONE test inbound succeeds.
```

If the throttle is still hot, escalate: the kickoff can still go ahead, but you'd have to demo via Slack instead of WhatsApp. **Make that call by 08:00 Monday so you have time to message Poncho.**

---

## §2. Switch the WhatsApp tenant binding to `altis`

The repo currently wires WhatsApp to the `baseworm` tenant. OpenClaw 2026.5.6 is single-account-WhatsApp (see comment in `infra/openclaw/entrypoint.sh:119-124`), so we **switch** rather than add. This loses the baseworm WhatsApp surface for the kickoff window.

### Edits

**`.env`** — replace the BASEWORM lines with ALTIS equivalents:

```diff
- WORMBASE_TENANT_ID=baseworm
+ WORMBASE_TENANT_ID=altis
- WHATSAPP_ENABLED_BASEWORM=true
- WHATSAPP_GROUP_POLICY_BASEWORM=allowlist
- WHATSAPP_GROUP_ALLOW_FROM_BASEWORM=<old jid>
- WORMBASE_WHATSAPP_BOT_PHONE_BASEWORM=5218114822051
+ WHATSAPP_ENABLED_ALTIS=true
+ WHATSAPP_GROUP_POLICY_ALTIS=allowlist
+ WHATSAPP_GROUP_ALLOW_FROM_ALTIS=    # left blank until §3 captures the JID
+ WORMBASE_WHATSAPP_BOT_PHONE_ALTIS=5218114822051
```

**`infra/openclaw/entrypoint.sh:147`** —

```diff
- WHATSAPP_INNER=$(render_whatsapp_block baseworm)
+ WHATSAPP_INNER=$(render_whatsapp_block altis)
```

(Leave `render_tenant_block baseworm` on line 141 alone — Slack stays bound to baseworm for now; Altis is WhatsApp-only.)

**`infra/docker-compose.yml`** — the OpenClaw service env block currently passes through the BASEWORM-suffixed vars (lines 111-115). Add the ALTIS-suffixed equivalents alongside (don't remove BASEWORM yet — harmless if both present):

```diff
       WHATSAPP_ENABLED_BASEWORM: ${WHATSAPP_ENABLED_BASEWORM:-}
       WHATSAPP_DM_POLICY_BASEWORM: ${WHATSAPP_DM_POLICY_BASEWORM:-pairing}
       WHATSAPP_GROUP_POLICY_BASEWORM: ${WHATSAPP_GROUP_POLICY_BASEWORM:-allowlist}
       WHATSAPP_ALLOW_FROM_BASEWORM: ${WHATSAPP_ALLOW_FROM_BASEWORM:-}
       WHATSAPP_GROUP_ALLOW_FROM_BASEWORM: ${WHATSAPP_GROUP_ALLOW_FROM_BASEWORM:-}
+      WHATSAPP_ENABLED_ALTIS: ${WHATSAPP_ENABLED_ALTIS:-}
+      WHATSAPP_DM_POLICY_ALTIS: ${WHATSAPP_DM_POLICY_ALTIS:-pairing}
+      WHATSAPP_GROUP_POLICY_ALTIS: ${WHATSAPP_GROUP_POLICY_ALTIS:-allowlist}
+      WHATSAPP_ALLOW_FROM_ALTIS: ${WHATSAPP_ALLOW_FROM_ALTIS:-}
+      WHATSAPP_GROUP_ALLOW_FROM_ALTIS: ${WHATSAPP_GROUP_ALLOW_FROM_ALTIS:-}
```

Also (line 463-ish) add the bot-phone passthrough for altis next to baseworm:

```diff
       WORMBASE_WHATSAPP_BOT_PHONE_BASEWORM: ${WORMBASE_WHATSAPP_BOT_PHONE_BASEWORM:-}
+      WORMBASE_WHATSAPP_BOT_PHONE_ALTIS: ${WORMBASE_WHATSAPP_BOT_PHONE_ALTIS:-}
```

### Restart

```bash
make openclaw-restart      # pick up the entrypoint + env changes
make adapter-restart       # pick up WORMBASE_TENANT_ID=altis
make openclaw-logs | head -30  # confirm "tenant altis: whatsapp enabled (...)"
```

---

## §3. Create the WhatsApp kickoff group

On YOUR phone, in WhatsApp:

1. Create new group: **"WormBase × Altis (Kickoff)"**.
2. Add: Poncho Garciga, Ruben Madiedo (you have Ruben's number from the May 22 call — `Ricardo Alanís: Rubén, ¿Me pasas tu teléfono, por favor?`), and the WormBase bot contact (`+5218114822051`).
3. Send one message: `kickoff smoke test`.

Capture the group JID from openclaw logs:

```bash
make openclaw-logs | grep -E "group.*@g\.us|chat_received" | tail -10
# Look for: "channel_id":"120363XXXXXXXXXXXXX@g.us"
```

Add the JID to `.env`:

```diff
- WHATSAPP_GROUP_ALLOW_FROM_ALTIS=
+ WHATSAPP_GROUP_ALLOW_FROM_ALTIS=120363XXXXXXXXXXXXX@g.us
```

Restart openclaw one more time so the allowlist picks up the JID:

```bash
make openclaw-restart
```

---

## §4. Smoke test the ingestion

Send 2-3 messages in the kickoff group from your phone (Poncho + Ruben don't need to be online yet). Confirm they land in the altis ledger:

```bash
uv run --directory apps/worm-core wormbase-ledger-recent --tenant altis --limit 20
# Expected: chat_received propose/execute rows with your messages, channel_id matches the JID.
```

Confirm the bot does **NOT reply** (look for `reply_suppressed` rows, NOT `chat_sent` rows):

```bash
uv run --directory apps/worm-core wormbase-ledger-recent --tenant altis --kind chat_sent
# Expected: zero rows.

uv run --directory apps/worm-core wormbase-ledger-recent --tenant altis --kind reply_suppressed
# Expected: rows present (one per inbound — the silent-mode plugin records each suppressed reply).
```

---

## §5. Ingest the May 22 prep call transcript

This is the demo moment — show Altis that their call has already been processed.

```bash
uv run --directory apps/worm-core wormbase-ingest-transcript \
  --tenant altis \
  --meeting-id altis-wormbase-kickoff-prep \
  --srt /Users/ricalanis/Downloads/Altis-Wormbase-72b96c65-7eaf.srt \
  --speakers "Ricardo Alanís,Poncho Garciga,Ruben Madiedo"

# Expected output (verified Saturday):
# parsed 135 cues, 53 turns after speaker-grouping
# ingested 53 chat_received entries for tenant altis
# session_id: meeting-altis-wormbase-kickoff-prep
# time range: 2026-05-22T23:00:00 .. 2026-05-22T23:10:35 (10m 35s)
# ledger seq range: <X>..<X+59>
```

Verify:

```bash
uv run --directory apps/worm-core wormbase-ledger-recent --tenant altis --limit 60 \
  --kind chat_received | grep transcript-altis-wormbase
```

---

## §6. On the call

Things to show, in order:

1. **The group exists, the bot is in it, messages flow.** Send a message in front of them.
2. **Run `wormbase-ledger-recent --tenant altis --limit 10`** in a terminal you share. They see the ingestion.
3. **Demo the transcript:** "We've already ingested our prep call from Friday. Watch:" then `wormbase-ledger-recent --tenant altis --kind chat_received --limit 60`. Point out the 53 speaker turns.
4. **Frame the mechanical-turk:** "For week 1 I'm the agent — you'll see ME respond, not the bot. The bot is listening. Weekly reports come from me directly." (You already pitched this on Friday.)
5. **Next step:** "Start inviting the bot to one client channel today/tomorrow so I can begin ingesting client conversations Monday afternoon." The default policy is `lurker`, so the bot will be silent there too.

Things to NOT promise on the call:

- A dashboard UI (week 3-4 roadmap)
- DM nudges to operators (week 4+)
- Per-channel talkativeness config (week 2-3)
- Real-time agent responses (mechanical-turk for now)

---

## §7. After the kickoff

By Friday 2026-05-30:

- At least one Altis client channel added; ingestion verified via `wormbase-ledger-recent`.
- First weekly report delivered to Altis as a written Markdown — use `record_decision` PEVR with `category="weekly_report"` to file it in the ledger so it lives next to the data it summarizes.
- Friction log → `docs/known_issues.md` entry for anything weird.

---

## Failure modes — what to do if §X breaks

**§1 fails (no inbound delivery):** throttle still active. Demo via Slack (baseworm Slack workspace is still wired). Apologize, schedule a "WhatsApp goes live" follow-up call Tuesday.

**§2 fails (openclaw restart errors):** check the rendered config — `docker exec wormbase-openclaw cat /root/.openclaw/openclaw.json | jq .channels.whatsapp`. If shape is wrong, the entrypoint logs the issue.

**§3 fails (no group JID in logs):** the bot may have been added but the group hasn't been activated for it yet. Have someone send a message in the group — that's what triggers the first inbound and the JID logging.

**§4 fails (chat_received rows missing):** tenant resolution may be wrong. Run `uv run python -c "from wormbase_channel_adapter.tenant import tenant_to_company_uuid; print(tenant_to_company_uuid('altis'))"` — must print `7f032a92-7036-5126-a957-8d2607126169`. If it does and rows are still missing, check `WORMBASE_TENANT_ID` is actually `altis` in the channel-adapter container: `docker exec wormbase-channel-adapter env | grep WORMBASE_TENANT_ID`.

**§5 fails (CLI errors on the SRT):** Saturday-verified to work. If it suddenly fails, the file may have been re-encoded or the schema changed. Re-run with `--dry-run` to see what parses.
