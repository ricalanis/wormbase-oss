# WormBase product arc — the canonical 5-step story

> **Status:** canonical spec. Every subagent dispatched after 2026-04-26 must map its work onto one of these five steps and reference this document.

> **Audience:** institutional AI investor / customer (a16z-adjacent). The worm replaces a senior data analyst seat by being deterministic, auditable, unprompted, and **personalized to each user's role** — not by being a chatbot.

---

## The 5 steps

```
1.  CONNECT          Install. Worm joins ANY chat platform. Conversations flow.
2.  GROW THE LAKE    Medallion (bronze → silver → gold), every layer in between,
                     across all six source-building flows.
3.  BUILD CONCURRENTLY    KPIs in a tree, governance over every resource,
                     processes retrieved from conversation history. All three
                     grow together; none is a separate phase.
4.  PRODUCE + CONVERSE   Data products generated from the lake. Text + voice
                     conversational interface. Every answer is receipt-backed.
5.  SELF-IMPROVE PER USER    Karpathy-style autoresearch loop, parameterized
                     by each user's role/position. Each person gets their own
                     analyst seat that gets sharper over time.
```

This sequence is the customer journey **and** the demo arc. Step 1 maps to Act I; Step 2 to Act II; Steps 3-5 collapse into Act III (concurrent growth + products + per-user improvement).

---

## Step 1 — CONNECT (chat platform only, one tap)

> **REVISED 2026-04-27 (supersedes the connector-first revision):** Tier 0 is one tap — connect the chat platform. Nothing else. A default local data source (playing all three medallion layers) is pre-provisioned per tenant; the worm works against it from minute zero. External data sources are progressive enhancement, added later via conversation OR `/sources/new`. See `feedback_minimal_friction_onboarding.md` for the durable principle. The connector-first framing in §17 of the dashboard PRD is REVISED — connector grid moves from `/onboarding` to `/sources/new` (where it always was, just without the duplicate front door).

**Goal:** time-to-first-event ≤ 60 seconds from sign-up. **Platform-agnostic** — the worm is not a Slack add-on. The team comes with the install — Persons are auto-discovered, role-graded, and onboarded without a separate user-management step.

**Mechanics:**
- Customer signs up → a tenant is provisioned (multitenancy: each company has an isolated `company_id`, scoped data + governance + processes + KPIs + improvement history + `Person` roster).
- The **installer** (the person who runs the install) becomes the tenant's first admin **and** the first `Person` row. Their `Person` is created from platform OAuth: name + email + avatar + the position they self-declare in Tier 2. They auto-grant themselves `tenancy.installer + tenancy.admin + domain.owner(*)`.
- Customer connects a chat platform via the OpenClaw `@connect <platform>` UX. **Day-one platform list is the FULL OpenClaw set** — Slack, Discord, Teams, WhatsApp, Signal, Matrix, IRC, Google Chat, Telegram, iMessage, Bluebubbles, Feishu, etc. (50+). The worm doesn't care which platform; the `ChannelAdapter` normalizes events into ledger entries with a uniform shape.
- The worm joins channels (one click per channel; bot identity is per-tenant). Speak is gated; ingest is on. Listen-for-ingest is always on.
- The onboarding wizard explicitly walks the installer through their **position** (CFO, data engineer, marketing lead, ops, customer success, etc.) which seeds Step 5's per-user autoresearch with role-appropriate initial metrics.
- **Auto-team-discovery** runs from the first wire event: every unknown `platform_user_id` triggers `emit_person_proposed`. Within the first day (or batch-confirmed during Tier 3) every chatter in every connected channel becomes a `Person` row — proposed by the worm, confirmed by an admin. Each `Person` has zero or more `PersonIdentity` rows (one per platform), so a single Bob spans Slack + Discord + Teams under one `person_id`.
- **Three role facets** are available from minute one — `tenancy` (installer / admin / member / observer), `domain` (owner / contributor), and `resource` (maintainer / contributor). The worm proposes `resource.maintainer` grants from chatter signal (whoever drops the file, pastes the credential, or owns the channel becomes the proposed maintainer). Admins confirm. Every grant is a ledger entry with audit trail.

