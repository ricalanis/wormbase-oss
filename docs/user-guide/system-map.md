# `/system-map` — User guide

## What it does

The System Map tab renders the **org graph** the worm has inferred from
channel chatter. Persons + channels are nodes; edges are weighted by
message count. The view is a force-directed graph; node size scales with
total message volume; edge thickness scales with bilateral chatter.

This is the COO's weekly surface. New hires use it to find "who do I
ask about X?" without polling everyone.

## First action

If the tenant has been listening for at least a few days:

1. Open `/system-map`. The graph renders the top ~30 nodes by message
   volume.
2. Hover any node to see the Person's position + recent topics.
3. Click any edge to see the conversation thread sample between the
   two endpoints.
4. Use the **filter** chip to narrow by domain ("show me only finance
   chatter") or by time range ("last 30 days").

If the tenant is brand-new:

1. The empty state explains: "System map auto-builds from chat. The
   worm needs ~24h of chatter for a meaningful graph."
2. Optional: click **Bootstrap from org chart** to upload a static org
   chart CSV — the worm will attach actual chatter weights to those
   relationships once they exist.

## Advanced

- **Layout algorithm** — force-directed default. Picker offers
  hierarchical (top-down org chart shape), circular (round-robin),
  geographic (if Person rows have location attribute).
- **Per-channel sub-graphs** — click any channel node → **Focus**.
  Renders the sub-graph of just the people who post in that channel,
  weighted by their participation.
- **Edge details** — click any edge to drill into the conversation
  thread sample (first 5 threads where these two endpoints
  participated).
- **Find a person** — search by name in the chip; the graph highlights
  + zooms.
- **Detect silos** — admin-only. **Find silos** runs a community
  detection pass; surfaces clusters that don't bridge to the rest of
  the graph. Useful for "are our teams over-fragmented?" audits.
- **Detect bottlenecks** — **Find bottlenecks** highlights nodes whose
  removal would disconnect the graph (high betweenness centrality).
  These are usually the COO and the senior engineer everyone asks.

## Behind the scenes

Reads from `projection_system_map_nodes` + `projection_system_map_edges`,
folds of:

```
emit_system_map_node       (one per Person + channel; updated on every chat batch)
emit_system_map_edge       (one per (sender, recipient_or_channel) pair; weighted)
emit_system_map_edge_weight_updated  (re-flush of edge weights periodically)
```

The system-map subsystem in
`apps/worm-core/src/wormbase_core/system_map.py` runs on every new chat
batch. It increments edge weights using a decay (recent chatter weighted
heavier than old) and writes `emit_system_map_edge_weight_updated`
periodically.

The dashboard's graph is rendered with React Flow. Polling cadence: every
30 seconds. Force-directed layout is computed client-side with
d3-force.

## Process retrieval — the worm-eye view

The system map is one of four lenses produced by the worm's
process-retrieval subsystem (alongside decisions, processes, recurring
questions). Together they answer: "what does this org actually do, and
how?"

After 7+ days of observation, the dashboard surfaces a **strong**
system map — admins can compare it to their static org chart and find:

- silos (clusters with no cross-traffic)
- bottlenecks (Persons whose removal would disconnect the graph)
- under-used channels (created but no chatter)
- heroes (Persons with abnormally many edges — usually the
  question-routers, often unrecognized)

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Empty graph after a week | `system_map` subsystem crashed | `make worm-logs \| grep system_map`; restart |
| Nodes overlap unreadably | Default zoom too tight | Use the +/- zoom controls; or pick hierarchical layout |
| Edge weights flat | Edge weight updater not running | `make worm-restart`; the updater runs every 5 min |
| Search highlights nothing | Person not in this view (filtered or no chatter) | Clear filters; or check `/people` for status |
| Silos detection finds none | Tenant too small (single team), or noise threshold too low | Lower the silo threshold via `/settings` (admin) |
