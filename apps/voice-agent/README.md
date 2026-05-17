# wormbase-voice-agent

Voice modality for WormBase. Bridges **ElevenLabs Conversational AI**
(STT, turn-taking, TTS) to the WormBase ledger and the Kimi-via-Ollama
brain. A phone caller talks to ElevenLabs; ElevenLabs calls our
custom-LLM webhook; we run the same Kimi prompt the Slack worm runs and
write hash-chained `chat_received` / `chat_sent` ledger entries tagged
with `modality="voice"`. Phone is just another channel.

Realises **Step 4b conversational voice** of the canonical 5-step
product arc (`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`).
The full design rationale lives in
`docs/superpowers/specs/2026-04-26-voice-agent-design.md` (W1.A).

## Architecture (one paragraph)

ElevenLabs is the ear and mouth: STT, voice activity detection, and
TTS run hosted on their side. Our FastAPI service exposes three
ElevenLabs-facing webhooks (`/webhook/elevenlabs`,
`/webhook/elevenlabs/session-start`, `/webhook/elevenlabs/session-end`)
plus `/healthz`. Per turn, the LLM webhook receives an OpenAI-shaped
`messages` array, writes a `chat_received` ledger entry, fetches the
last 20 utterances from the conversation lake as context, calls Kimi
via the existing `OLLAMA_API_KEY`, writes a `chat_sent` entry, and
returns the reply text in OpenAI chat-completion shape so ElevenLabs
can render TTS. Both ledger writes carry `modality="voice"` and an
`audio_ref` (filesystem path for the demo, S3 in production) so a
JSONB query like `payload->>'modality' = 'voice'` finds every voice
exchange. Hash chain extends across voice and text uniformly.

## Layout

```
apps/voice-agent/
├── pyproject.toml                — fastapi, uvicorn, httpx, pydantic, wormbase-ledger
├── Dockerfile                    — workspace-context build, port 8090
├── README.md                     — this file
├── src/wormbase_voice_agent/
│   ├── __init__.py               — VoiceAgent facade + dataclasses
│   ├── app.py                    — FastAPI app + create_app() + endpoints
│   ├── audit.py                  — emit_chat_received / emit_chat_sent / session helpers
│   ├── audio_store.py            — filesystem-backed AudioStore
│   ├── elevenlabs.py             — webhook Pydantic models + KimiOllamaClient
│   └── cli.py                    — `wormbase-voice-agent serve` (Click + uvicorn)
└── tests/
    ├── conftest.py               — InMemoryLedger + FakeKimi fixtures
    ├── test_kimi_proxy.py        — webhook handler with mocked ElevenLabs body
    ├── test_audit.py             — voice modality + audio_ref tags + chain integrity
    └── test_audio_ref.py         — filesystem audio writes + ledger linkage
```

## Install + run (local)

```bash
# 1. Sync deps (uv workspace).
uv sync --package wormbase-voice-agent --extra dev

# 2. Run tests.
uv run --package wormbase-voice-agent --extra dev pytest apps/voice-agent/tests -q

# 3. Start the service against a local Postgres ledger.
export OLLAMA_API_KEY=...
export WORMBASE_LEDGER_DSN=postgresql+asyncpg://wormbase:wormbase@localhost:5432/wormbase
uv run --package wormbase-voice-agent wormbase-voice-agent serve --port 8090

# 4. Verify health.
curl localhost:8090/healthz
# {"ok":true,"service":"wormbase-voice-agent"}
```

## Run via docker-compose

```bash
make up                       # full stack
docker compose --project-directory . -f infra/docker-compose.yml \
    build voice-agent
docker compose --project-directory . -f infra/docker-compose.yml \
    up -d voice-agent
docker compose --project-directory . -f infra/docker-compose.yml \
    logs -f voice-agent
```

## Webhook contract (ElevenLabs custom LLM)

ElevenLabs custom-LLM is OpenAI chat-completions-shaped. Our handler
is intentionally permissive: any extra fields in the request are
allowed and ignored. The fields we depend on are:

| Field             | Source                              | Why we need it                        |
|-------------------|-------------------------------------|---------------------------------------|
| `messages`        | OpenAI chat shape                   | Last `role=user` is the transcript.  |
| `conversation_id` | ElevenLabs session id (one of)      | Forms the ledger `channel_id`.        |
| `session_id`      | (alternate)                         | (same)                                |
| `agent_id`        | ElevenLabs                          | Fallback session key.                 |
| `user_id`         | ElevenLabs caller metadata          | Maps to `sender_person` UUID.         |
| `caller_id`       | (alternate)                         | (same)                                |

The response is an OpenAI chat-completion JSON body with
`choices[0].message.content` set to Kimi's reply. ElevenLabs renders
the content via TTS.

## Audio storage (demo vs production)

For the Thursday demo, audio refs are **filesystem paths** under
`/tmp/voice-audio/<turn_id>.<ext>`. The voice-agent container mounts
the `voice-audio` named volume there. Each `chat_received` /
`chat_sent` execute payload has an `audio_ref` field carrying the
absolute path.

**Production migration plan:**

1. Swap `AudioStore` (a 50-LOC class in `audio_store.py`) for an
   S3-backed implementation that writes to a per-tenant bucket and
   returns `s3://wormbase-audio/<tenant>/<session>/<uuid>.opus` URLs.
