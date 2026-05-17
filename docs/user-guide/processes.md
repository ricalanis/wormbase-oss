# `/processes` — User guide

## What it does

The Processes tab renders every process map the worm has extracted from
channel chatter as a **swimlane diagram**. A process map is an ordered
sequence of actor → action steps the worm inferred from chat ("first Bob
exports, then Alice reviews, then Carol approves, then it's posted"). Each
map carries:

- a name (worm-proposed or admin-edited)
- the swimlane diagram (actors as lanes, actions as boxes)
- contributing chat messages (source thread links)
- a confidence score
- a Receipt chip
- a freshness badge (when the worm last saw this process fire)

This is the COO's daily surface. Operations folks live here.

## First action

If the tenant has chat history:

1. Open `/processes`. Maps render with the highest-confidence at the top.
2. Click any swimlane to drill into that step's source messages.
3. Click **Edit** on any map to open the `ProcessMapEditor`. Reorder
   steps, rename actions, mark a step as `automated`. Each edit writes
   `emit_process_map_edited` with the diff.

If the tenant is brand-new:

1. The empty state explains: "Process maps auto-build from chat. The worm
   needs to see a process fire 2-3 times before it proposes a map. You
   can also draft one manually."
2. Click **Draft a process** to open the editor with a blank canvas.
   Writes `emit_process_map_proposed` with `proposed_by=<you>` once
   you save.

## Advanced

- **Endorse a process** — admin-only. Writes `emit_process_map_endorsed`.
  The worm prioritizes this process in future system-map weighting.
- **Mark a step as broken** — click any step → "Mark broken". Writes
  `emit_process_map_step_broken {step_id, reason}`. The worm watches for
  the next time this process fires and proposes a fix.
- **Mark for automation** — owner-only. Writes
  `emit_process_automation_proposed`; the autoresearch loop picks this
  up and proposes experiments to automate the step.
- **Click an actor lane** to open the actor's `/people/{id}` page filtered
  to this process — see what else this Person owns.
- **Compare versions** — every edit creates a new version. Click
  **History** to see the diff between versions; useful for
  "when did this process change?" audits.

## Behind the scenes

Reads from `projection_process_maps`, a fold of these ledger entries:

```
emit_process_map_proposed       (process_extractor inferred from chatter)
emit_process_map_confirmed      (admin click)
emit_process_map_endorsed       (admin signal — raise weight)
emit_process_map_edited         (drag-and-drop or rename in editor)
emit_process_map_step_broken    (admin flagged a step)
emit_process_automation_proposed (link to autoresearch experiment)
emit_process_map_archived       (soft delete)
```

The process_extractor (the same module that produces decisions) groups
related decisions into ordered sequences when the same actor pattern fires
≥ 2 times in a similar context. Threshold is configurable per tenant (lower
threshold = more proposals, more noise; tunable from `/settings`).

Each process map links to its contributing `emit_decision_recorded` rows
via `decision_ids[]` in the projection — that's how the swimlane drill-in
shows source messages.

## Process retrieval is the worm-eye view of the org

Process retrieval (alongside decisions, system map, recurring questions)
is **agentic process bookkeeping**. The worm reads its own conversation
lake (channel-adapter writes every message; the conversation pipeline
runs bronze → silver → gold for **conversations** as a first-class data
source) and extracts:

- decisions ("we decided to push the Q3 close to Friday") → `/decisions`
- process maps ("Q3 close flows: Bob → Alice → Carol") → this tab
- system maps (org graph) → `/system-map`
- recurring questions (chatter patterns) → `/decisions` sidebar

After 24 hours of observation, the dashboard shows: "here's how Q3 close
actually flows through your team — and where it breaks."

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Empty after a week | Tenant chat volume too low for the threshold | Lower the threshold via `/settings`; or import a transcript |
| Swimlane shows wrong actor | Process_extractor confused two Persons with similar names | Open `/people`; check identities; merge if dup |
| Editor crashes on save | `process_map.cells` exceeded the 100-step cap | Split into two maps; or raise the cap via `/settings` (admin) |
| Confidence stuck low | Worm has seen the process once, not yet ratified | Endorse manually to raise the weight |
| Source thread 404s in drill-in | Slack message deleted | Process map persists; thread link is best-effort |