**On-thesis criteria hit:**
- C1 unprompted action (worm proposes Persons, identities, role grants)
- C3 compounding state (team graph compounds alongside lake graph)
- C6 auditable governance (every Person creation, identity link, and role grant is a ledger receipt)
- C7 domain specialization (built around chat-as-substrate, role-aware, not a general assistant)
- C8 unprompted surface, prompted depth (worm starts observing and proposing Persons without being told to)

**Demo beat (REVISED 2026-04-27):** "no integration project. no IT ticket. no data-source authentication. no credential paste. **One tap** — install one chat app: Slack, Teams, Discord, WhatsApp, anything. The worm joins your channel. A default local data lake is already there, ready to grow with your conversations. **Within a minute** the worm is in the room, your team is being auto-discovered, and the lake is logging every message. Pull external data when you're ready — paste a Stripe API key in a DM, click 'Add source' on the dashboard, or wait for the worm to ask. **Read.ai for data, but for your whole company.**"

> Implementation reference: `docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md` §3-§6 (channel abstraction, identity model, role facets, lifecycle).

---

## Step 2 — GROW THE LAKE (lazy + progressive; default local lake from day one)

> **REVISED 2026-04-27:** the lake starts NON-EMPTY. Every tenant gets a default `LocalLakeConnector` pre-provisioned during install — a self-contained source that plays all three medallion layers (bronze: raw conversation events from the ledger + uploaded artifact bytes; silver: parsed Persons / decisions / processes; gold: aggregated metrics + KPI views). The worm answers questions about Persons, channels, decisions, and processes from minute zero against the local lake — no external source required.
>
> **External sources are progressive enhancement.** The six source-building flows below still apply, but they fire WHEN THE TENANT NEEDS THEM, not at install time. Bronze, silver, and gold layers can land in any combination — a connector can ship just gold (a KPI feed), or bronze+silver only (raw + parsed without aggregation), or all three. The medallion cascade is a reusable orchestrator, not a forced ordering at install.

**Goal:** every data source — internal or external, file or stream, dropped or discovered — flows through a uniform medallion pipeline. Bronze captures the raw bytes (hash-stable, replayable). Silver applies inferred schema, types, and governance classification. Gold produces business-ready aggregates ready for KPI consumption. **The default LocalLakeConnector ships all three from day one against the tenant's own ledger projections + a local filesystem store.**

**Six source-building flows** (all five from PRD §4 + new lake-discovery):

| Flow | Trigger | Demo beat |
|---|---|---|
| `drop_and_profile` | File dropped in channel | "Bob drops sales-q3.csv, worm proposes adding it as a source" |
| `credential_offered_in_dm` | Token / connection string in DM | "Carol DMs the Stripe API key, worm connects" |
| `mentioned_in_conversation` | "we should pull from X" in chat | "Bob: 'we should integrate Stripe' → worm: 'want me to wire that up?' → DM the key → connected" |
| `dashboard_form` | Manual add via UI | Power-user escape hatch |
| `kpi_gap_triggered` | Worm observes a KPI tree gap | "Carol asks Q3 net revenue, worm: 'I don't have that data — DM me your warehouse credentials and I'll connect'" |
| `lake_discovery` (NEW) | Existing lake catalog walked at install time | "Customer points worm at their Snowflake instance — worm walks 50 tables, classifies, proposes 12 as on-thesis" |

**Medallion + the layers between:**

```
RAW BYTES                    BRONZE PROFILED               SILVER TYPED + ENRICHED            GOLD BUSINESS-READY
File / stream / API  →   row_count, col_count,    →   inferred types, joined to    →   KPI aggregates, charts,
url_private, hash         schema_hash, mime              other tables, classified         decision artifacts, reports
                         (emit_source_bronzed)          (emit_source_silvered)            (emit_kpi_proposed,
                                                                                          emit_data_product)
```

**Every layer writes to the ledger** with the canonical PEVR primitive (propose → execute → verify → resolve), giving us a hash-chained provenance trail for every byte. Replay the ledger to timestamp T → identical hashes (Karpathy-wiki compounding state).

