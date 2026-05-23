# Weekly Report Template

> Use this template to deliver the **Friday weekly report** to a design partner during the mechanical-turk phase (week 1 onward, until the agent generates these automatically).
>
> Spec: `docs/superpowers/specs/2026-05-23-altis-kickoff-readiness-design.md`.
> Filed in the ledger via `record_decision` PEVR with `category="weekly_report"` (see §"How to file" at bottom).

---

## Why this template exists

The Altis pitch (call 2026-05-22) framed the bot as a listener while Ricardo personally generates weekly insights. The promise is **a useful report each Friday**. Improvising the format kills compounding trust week-over-week; the same skeleton each week lets Altis recognize "the WormBase report" as a thing.

The template captures what the agent will eventually compose. Filing it in the ledger via `record_decision` means the report is a first-class lake event — searchable, citable, replayable.

---

## The template

Open a new file:
`/tmp/wormbase-report-<tenant>-week-<YYYY-MM-DD>.md`

Fill in section-by-section. Cite ledger seqs in square brackets so any claim is traceable to the entry that produced it (e.g. `[seq 4823]`).

```markdown
# WormBase Weekly — <Tenant Name>
**Week of:** YYYY-MM-DD to YYYY-MM-DD
**Author:** Ricardo (mechanical-turk phase)
**Filed:** YYYY-MM-DDTHH:MM in altis ledger via record_decision
**Sources active:** <e.g. WhatsApp (3 channels), Fireflies (5 meetings)>

---

## 1. What the lake heard this week

One paragraph + bullet list. What ingested, in volume terms.

- **X meetings ingested** — <comma list of titles>. Total Y turns.
- **N WhatsApp messages across M channels** — most-active channel: `<channel-label>`.
- **K new data sources connected** (if any) — `<source kind>` for `<purpose>`.

Anchor each fact to a ledger range: `[seq 4567–4626]`.

---

## 2. Decisions detected

Up to 5 explicit decisions or commitments said in the week, with the context that
made them stand out.

- **Decision:** <one sentence — "Move kickoff to Tuesday">.
  **Context:** <why it matters — who, when, in what conversation>.
  **Citation:** `[seq 4815]` (chat_received) or `[meeting altis-acme-discovery, 12:34]`.
- ...

Skip the section entirely if there are <2 real decisions — don't pad.

---

## 3. Open questions / unresolved threads

Things the conversations raised that haven't been answered. These are the
candidates for next-week's first agent prompts.

- **Q:** <question as quoted from the conversation>.
  **Last touched:** `[seq 4720]`, no response since.
- ...

---

## 4. Pattern observations (optional, 0-3 items)

Higher-order things you noticed across multiple conversations. Don't force
this section if there's nothing real.

- E.g. "Three separate client calls mentioned 'pipeline visibility' as a
  pain point this week — `[seq 4502, 4631, 4798]`."

---

## 5. Sources we should connect next week

Based on what was mentioned in conversation (cite the seq where it came up).

| Source | Mentioned by | Citation | Why it'd matter | Effort to wire |
|---|---|---|---|---|
| Hubspot | Ruben | `[seq 4720]` | "All deal data lives here" | ~30 min (MCP preset exists) |
| Read.AI | Poncho | `[seq 4825]` | "Some calls are recorded here, not Fireflies" | ~3-6h (no driver yet — see source-connector-cheatsheet §3) |

If empty: "Nothing new mentioned this week. Current sources are sufficient."

---

## 6. Ricardo's commitments for next week

What you'll deliver by next Friday.

- [ ] Connect <source>
- [ ] Generate the next weekly report by <date>
- [ ] <one specific analytical artifact, e.g. "Map of who-talks-to-whom across the 3 client channels">

---

## 7. Operator notes (private — not in the report sent to Altis)

Things to remember for the next iteration. NOT included in the markdown
you send to the customer; kept here for your own log.

- Friction encountered this week: ...
- Things to add to `docs/known_issues.md`: ...
- Things to ask Altis on next call: ...
```

---

## How to file the report in the ledger

Two write paths, do BOTH:

### A. File the report markdown in the ledger via `record_decision`

```bash
# Compose the report at /tmp/wormbase-report-altis-week-2026-05-30.md, then:
uv run python -c "
import asyncio
from uuid import uuid4
from wormbase_core.write_actions import record_decision
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_ledger import Ledger
import os

async def main():
    ledger = Ledger(os.environ['WORMBASE_LEDGER_DSN'])
    tenant = 'altis'
    company_id = tenant_to_company_uuid(tenant)
    decision_id = uuid4()
    with open('/tmp/wormbase-report-altis-week-2026-05-30.md') as f:
        report_md = f.read()
    await record_decision(
        ledger=ledger,
        company_id=company_id,
        decision_id=decision_id,
        title='Weekly report 2026-05-30',
        decision_text=report_md,
        category='weekly_report',
        decided_by='ricardo-manual',
    )
    print(f'filed decision {decision_id}')

asyncio.run(main())
"
```

(Verify the exact `record_decision` signature in `apps/worm-core/src/wormbase_core/write_actions.py:1577` before running — params may differ.)

### B. Deliver to the customer

For Altis specifically (WhatsApp-first): send the rendered markdown as a
WhatsApp message in the internal `WormBase × Altis (Kickoff)` group. Keep
section headers; WhatsApp renders `*bold*` and `_italic_`. If the report
is long (>5 messages-worth), drop a Google Doc / Notion link instead and
post the LINK in the group.

Optional (week 3+): a `wormbase-publish-report` CLI that auto-DMs the
report markdown to each tenant's designated recipient list. Skip for
now — manual delivery is fine while we learn what shape Altis actually
wants.

---

## Quality bar — what makes a "good" first report

After the report is drafted, sanity-check against these (5-min review):

- [ ] **Every fact cites a ledger seq** — if a claim has no `[seq N]`, either drop it or find the seq
- [ ] **At least one item the operator (Ruben) couldn't have seen by just scrolling WhatsApp themselves** — this is the value-add bar; if everything in the report is just "you said X, then Y said Z," there's no insight
- [ ] **One concrete commitment for next week** — momentum signal
- [ ] **No vapor**: don't say "we'll connect Hubspot" if you don't have a real plan; don't claim "the lake learned X" if it's just one event
- [ ] **Under 800 words** — long reports get skimmed; long reports also signal "I'm padding"

If the report fails any of these checks AFTER 2h of work, ship it anyway with a private note in §7 about what to fix next week. Reports that miss the Friday window are worse than reports that miss the bar.
