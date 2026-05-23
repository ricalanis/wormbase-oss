# Agent-Driven Lake Extension — Sprint 2/3 Sketch

**Status:** sketch (not for Monday). Captures the architectural intent so the Sprint 1 CLIs (`wormbase-ingest-transcript`, `wormbase-pull-fireflies`) aren't read as "the answer" — they're the pragmatic interim layer.

**Origin:** raised during 2026-05-23 brainstorm — *"can we try to generate an agent that allows that abstract generation of the lake? would the agent lake be used for this?"*

## The insight

The Sprint 1 pull-fireflies CLI works, but it's a one-off — every new vendor needs its own script. The repo already has a better abstraction one layer up: `SurfaceDriver` in `packages/lake-surfaces/`, with a thin `MCPSurfaceDriver` that wraps any MCP server in ~30 lines (`make_mcp_preset`). Six MCP presets already ship (atlassian, github, gworkspace, hubspot, linear, notion).

The architecturally consistent answer to "how do I add Fireflies?" is **not** "write a Python script" — it's **"register a `SurfaceDriver`, then let the agent invoke it via MCP tools the same way it invokes every other source."**

## Staged migration

### Now (Monday 2026-05-25 — shipped)

- `wormbase-ingest-transcript` — SRT → `chat_received` entries. Operator-run.
- `wormbase-pull-fireflies` — Fireflies API → `chat_received` via the above. Operator-run, idempotent.
- Both share `ingest_turns(...)` as the canonical turn-emission helper.

This is the **mechanical-turk layer**. Ricardo runs the CLIs weekly; the lake grows. Adequate for week 1 of design-partner operation.

### Sprint 2 (weeks 2-3) — formalize Fireflies as a `SurfaceDriver`

Two paths depending on whether Fireflies ships a public MCP server:

**Path A — Fireflies publishes an MCP server** (current state: not yet, but watch their changelog)
- Add `packages/lake-surfaces/src/wormbase_lake_surfaces/mcp_presets/fireflies_preset.py` — ~30 lines.
- `kind="mcp:fireflies"`, `server_url=<from Fireflies docs>`, `required_secrets=("bearer_token",)`.
- Driver appears in `default_registry()`, the dashboard picker, `/api/v1/connectors`.
- The Sprint 1 CLI stays as a fallback but becomes the slow path.

**Path B — No MCP, native driver wrapping the GraphQL API**
- Add `packages/lake-surfaces/src/wormbase_lake_surfaces/fireflies.py` — native `SurfaceDriver` following the `linear.py` (GraphQL) template.
- ~4-6h of work. The CLI's `_fetch_transcripts` + `_sentences_to_turns` logic lifts straight in.
- Once landed, the CLI becomes redundant; deprecate but keep one release as a fallback for ops.

Both paths converge on: **Fireflies becomes addressable to `SourceBuilder.build_full_sequence(...)` like every other source.** No more vendor-specific CLI scripts.

### Sprint 3 (weeks 4+) — the agent decides

The lift that turns this from "operator-driven" to "agent-driven":

1. **Reactivity to detect source mentions in conversation.** Pattern: in `packages/wormbase-research-loop/` (or a new reactivity), watch `chat_received` events for phrases like "we use X," "our data is in X," "you'd find that in X." Match against the `default_registry()` of known drivers OR against a "candidate sources" list curated by the agent.
2. **`promote_source_candidate` MCP tool** (already exists at `apps/worm-core/src/wormbase_core/write_actions.py:3980`) — the reactivity invokes this with the matched source. Writes a `source_proposed` ledger entry with provenance "mentioned by <person> in <channel> at <seq>".
3. **Operator approval surface** — dashboard widget or DM to the operator: "Ruben just mentioned Hubspot at [seq 4720]. Wire it? (yes/no/edit)." Approval triggers `source_confirmed` → `source_connected` via the existing `SourceBuilder` flow.
4. **Auto-pulled secrets** — for vendors with OAuth, the dashboard pulls the operator into the consent flow once; subsequent re-uses go straight through `CredentialBroker`.

The end state matches the pitch: *"As you mention sources, I wire them."* The agent does it; Ricardo approves.

## Why this matters for the customer story

The Altis pitch explicitly framed source-connection as a **continuous, conversation-driven process**. The CLI is honest but not the story Ricardo told Rubén. The Sprint 3 state IS the story. Capturing it now means:

1. The Sprint 1 CLI isn't accidentally treated as the architecture.
2. The Sprint 2 refactor is scoped against a real target (not "make it better somehow").
3. When Altis asks "how does this scale to our 5 client companies?" — the answer is the Sprint 3 surface, not a more elaborate script.

## What this design does NOT cover

- The specific reactivity heuristic for detecting source mentions (NLP / pattern matching / agent-LLM-call) — open design question for Sprint 3.
- The dashboard UX for source approval — needs design work.
- Multi-tenant secret isolation beyond what `CredentialBroker` already does.
- Whether `mcp:fireflies` ever ships (out of our control).

## What it explicitly endorses

- The Sprint 1 CLIs are **fine** — keep them; don't pre-emptively refactor.
- The next refactor target is **the `SurfaceDriver` formalization**, not a more elaborate CLI.
- The end state is **agent-driven**, with the operator in the loop only at the consent/approval step.
