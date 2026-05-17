# Institutional Onboarding Proposal

This document is the architectural proposal that translates OpenClaw's
onboarding pattern into an institutional-scale shape WormBase can
implement. It synthesizes the OpenClaw pattern characterization with
the current-state seams surfaced by the customer-journey audit, and it
proposes a phased delivery path with explicit decisions called out.

For the OpenClaw pattern itself, see
[openclaw-integration-patterns.md](../case-studies/openclaw-integration-patterns.md).
For the current-state customer journey, see
[customer-journey.md](customer-journey.md).

---

## TL;DR

OpenClaw's onboarding pattern boils down to **five durable properties**.
WormBase already has two of them (capability declarations as data; per-
adapter status badges) and partially has a third. The gap to
"institutional OpenClaw" is **three net-new surfaces + one critical
fix**:

- **NEW:** unified `@onboard <object>` verb over the institutional
  ontology (connectors / channels / domains / persons / roles /
  policies / agents / subscriptions).
- **NEW:** multi-stakeholder approval state machine (legal / ops / IT
  consent branches; ledger-resident transitions).
- **NEW:** governance baseline before data (domain pack +
  classification defaults + policy templates pre-seeded; 90-second
  config sprint).
- **FIX:** `InstallCascadePanel` silent demo seam — 5 of 9 cascade
  steps wait for emitter names no producer writes.

Two large supporting fixes:

- **Tier 2 confirm callbacks are empty** — projection-read shells with
  no write-back at the tier surface.
- **2 of 5 source-build flows are not dispatcher-reachable** —
  `mentioned_in_conversation` and `kpi_gap_triggered` are factory-only;
  the chat-service dispatcher carries an unfinished comment.

A coherent institutional-onboarding UX needs all four (three new
surfaces + one fix) at minimum. The two supporting fixes are required
for honest production UX.

---

## 1. OpenClaw pattern → institutional analog

The five properties of OpenClaw's onboarding, mapped to institutional
analogs:

