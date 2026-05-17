# `/decisions` — User guide

## What it does

The Decisions tab lists every decision the worm has extracted from channel
chatter. A decision is a sentence like "we decided to push the Q3 close to
Friday" — the worm's process_extractor classifies it, attaches the
contextual messages around it, and writes a record. Each row carries:

- the decision text (verbatim or paraphrased)
- the actors involved (Persons + roles)
- the channel + timestamp + thread link
- a Receipt chip linking to the source messages
- a confidence score
- the cited data products (if the decision references a chart or report)

A sidebar shows the **top recurring questions** — chatter patterns the
worm has flagged as candidates for automation ("Carol asked Q3 revenue 4
times this quarter — want a daily snapshot?").

This is the COO's weekly surface. Auditors live here.

## First action

If the tenant has been listening for at least a few hours:

1. Open `/decisions`. Decisions render in reverse-chronological order.
2. Click the row's Receipt chip. The drawer opens with the source thread
   inline + the inferred actors + the cited data products. The thread is
   scrollable; the worm highlights the message it classified as the
   decision sentence.
3. Click **Open in Slack** to jump to the original thread (deep-link
   preserves the timestamp).

If the tenant is brand-new:

1. The empty state explains: "Decisions auto-extract from chat. Ask the
   worm to lurk for a few hours before you check back. Or drop a chat
   transcript and the worm will extract decisions from history."
2. Optional power-user path: click **Import a transcript** to upload a
   chat history JSONL — the worm runs the same extractor against it.

## Advanced

- **Filter by domain** — chip in the header. URL-driven; shareable.
- **Endorse a decision** — admin-only. Writes `emit_decision_endorsed` so
  the worm raises this decision's weight in future processes.
- **Reject a decision** — admin-only. Writes `emit_decision_rejected` —
  the worm learns this pattern wasn't actually a decision (training
  signal).
- **Cite a data product** — open a decision drawer, click **Add citation**,
  pick a data product. Writes `emit_data_product_consumed` with
  `surface=decision`. The data product's consumption count increments;
  auditors can trace **decision → artifact → source bytes → ingest
  provenance**.
- **Recurring questions sidebar** — click a row to see the question text,
  occurrence count, asking Persons, and "Propose automation" CTA. The CTA
  writes `emit_data_product_proposed` with `kind=recurring_summary`,
  scheduled.
- **Audit a decision via MCP** — external AI clients (Claude Desktop) can
  call the `audit_decision` prompt against the MCP server. The prompt
  walks decision → process map → KPIs → source bytes end-to-end and
  writes one `emit_mcp_call_received` row. See
  [`/mcp` user guide](mcp.md) and Beat 8 of
  [`docs/demo-runbook.md`](../demo-runbook.md).

## Behind the scenes

Reads from `projection_decisions`, a fold of these ledger entries:

```
emit_decision_recorded     (process_extractor classified a decision)
emit_decision_endorsed     (admin click)
emit_decision_rejected     (admin click — training signal)
emit_data_product_consumed (when a data product is cited; surface=decision)
emit_recurring_question    (question pattern recognized — sidebar source)
```

The process_extractor lives in
`apps/worm-core/src/wormbase_core/process_extractor.py`. It runs on every
new chat batch (~1-minute cycle), pulls the last N messages per channel,
runs them through a relevance gate, and writes `emit_decision_recorded`
when a decision pattern matches.

Recurring questions surface from `projection_recurring_questions`, a fold
of `emit_recurring_question` keyed by `(question_normalized,
asking_person_id)` — increments on each new occurrence.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Tab empty after weeks of chat | process_extractor crashed silently | `make worm-logs \| grep process_extractor`; restart |
| Decision text says "[redacted]" | Channel is `classification=pii`, current Person lacks the grant | Ask domain owner for the grant; or view via an observer who has it |
| Receipt chip 404s | Source message deleted in Slack post-extraction | The decision row stays; the chat link is best-effort |
| Recurring questions sidebar empty | Tenant new (< 7 days of chatter) | Wait; or import a transcript |
| Endorse / reject silent | Current Person lacks `tenancy.admin` | Ask an admin |
