# Process retrieval (Step 3c)

> Realises **Step 3c — Process retrieval** of the canonical 5-step product
> arc spec. See
> [`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`](../../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md)
> for the customer-facing narrative.

The worm reads its own conversation lake (every
`channel_adapter.emit_chat_received` ledger entry the channel-adapter
writes after an inbound chat arrives) and promotes structured
artefacts back into the ledger:

| Output kind | Tool name | What triggers it |
|-------------|-----------|------------------|
| Decision record | `emit_decision_recorded` | "we decided X", "let's go with Y", "approved", "agreed" |
| Process map | `emit_process_map_proposed` | Ordered actor → action sequences ("first Bob exports, then Alice reviews") |
| System map node | `emit_system_map_node` | Running tally of who-mentions-whom, what-channels-host-what-topics, flushed every N batches |
| Recurring question | `emit_recurring_question` | A normalized question observed ≥ 2× in the lake |

Each output goes through the canonical PEVR write primitive
(`propose → execute → verify → resolve`), so every artefact is
hash-chained, tenant-scoped, and replayable.

---

## Pipeline shape

```
                ledger.execute(channel_adapter.emit_chat_received)
                                       │
                            ┌──────────▼──────────┐
                            │  ProcessExtractor   │
                            │  (loop, 5s/60s)     │
                            └─┬────┬────┬────┬────┘
                              │    │    │    │
                              ▼    ▼    ▼    ▼
                        ┌───────┐┌─────┐┌─────┐┌────────┐
                        │decisn.││proc.││sys. ││recur.  │
                        │heur+  ││heur ││map  ││Levensh.│
                        │Kimi   ││+Kimi││tally││cluster │
                        └───────┘└─────┘└─────┘└────────┘
                              │    │    │    │
                              ▼    ▼    ▼    ▼
                        emit_decision_recorded
                        emit_process_map_proposed
                        emit_system_map_node
                        emit_recurring_question
                              │
                              ▼
                       Postgres ledger
                              │
                              ▼
              Dashboard /decisions, /processes, /system-map
```

The extractor is wired in as a background task by `cli._run_async` next
to `chat_received_reactivity_poller`. The two never compete for the
same rows — the poller forwards them into the relevance gate, the
extractor folds them into structured artefacts.

---

## Heuristics + Kimi: the hybrid

Every extraction stage runs heuristics first, then asks Kimi only for
residual coverage. This pattern is borrowed from `OllamaCloudClassifier`
and gives us three useful properties:

1. **Demo determinism.** When the cloud is offline (or
   `OLLAMA_API_KEY` is unset, e.g. during CI), the extractor still
   produces evidence. The acceptance test fixtures all run in this mode.
2. **Cost discipline.** Kimi is only called for messages that look
   decision-shaped or sequence-shaped — a single regex pass per
   message keeps the budget bounded.
3. **Compounding state.** Heuristic catches feed the same ledger as
   Kimi catches; replay reproduces the same state regardless of
   which path produced the entry.

### Decision detection

Pre-filter regex tests for any of: `we decided / agreed / approved`,
`let's go with`, "sign off", "ship it", "lgtm". Surviving messages are
batched into a single Kimi prompt:

```
You are WormBase's process retriever. The user gives you the latest
batch of chat messages from a single channel. Detect any explicit
DECISION the team made. Output JSON ONLY.

Schema:
{"decisions": [
  {"text": "<short decision text>", "evidence": ["<message_id>", ...],
   "deciders": ["<sender_person uuid>", ...], "confidence": 0.0-1.0}
]}
```

If the Kimi call fails or returns no decisions, every pre-filter hit
is promoted as a heuristic decision with `confidence = 0.55`.

### Process maps

Two regex patterns catch the bulk of cases:

* `first <actor> <verb>, then <actor> <verb>, [finally <actor> <verb>]`
* `<actor> <verb> → <actor> <verb> [→ <actor> <verb>]`

Domain is heuristically detected from token hits (`q3 / close / revenue`
→ `finance`; `deploy / release / incident` → `eng`). When no heuristic
fires, Kimi is called with a similar JSON-only schema.

### System map

The extractor maintains an in-memory tally:

* `person_to_person`: every `@<name>` mention adds an edge weight.
* `person_to_channel`: every message increments the sender↔channel edge.
* `channel_to_topic`: every message increments the channel↔domain edge.

These are flushed as `emit_system_map_node` entries every
`flush_system_map_every` batches (default = 1, i.e. every cycle). The
flush is idempotent — re-running on the same input produces the same
node states.

### Recurring questions

Every question (heuristic: `?` or starts with a wh-word) is normalized
(lowercase, strip stopwords + pronouns, keep nouns/verbs) and
clustered. Two heuristics decide cluster membership:

1. **Token Jaccard ≥ 0.5** — catches "q3 net revenue" vs
   "q3 net revenue this quarter" cleanly.
2. **Levenshtein ≤ max(4, len/2)** — catches inflection / typo drift.

A cluster is emitted as a `RecurringQuestionPayload` once
`occurrences ≥ 2`; subsequent emissions update `occurrences`,
`last_seen_at`, and (at `≥ 4`) `suggested_automation`.

The `question_id` is derived deterministically from the canonical
form via `uuid5(NAMESPACE, canonical)` so the same cluster always
produces the same UUID across runs.

---

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `OLLAMA_API_KEY` | unset | Required for the Kimi path. Heuristics-only when absent. |
| `OLLAMA_API_BASE` | `https://ollama.com` | Override for self-hosted Kimi. |
| `WORMBASE_DEV` | unset | When `1`, default poll interval is 5s instead of 60s. |
| `WORM_CORE_PROCESS_EXTRACT_INTERVAL_S` | (auto) | Explicit poll interval override. |

---

## On-thesis criteria

The Triad alignment for this subsystem (per `CLAUDE.md`):

| Criterion | How it's hit |
|-----------|--------------|
| C1 unprompted action | The extractor runs without being asked; the worm builds the org bookkeeping that humans never get around to. |
| C3 compounding state | Recurring-question clusters and system-map tallies grow in place; the ledger replays to the same state. |
| C6 auditable governance | Every decision/process/node lands as a hash-chained ledger entry with a confidence score. |
| C7 domain specialization | Heuristics include a finance/eng/marketing domain detector seeded for SaaS. |

> **Verbatim phrases used:** "compounding", "synthesis at ingestion",
> "knowledge compiled, not re-derived", "auditable governance",
> "unprompted surface, prompted depth".

---

## Testing

* `apps/worm-core/tests/test_process_extractor.py` — synthetic
  `_ChatRow` fixtures driven through `extract_from_rows`, asserting
  the four expected ledger payloads land for the canonical Q3-close
  demo arc.
* `packages/ledger/tests/test_entries.py` — round-trip the four new
  payload models, validate confidence/occurrence bounds, ensure
  `extra='forbid'`.
* `apps/dashboard/tests/unit/process-views.test.tsx` — render
  `DecisionsTable`, `ProcessDiagram`, `SystemMapGraph` against mock
  data, exercise empty states + filters.