| # | OpenClaw property | Institutional analog | Status |
|---|---|---|---|
| 1 | **Unified verb** (`channels add` compiles to N auth flows) | `@onboard <object>` compiles to N flows across the ontology (connectors / channels / domains / persons / policies / agents) | Need new surface |
| 2 | **Status badges as data** (production/preview/coming_soon) per adapter | Capability + status badges per *everything* in the ontology, not just channels | Have it for connectors + adapters; missing for governance + agents |
| 3 | **Capability set per adapter** (`{ingest, send, dm, file_upload, voice}`) | Capability declarations per object kind: per connector ({discover, profile, sample, watch}); per channel ({ingest, send, file_upload, dm, voice}); per agent ({read, write, subscribe, execute}); per policy ({mask, redact, audit, deny}) | Have it for connectors + channels; missing for agents + policies |
| 4 | **`--probe` discipline** (status as a first-class verb that distinguishes works / degraded / failed) | `@status <object>` and `@logs <object>` as universal verbs across all onboarding-touchable objects | Have it for channels (OpenClaw native); missing for connectors + agents + governance |
| 5 | **Onboarding-deferred channel adds** (wizard doesn't auto-connect channels) | Wizard onboards governance + first source FIRST; channels can be deferred to post-aha | Have it inverted today — channels are Tier 0 + governance is Tier 2 |

**Three properties map cleanly.** Two are inverted or missing. The
first-wave deliverable closes these gaps surgically.

---

## 2. Five institutional-specific differences

Things an institutional-onboarding UX must model that OpenClaw alone
does not. Each is a net-new surface, not an extension of an OpenClaw
primitive.

1. **Org identity + multi-Person + PersonIdentity stitching.**
   OpenClaw is per-account; WormBase needs org-as-first-class with N
   people across N platform identities. WormBase already has this
   (Person + PersonIdentity + Install schemas).

2. **Multi-stakeholder approval state machine.** Legal / ops / IT may
   need to consent before data flows. Not built.

3. **Governance + classification baseline set BEFORE data flows.** PII
   auto-detect, per-domain classification defaults, policy templates.
   Partial (Tier 2 reads governance projections but doesn't write
   back).

4. **Source has nine substrate states** (proposed → confirmed →
   connected → profiled → classified → sampled → ingested → lineage-
   attached → quality-gated) vs OpenClaw's three-state channel.
   Partial — 4 of 9 wired today; classified/sampled/ingested/lineage-
   attached/quality-gated only partially via the L3 + L7 lake-side
   loops.

5. **Domain pack picker** with pre-seeded ontologies (SaaS /
   marketplace / fintech) + per-domain owner assignment. Partial —
   Tier 2 has a picker but read-only.

These are real institutional concerns; the proposal addresses them in
five phases.

---

## 3. Current-state assessment

| Area | State | Critical? |
|---|---|---|
| OAuth + KMS-wrapped tokens (Tier 0/1) | Real end-to-end; ~10 PEVR cycles per install; auto-provisioned local lake | — |
| `InstallCascadePanel` UI | **Silent demo seam** — 5 of 9 cells wait for emitter names with no producer; copy says "every checkmark is real" | YES |
| Tier 2 confirm callbacks | **Empty bodies** — read projections, never write back from tier surface | YES |
| Source-build flows 1+2+4 (drop / DM / form) | Wired in dispatcher | — |
| Source-build flows 3+5 (mention / KPI-gap) | **Factory-only**; chat-service carries unfinished comment | YES |
| OAuth connectors (Stripe / Salesforce / HubSpot / GSheets) | Credential-paste only; `oauth_unconfigured=1` redirect from callback | Med |
| Connector registry | 14 connectors. All scaffolded; production-readiness varies | — |
| Governance baseline | Tier 2 surface reads it; doesn't auto-seed | Med |
| Agent registration | Live | — |
| Subscriptions | Live | — |

The institutional-onboarding UX assumes a working Tier 0-3. Today
**Tier 0-1 is solid; Tier 2-3 is read-shells; the cascade panel has a
correctness bug.**

---

## 4. Proposed UX shape

### 4.1 The five-tier flow

Mirrors OpenClaw's deferred-connect discipline plus the OpenClaw-
pattern synthesis.

```
Tier 0: Landing + Org Creation              ── ≤30s
        - Org name + installer identity
        - Single chat-or-deferred decision
        - Status: WORKING TODAY
                            │
                            ▼
Tier 1: Install (chat OR data-first)        ── ≤30s
        - If chat: existing OpenClaw OAuth flow per platform
        - If data-first: skip chat; jump to Tier 2
        - Status: chat side WORKING; data-first NEW
                            │
                            ▼
Tier 2: Governance Baseline (90s)           ── ≤90s
        - Domain pack picker (SaaS / marketplace / fintech / generic)
          → seeds domains + classification defaults + policy templates
        - Co-admin invites (real PersonIdentity discovery via platform members)
        - Per-source classification defaults review
        - Stakeholder approval initiation (legal / ops / IT — async signoff)
        - Status: SURFACE EXISTS, write-back EMPTY
                            │
                            ▼
Tier 3: First Source + KPI                  ── ≤45s
        - Connector marketplace surface
        - Pick: dbt / Snowflake / Postgres / CSV upload / etc.
        - Profile + classify proposal → confirm
        - First KPI propose (auto-derived from sampled data)
        - Status: PARTIAL
                            │
                            ▼
Aha: First worm interaction                 ── ≤60s cumulative
        - Worm posts in connected channel (if chat was set up)
        - Bronze cascade visible
        - KPI proposed
        - Knowledge ramp first-moved
        - Status: end-to-end claim; needs cascade-panel fix to be honest
```

### 4.2 The verbs

Per the OpenClaw `@onboard <object>` synthesis, the dashboard exposes
these verbs across the entire onboarding flow (and post-onboarding for
adding new objects):

| Verb | Object | Surface today | Needs |
|---|---|---|---|
| `@onboard chat` | channel (Slack/WhatsApp/Discord/Teams) | OpenClaw native | — |
| `@onboard source` | connector instance | dashboard form + 2 wire-driven flows | NEW: unified surface |
| `@onboard domain` | domain pack | Tier 2 picker read-only | NEW: write-back |
| `@onboard person` | co-admin / member | Tier 2 surface | NEW: real identity discovery + invite emit |
| `@onboard policy` | governance policy | dashboard list view | NEW: pack-driven seed |
| `@onboard agent` | external agent | `/people/agents/new` live | — |
| `@onboard subscription` | event subscription | `/people/agents/[id]/subscriptions/new` live | — |

`@status <object>` and `@logs <object>` are the universal observability
verbs. Status renders a per-object health table; logs render the most
recent ledger entries.

### 4.3 CLI is implicit

The institutional onboarding flow targets the web UI for non-developer
admins. The CLI version of `@onboard chat` already exists via
OpenClaw's `channels add`. The CLI version of `@onboard source` and the
rest could ship via a thin Click wrapper over the worm-core write
endpoints; out-of-scope for the first-wave web UX deliverable, trivial
to add later.

---

## 5. Implementation phases

### Phase 0 — Correctness fixes (~2-3 hours)

Required before institutional onboarding can be honest.

- **F1: Fix `InstallCascadePanel` emitter-name mismatch.** Either
  change UI to match real emitter names, or add the five missing
  producer emitters. Four of the five missing emitters have a clear
  semantic home in existing code (just not yet wired).
- **F2: Wire Tier 2 confirm callbacks.** Empty bodies in
  `Tier2Client.tsx:83-86`. Should write back to worm-core via the
  existing PEVR pattern.
- **F3: Wire `mentioned_in_conversation` + `kpi_gap_triggered` flow
  dispatchers.** `service.py:283` is the canonical site. Each needs a
  semantic-interpretation trigger predicate.

### Phase 1 — Unified onboarding surface (~6-10 hours)

Net-new surfaces.

- **P1.1 `/onboard` landing route.** Single tab in the dashboard;
  replaces or wraps the scattered onboarding pages. Tabs for chat /
  source / domain / person / policy / agent / subscription.
- **P1.2 Tier 2 governance baseline write-back.** Domain pack picker
  writes `domain_pack_selected` (potentially new kind, or composite of
  existing `domain_proposed` + `policy_proposed` writes);
  classification defaults flow to per-source
  `classification_proposed`; stakeholder approvals as
  `stakeholder_approval_requested` + `_granted` (NEW kinds).
- **P1.3 Real co-admin invites.** PersonIdentity discovery via platform
  members; invite emit as `person_invited` ledger entry; accept-flow
  via emailed signed URL.
- **P1.4 `@status <object>` + `@logs <object>` views.** Per-object
  health + recent-entry surfaces (small components reused across
  object kinds).
- **P1.5 Capability badges everywhere.** Extend the `StrategyStatusBanner`
  pattern to every onboarding-touchable object (production / preview /
  coming_soon).

### Phase 2 — Stakeholder approval state machine (~3-5 hours)

- New ledger kinds: `stakeholder_approval_requested`,
  `stakeholder_approval_granted`, `stakeholder_approval_denied`.
- Projection: `projection_stakeholder_approvals`.
- Async notification flow (email / @notify in connected channel).
- Per-source gating: if any stakeholder approval is pending or denied,
  data ingestion blocked at the gate (which already exists in the
  governance package).

### Phase 3 — Domain pack seeding (~2-4 hours)

- Three pre-seeded packs: SaaS / marketplace / fintech / generic.
- Each pack = (domain list, classification defaults, policy templates).
- Tier 2 selection writes the full pack as a batch of ledger entries.
- Packs ship as YAML in the repo (declarative + audit-friendly).

### Phase 4 — Connector marketplace polish (~2 hours)

- The `/lake/connectors` marketplace shell already exists. Extend
  with:
  - Per-connector "Add" action that routes to the appropriate config
    form.
  - Status probes (real connection test + display).
  - Capability badges per connector (already present in the catalog
    data).

### Phase 5 — Carry-forward connector fixes (~3-4 hours each)

OAuth-style connectors that currently redirect to credential-paste —
wire real OAuth for Stripe / Salesforce / HubSpot / GSheets. Each is
its own task. Recommendation: ship one reference implementation
(Stripe) and add the rest incrementally.

### Sizing summary

| Phase | Effort |
|---|---|
| 0 — Correctness fixes | ~6-9 hours |
| 1 — Unified onboarding surface | ~6-10 hours |
| 2 — Stakeholder approval | ~3-5 hours |
| 3 — Domain pack seeding | ~2-4 hours |
| 4 — Connector marketplace polish | ~2 hours |
| 5 — OAuth connector wiring | ~3-4 hours each × N |

**Phase 0+1+3+4 ≈ 14-25 hours = one maintenance arc.** Phase 2 and 5
are additive future arcs.

---

## 6. Cumulative architectural delta

If Phase 0+1+3+4 ship:

- **Ledger kinds added:** `domain_pack_selected`, `person_invited`,
  possibly 2-3 more for governance write-back.
- **Projections added:** 0-1 new (governance baseline already
  projected; domain pack might reuse existing projections).
- **Reactivities added:** 0 (Phase 0+1+3+4 is wiring + surfaces, not
  new compounding loops).
- **MCP tools added:** maybe 2-3 (`onboard.source.create`,
  `onboard.domain.seed`, etc.).
- **Opt-in env knobs added:** 0-1 (`WORMBASE_ONBOARDING_V2_ENABLED` if
  default-OFF is preferred for the new surface; default-on is
  acceptable since it's net-additive UI).

If Phase 2 ships: +3 ledger kinds (`stakeholder_approval_*`) + 1
projection.

If Phase 5 ships: per-OAuth-provider config + real callback
implementation per provider.

---

## 7. Open decisions

Four scope questions worth surfacing for whoever picks up this
proposal:

### Q1 — Phase priority

Pick a starting point:

- (a) Phase 0 first (correctness fixes; ship the cascade panel honest
  before any new surfaces).
- (b) Phase 1 first (build the unified `@onboard` surface; tolerate
  the demo seams until Phase 0 follows).
- (c) Phase 0 + Phase 1 together (single wave; ~12-19 hours; cleaner
  narrative).

**Recommendation: (c).** Phase 0 fixes are a precondition for the
institutional-onboarding pitch being honest. Doing them together is
the right shape.

### Q2 — Stakeholder approval scope

The multi-stakeholder approval state machine is a real differentiator
vs OpenClaw, but it is also the largest net-new piece.

- (a) Include in first wave (Phase 2 inline; adds ~3-5 hours).
- (b) Defer to follow-up (ship without; first-wave is org-creation +
  sources; approval is a Phase 2 wave).

**Recommendation: (b).** First wave ships the surfaces; the approval
state machine is its own architectural ask with real ledger kinds, and
the gate logic should land separately.

### Q3 — Connector marketplace polish vs OAuth wiring

Phase 4 is cheap; Phase 5 is multiple medium-effort tasks.

- (a) Phase 4 only this wave (cheap, completes the UX).
- (b) Phase 4 + 1 reference OAuth implementation (Stripe is the
  cleanest; sets the pattern).
- (c) Phase 4 + all OAuth implementations (closes the OAuth-redirect
  debt entirely).

**Recommendation: (b).** Phase 4 + Stripe as the OAuth reference. The
other OAuth implementations become a follow-up wave with a clear
template.

### Q4 — CLI version

- (a) Web only this wave (CLI is implicit; trivial follow-up if anyone
  needs it).
- (b) Web + thin CLI wrapper.

**Recommendation: (a).** Web first. CLI is a 30-minute wrapper once
endpoints exist.

---

## 8. Recommended first wave

Phase 0 + Phase 1 + Phase 3 + Phase 4(a) — ~10-15 hours total.

This produces:

- Cascade UI honest (F1).
- Tier 2 write-back wired (F2).
- `mentioned_in_conversation` + `kpi_gap_triggered` flows reach the
  dispatcher (F3).
- Unified `/onboard` surface with `@onboard <object>` shape across the
  ontology.
- Capability badges + `@status` / `@logs` verbs everywhere.
- Tier 2 governance baseline write-back (writes real domain +
  classification + policy entries from the pack picker).
- Domain pack seeding (3 packs: SaaS / marketplace / fintech).
- `/lake/connectors` polish (action wiring + capability display).

### Sub-wave decomposition

- **Sub-wave A:** Correctness fixes (F1 + F2 + F3) — wires existing
  pieces; minimal new code.
- **Sub-wave B:** Unified `/onboard` route + verbs + capability
  badges.
- **Sub-wave C:** Domain pack YAML + seeding logic + Tier 2 write-
  back.
- **Sub-wave D:** Connector marketplace polish + per-connector status
  probes.
- **Sub-wave E:** Close-out + operator runbook.

---

## What this proposal does not implement

Explicit deferrals, all with clear shapes for future waves:

- Phase 2 stakeholder approval state machine.
- Real OAuth for Salesforce / HubSpot / GSheets (Stripe is the
  reference implementation).
- The CLI wrapper.

---

## Cross-references

- [openclaw-integration-patterns.md](../case-studies/openclaw-integration-patterns.md)
  — the OpenClaw pattern characterization this proposal builds on.
- [customer-journey.md](customer-journey.md) — the current-state
  customer journey audit whose Seams 1-4 the institutional onboarding
  closes (specifically Seam 2 and the source-build flow gaps).
- [semantic-layer-best-practices.md](../synthesis/semantic-layer-best-practices.md)
  — the agent-gateway and compounding-loop substrate the onboarding
  flow feeds.