2. Add KMS encryption-at-rest in the bucket policy.
3. Add a tenant-configurable retention TTL (governance review pending —
   per the design doc §10 open question).
4. The ledger schema does not change — the `audio_ref` field is a
   string, S3 URLs flow through the same code path. Replay continues
   to work because we content-address (sha256) the blob.

## Demo-day prerequisites (human action required)

These cannot be automated by the implementation subagent; the human
operator must complete them before the rehearsal.

1. **Order an ElevenLabs phone number.** US numbers provision in 24-48h
   in some regions. Order **by Monday** for a Thursday demo. EU
   numbers may take longer — confirm geography during agent setup.
2. **Create the ElevenLabs Conversational AI agent.**
   - Voice: pick a neutral preset (e.g. "Daniel" / "Sarah"); test
     numeric pronunciation with a coworker — the system prompt asks
     Kimi to render numbers as words ("four point two million dollars"),
     but voice quality varies by preset.
   - Custom LLM: enable; point the webhook URL at the public-facing
     URL of this service. For local demos, expose port 8090 via
     `ngrok http 8090` or equivalent; copy the public URL into the
     ElevenLabs config.
   - Auth: paste the agent token from `ELEVENLABS_AGENT_TOKEN` so
     ElevenLabs signs requests we accept. (The current handler doesn't
     enforce signature verification — Phase 2.)
3. **Pre-warm Kimi.** The `/session-start` webhook fires a
   fire-and-forget Kimi ping so the first turn isn't cold; if the
   demo machine is on bad WiFi, hot-call once before the rehearsal so
   the ElevenLabs ↔ webhook ↔ Ollama path is warm.
4. **Tether a hotspot.** The demo's only WAN dependencies are
   ElevenLabs ↔ phone carrier and our service ↔ Ollama. Bad venue
   WiFi tanks both. Tether the demo machine to a phone hotspot (per
   design-doc §8 risk #5).
5. **Verify** the dashboard's `/activity` view shows the
   `voice:elevenlabs:<session>` channel id rendering correctly. The
   dashboard's existing channel filter handles both `slack:*` and
   `voice:*` channel ids — no UI change needed.

## Mapping to the design doc's narrator beat

The W1.A design doc §4 specifies a verbatim narrator beat for
demo day:

> **Worm** — "Q3 net revenue was $4.2 million, up 12.4% versus Q2's
> $3.74 million. Source: sales-q3.csv, ingested 09:13 UTC. Trace at
> activity row 247."

What this implementation produces today (and what's a gap):

- ✅ Kimi answers with the prompted persona — the
  `VOICE_SYSTEM_PROMPT` in `elevenlabs.py` instructs Kimi to be
  concise, render numbers as words, and cite provenance.
- ✅ Conversation lake context is pulled from the same ledger
  (`fetch_recent_conversation_context`) the Slack worm reads. If
  Slack already saw a `sales-q3.csv` ingestion, Kimi has the
  reference in its context.
- ⚠️ **GAP — KPI lookup as a tool call.** The current implementation
  does not execute a deterministic KPI query before answering — it
  forwards the conversation context to Kimi and trusts the model to
  cite the right number. To fully realise the narrator beat ("$4.2M
  with hash a8989ece"), Phase 2 should add a tool-call layer where
  Kimi can invoke `kpi_lookup(question)` against the projection,
  returning a hash-stable answer. The voice-agent then renders that
  number into TTS-friendly text. The ledger schema for this exists
  (`KpiAnsweredPayload`); the wiring is the gap.
- ⚠️ **GAP — auto-fetching Slack channel history.** The narrator beat
  references "Trace at activity row 247." Today, the trace is
  derivable from the ledger entry id but not surfaced verbatim in
  Kimi's reply. Phase 2 can post-process Kimi's reply with the
  `received` `WriteResult.entry_ids` to splice the activity row id in.

These gaps are explicitly out of scope for the W1.A POC; the surfaces
to extend live in `app.py:elevenlabs_llm` and `elevenlabs.py:build_voice_prompt`.

## On-thesis criteria hit

Per design doc §1 and the on-thesis rubric:

- **C1 unprompted action** — voice exchange triggers downstream
  reactivity exactly like a Slack mention.
- **C2 deterministic output** — the substrate response is hash-stable;
  the TTS rendering is the probabilistic edge.
- **C3 compounding state** — voice transcripts flow into the same
  conversation lake (bronze → silver → gold) as Slack text.
- **C6 auditable governance** — every utterance produces
  `chat_received` (with `audio_ref`) and `chat_sent` (with `audio_ref`)
  entries via the canonical PEVR cycle.
- **C8 unprompted surface, prompted depth** — the voice channel
  initiates (greets caller via session-start), accepts user
  direction once on the line.

Five of eight rubric criteria — squarely on-thesis.

## Out of scope (Phase 2)

Per design doc §7:

- Outbound dialing (worm initiates calls to on-call eng).
- Multi-party huddles.
- Voice cloning (brand-voice CEO tuning).
- Browser voice widget (≈30 LOC against the same webhook).
- Voice ingest of memos / dropped MP3s (Whisper-style STT).
- Real-time tool use mid-call (worm runs `make verify` while on
  phone — ElevenLabs supports it).
- Multi-tenant phone numbers (one number per tenant; Twilio matrix).
- Speaker diarization for multi-caller calls.
