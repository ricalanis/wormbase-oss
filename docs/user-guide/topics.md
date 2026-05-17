# `/topics` — User guide

## What it does

The Topics tab is the **silver-conversations cluster view** — what is
actually being discussed in the tenant's chat, grouped by topic. Each
topic carries:

- a name (worm-proposed from top keywords; admin-editable)
- an estimated cluster size (message count)
- top participants (Persons)
- top channels
- a Receipt chip linking to source threads

This is the biggest unclaimed differentiator per the business audit:
**Read.ai does meeting topics; nobody does chat topics; Fivetran admits
they can't sessionize chat.** WormBase does.

Daily for members; weekly for COOs and CMOs (chatter signal for
positioning research).

## First action

If the tenant has been listening for at least 24h:

1. Open `/topics`. Topics render with the largest at the top.
2. Click any topic to see: the auto-extracted summary, the contributing
   threads, the top participants.
3. Click **Open in Slack** on any thread to jump to the original.

If the tenant is brand-new:

1. The empty state explains: "Topics emerge from chat. The worm needs
   ~24h of chatter — or import a transcript."

## Advanced

- **Pin a topic** — click the pin icon. Pinned topics surface in
  `/activity`'s conversations feed with extra weight; you'll see new
  threads on this topic highlighted.
- **Edit topic name** — admin or maintainer-only. Click the name to
  rename. Writes `emit_topic_renamed`.
- **Merge two topics** — admin-only. Pick two topics → **Merge**. Writes
  `emit_topic_merged`. The smaller cluster's threads reattach to the
  surviving topic.
- **Per-Person topic activity** — open `/people/{id}` → "Topics"
  section shows what this Person mostly talks about. Useful for
  "what does Bob actually do?" when assigning positions.
- **Topic drift detection** — `/topics/drift` (admin-only) shows
  topics whose volume changed > 50% w/w. Useful for early signals of
  org-level shifts.

## Behind the scenes

Reads from `projection_topics`, a fold of these ledger entries:

```
emit_topic_proposed        (clustering pass produced a new topic)
emit_topic_renamed
emit_topic_merged
emit_topic_archived
emit_topic_message_attached  (every message that lands in a topic)
```

The topic subsystem currently runs a **naive clustering** — one topic
per `(channel, top-keyword)` pair, top-keyword = simple TF over
whitespace tokens minus a small stopword allowlist. The
projection-builder service (workstream WS4) will swap this for a
proper clustering pass (BERTopic or similar) — same Connector contract,
just better silver-conversation quality.

Topics live at the **silver** layer of the conversation lake — bronze
holds raw chat events, silver applies parsing + topic clustering, gold
aggregates into per-topic process maps and recurring-question rollups.

## Why chat topics are the wedge

Read.ai bills meetings. Fivetran ingests structured data. **Nobody else
sessionizes chat as a first-class data source.** The worm's
conversation lake captures every Slack / Discord / Teams thread,
classifies it into bronze / silver / gold, and surfaces the silver
layer here. Switching cost compounds with conversation history captured
and refined — a worm running for six months in a customer's Slack
carries process knowledge that cannot be replayed elsewhere and would
take another six months to rebuild.

This is the **agentic process bookkeeping** principle: the worm mines
the data the org is already throwing away.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Empty after a week | Clustering threshold too high | Lower via `/settings/topics`; or wait |
| Topics look noisy / generic | Naive TF-IDF; awaiting WS4 upgrade | Manually merge similar topics; mark for retraining |
| Pinned topic not surfacing in /activity | Activity feed cache stale | Refresh; or click into the topic to force a re-rank |
| Edit topic name silent | Lacking `tenancy.admin` or topic-resource maintainer grant | Ask an admin |
| Drift detection flat | Tenant too small (< 30 days of chatter) | Wait |