**On-thesis criteria hit:**
- C1 unprompted action (worm proposes sources autonomously)
- C2 deterministic output (medallion cascade is a deterministic function of source bytes)
- C3 compounding state (lake grows over time, worm doesn't redo work)
- C6 auditable governance (every layer has a receipt)

**Demo beat:** "watch the medallion cascade fire as Bob drops the file. Bronze in 200ms, silver in 1.5s, gold KPI in 4s. Every step has a hash."

---

## Step 3 — BUILD CONCURRENTLY (KPIs in a tree + governance + process retrieval)

**Goal:** these three pillars grow **at the same time, from the same substrate** (the ledger). None of them is a separate phase or a separate subsystem.

### 3a. KPI tree

KPIs are a **graph** — nodes are metrics (Q3 net revenue, monthly retention, CAC payback), edges are derivation relationships (gross revenue = sum of plan revenue + expansion - churn). Tree grows from gold-layer aggregates upward into business-ready KPIs.

- New KPI proposed when (a) gold aggregate produced from a new source, (b) human asks a question that requires it, (c) autoresearch loop suggests it.
- Each KPI is a ledger entry — proposed, confirmed, connected to upstream sources, retired.
- Dashboard shows it as an interactive graph (React Flow). Clicking a node shows its lineage all the way down to bronze.

### 3b. Governance

Five entities, all materialized from the ledger:
- **Person** (id, role)
- **Domain** (sales, finance, product — each owned by a person)
- **Resource** (source, table, KPI, policy — each in a domain, classified)
- **Classification** (public / internal / confidential / pii / regulated)
- **Policy** (rule attached to a domain × classification × resource — implemented as code)

Every resource that the lake (Step 2) or KPI tree (3a) produces gets auto-classified, auto-domained, auto-owned. Humans confirm; worm proposes.

### 3c. Process retrieval (NEW)

The worm reads its own conversation lake (channel-adapter writes every message; the worm processes them through bronze → silver → gold for **conversations** as a first-class data source) and extracts:
- **Decisions** ("we decided to push the Q3 close to Friday") → `emit_decision_recorded`
- **Process maps** ("Q3 close flows: Bob exports → Alice reviews → Carol approves → posted") → `emit_process_map_proposed`
- **System maps** (org graph: who-asks-whom, what-channels-do-what) → `emit_system_map_node`
- **Recurring questions** ("Carol asked Q3 revenue 4 times this quarter") → `emit_recurring_question`

Process retrieval is the worm-eye view of the org. After 24 hours of observation, the dashboard shows: "here's how Q3 close actually flows through your team" — and where it breaks.

**On-thesis criteria hit by all three pillars:**
- C3 compounding state (all three grow over time)
- C6 auditable governance (every node, every classification, every decision is receipt-backed)
- C7 domain specialization (this isn't a generic ontology; it's specific to *your* business)

**Demo beat:** "every minute the worm has been in the room, the KPI tree got more nodes, governance picked up more resources, and the process map got tighter. None of this is human-prompted. The worm is doing the bookkeeping you'd never get around to."

---

## Step 4 — PRODUCE + CONVERSE

**Goal:** the worm **outputs**, not just observes. Two output modalities:

### 4a. Data products

Generated from the lake + KPI tree + governance + processes. Examples:
- **KPI dashboards** (rendered as the `/kpis` view live on the demo)
- **Process maps** (rendered as `/processes`)
- **Decision logs** (rendered as `/decisions`)
- **Lineage graphs** (every gold artifact has a clickable trail back to bronze bytes)
- **Recurring-question summaries** (with proposed automations)
- **Improvement candidates** (per-process suggestions from the autoresearch loop — Karpathy-style)

Each product is a ledger artifact: `emit_data_product_published`. Replayable, hash-stable, exportable to CSV / JSON / Markdown / PDF.

### 4b. Conversational interface

Two channels:
- **Text** (in Slack, on @-mention) — bot replies with a sourced answer + receipt
- **Voice** (NEW) — BaseWorm answers a phone call or joins a Slack Huddle. ElevenLabs Conversational AI ear/mouth, Kimi brain via custom-LLM webhook. Every turn writes to the ledger like a chat turn does.

The conversational interface is the **prompted depth** to Step 1's **unprompted surface**. The worm initiates work autonomously (Steps 2-3); humans direct it via conversation (Step 4).

**On-thesis criteria hit:**
- All 8. This is where institutional AI shows up.

**Demo beat:** "Carol calls the worm's number from the kitchen. 'What's our Q3 net revenue?' Worm: 'Q3 net revenue is $1.42M, up 12% from Q2. Source: stripe.invoices joined with snowflake.subscriptions, computed at 09:14 today, hash a8989ece. Want me to email Bob the breakdown?' That's institutional AI. That's the receipt."

---

## Step 5 — SELF-IMPROVE PER USER (Karpathy-style, role-aware)

**Goal:** every user gets their own continuously-sharpening analyst seat. The autoresearch loop is **not one global loop** — it's **one loop per role**, parameterized by what that user cares about.

### User + role structure

The governance model from Step 3b is extended with explicit **positions**:
- **Person** (id, name, email, role within the tenant: admin / member / observer)
- **Position** (NEW): CFO, CMO, data engineer, marketing lead, ops manager, customer success, founder, etc. Assigned at onboarding by the installer; editable later.
- **Installer**: implicitly admin; their position seeds the initial autoresearch focus.
- Each Position carries:
  - **Metric set** they care about (CFO: revenue, runway, CAC payback. Marketing lead: retention, channel mix, viral coefficient. Data engineer: pipeline latency, schema drift, query cost.)
  - **Question patterns** (what kinds of questions does this position ask? CFO: "What's our…?" "How much…?" Data engineer: "Why is…?" "When did this break?")
  - **Improvement candidates** they want surfaced (CFO: cost optimizations. Engineer: pipeline reliability.)

Position is a first-class entity in the ledger:
```
emit_person_registered { person_id, name, email, role }
emit_position_assigned { person_id, position, by_person, at }
emit_position_metric_added { position, metric_id, weight, by_person }
emit_position_question_pattern { position, pattern, frequency }
```

### Per-user autoresearch loop

For each person × position pair, the worm runs an autoresearch cycle. Loop body:
1. **Read the user's recent activity** (questions they asked, KPIs they viewed, decisions they participated in — all from the conversation lake + dashboard activity)
2. **Track their headline metrics** (defined by position; CFO sees revenue/runway, data engineer sees pipeline-latency-p95)
3. **Propose experiments** specific to this user:
   - "If we cache the Q3 net-revenue query for 5 minutes, your dashboard load latency drops 40%."
   - "Carol asked Q3 revenue 4 times this quarter; want me to send a daily snapshot to your DM?"
   - "The retention cohort definition Alice uses excludes promo signups; including them changes m3 by 8%."
4. **Run the experiment** (mocked execution + ledger write entries simulating the cycle):
   - `emit_experiment_proposed { for_person, headline_metric, proposed_change, expected_delta }`
   - `emit_experiment_run { experiment_id, started_at, finished_at }`
   - `emit_experiment_resolved { experiment_id, outcome: keep|discard, observed_delta, rationale }`
5. **Report to the user**: every win lands in their personal "research log" tab; every cumulative improvement updates their headline metric over time.

### Why this is institutional AI

A general LLM gives the same answer to everyone. WormBase gives **Carol's-CFO answer** to Carol — pre-computed, hash-receipt'd, with the metrics SHE cares about ticking up over time. The CFO and the data engineer share the same worm but get different value because the autoresearch is per-position.

This is also how the worm **scales**. Adding a new user is "create person + assign position." The autoresearch loop picks them up automatically. No human-in-the-loop config.

### Karpathy autoresearch alignment

Direct mapping to the autoresearch paper (CLAUDE.md anchor):
- **modify code** → modify [process / classifier rule / KPI cache / pipeline parameter / answer cadence]
- **train** → run [classification / process extraction / query / cache warm] on fresh data
- **evaluate metric** → check the user's headline metric (per their position)
- **keep-or-discard** → ledger entries; wins keep, losses discard
- **overnight run** → the loop runs continuously; the worm reports cumulative wins per user weekly

### Demo dashboard

New `/research` tab. Two views:
- **Per-tenant overview**: total experiments run, win rate, top movers across the user base.
- **Per-user view** (filtered to whoever is logged in): your headline metrics over time, your experiments, your wins, what the worm wants to try next (with "approve / reject" buttons).

**On-thesis criteria hit:**
- C5 metric-governed self-improvement (the canonical match)
- C3 compounding state (per-user research history accumulates)
- C7 domain specialization (this isn't autoresearch on language models; it's autoresearch on YOUR business on YOUR position)
- C8 unprompted (the loop runs without being asked; user just receives the wins)

**Demo beat:** "Carol logs in. Her dashboard shows: 'over the past week, the worm ran 23 experiments on metrics that matter to your CFO role. 8 wins. Q3 revenue forecast accuracy is up 4%. Cash runway projection is 12% tighter. Want to see the trail?' That's a personalized analyst seat."

---

## How this maps to the existing codebase + dispatched waves

| Step | Existing code | New work in flight |
|---|---|---|
| 1. Connect (any platform) | OpenClaw + channel-adapter (Path 3) + sim-harness | **W1.D** — tenant context, switcher, scoped queries; **W2.L** — onboarding wizard captures installer + position |
| 2. Grow the lake | Source-builder + 5 flows + DropAndProfileFlow | **W2.B** — medallion cascade + remote URI handlers + lake_discovery flow; **W2.H** — proactive source-from-conversation |
| 3a. KPI tree | KPI projection in ledger | **W2.C** — React Flow tree; live polling; click-to-lineage |
| 3b. Governance | 5 entities materialized as projections | **W2.C** — drag-and-drop, inline classification editing; **W2.L** — Position entity + per-resource ownership UI |
| 3c. Process retrieval | (new) | **W2.J** — process_extractor.py + /processes /decisions /system-map |
| 4a. Data products | Static fixture-driven dashboards | **W2.K** — autoresearch loop produces improvement candidates as data products; W3.F demo scenarios drive product output during the run |
| 4b. Conversational text | OpenClaw + Kimi (existing) | (no new work; already in production) |
| 4b. Conversational voice | (new) | **W2.E** — ElevenLabs + Kimi via custom-LLM webhook (per W1.A design doc) |
| 5. Self-improve per user | (new) | **W2.K** — per-user autoresearch loop parameterized by position; **W2.L** — user/position structure that K consumes; new `/research` tab |

---

## Multitenancy throughout

Every step is **company-scoped**. The same single binary serves N companies. Each company sees only their own ledger, lake, KPIs, processes, governance. The dashboard tenant switcher demos this in seconds: flip from baseworm → democorp → see a separate, sparser company come online with the same product surface.

---

## Time-to-aha target

- **5 minutes after install**: 1 connected chat platform + 5+ ingested chat events + 1 source proposal (drop or mention) + 1 governance domain ready
- **30 minutes**: bronze + silver + gold for one source; first KPI proposed; first decision extracted from conversation
- **24 hours**: full process map for one workflow; recurring questions identified; first autoresearch experiment run

The dashboard's onboarding panel tracks this explicitly (the **"aha gauge"**). Demo shows a fresh tenant hitting the 5-minute milestone live.

---

## What's out of scope for the Thursday demo

- Production-grade voice rate-limit handling (we use ElevenLabs trial credits)
- Discord / Teams / WhatsApp wiring (config-only, demonstrated by `@connect` but not exercised live)
- Real autoresearch loop running on real GPU experiments (the loop runs on org-metric experiments — process tweaks, classifier rules, KPI definitions — not model training)
- Federated multi-region deployment (single-region SaaS is shown)
- On-prem / VPC variant (mentioned in the pitch, not demoed)

These all stay in the architectural priors but are deliberately out of the demo's surface.

---

## Reference

This document is the canonical product story. Other docs derive from it:
- `docs/demo-runbook.md` — narrator script, fallback playbook (W3.G updates per Step mapping)
- `docs/superpowers/specs/2026-04-26-voice-agent-design.md` — Step 4b implementation plan
- `apps/sim-harness/scenarios/demo-c-plus-b.yml` — the live demo arc (W3.F updates per the 4 steps as 3 acts)
- App-level `README.md` files — each documents the contribution to its mapped step

When in doubt about scope: does this work map to one of the four steps? If not, it's out of scope.
