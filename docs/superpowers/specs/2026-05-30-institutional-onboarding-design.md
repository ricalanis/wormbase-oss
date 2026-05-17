# Institutional Onboarding — Design Spec

**Status:** DESIGN — user-approved 2026-05-30 ("recommendations approved, write spec + plan + dispatch")
**Predecessor:** `docs/superpowers/notes/2026-05-30-institutional-onboarding-proposal.md` (`0c10358`)
**Authority:** binding for the first wave (Phase 0 + Phase 1 + Phase 3 + Phase 4(a))

---

## 1. Wave scope

Approved scope per Q1-Q4 recommendations:
- **Q1 (c):** Phase 0 + Phase 1 together
- **Q2 (b):** Phase 2 stakeholder approval **deferred** to future wave
- **Q3 (b):** Phase 4 polish + **Stripe OAuth as reference impl**
- **Q4 (a):** Web only this wave; CLI deferred

**In scope:**
- F1 InstallCascadePanel emitter-name correctness fix
- F2 Tier 2 confirm callbacks wired (write-back via worm-core PEVR)
- F3 `mentioned_in_conversation` + `kpi_gap_triggered` flow dispatchers wired
- P1 Unified `/onboard` route + `@onboard <object>` verbs + `@status`/`@logs` views
- P3 Domain pack YAML (4 packs) + seed logic + Tier 2 picker write-back
- P4 `/lake/connectors` per-connector "Add" wiring + real status probes
- P5(Stripe) — Stripe OAuth callback replaces the credential-paste redirect; sets the reference pattern for Salesforce/HubSpot/GSheets in future waves

**Out of scope (deferred):**
- Stakeholder approval state machine (Phase 2) — separate wave; new ledger kinds + projection + gate
- OAuth for Salesforce / HubSpot / GSheets — Stripe is the reference impl; other 3 follow the same template
- CLI version — 30-min wrapper after web ships
- L7 quality-checks implementation — `ad327a0` spec + plan staged; resume after this wave

---

## 2. OpenClaw → institutional mapping (locked)

| OpenClaw property | Institutional analog | This wave |
|---|---|---|
| Unified verb (`channels add`) | `@onboard <object>` over institutional ontology | Sub-wave B builds the surface |
| Capability badges as data | Capability + status everywhere | Sub-wave B reuses L3's `StrategyStatusBanner` pattern |
| Capability set per adapter | Capability declarations per object kind | Sub-wave B renders only valid actions per capability |
| `--probe` discipline | `@status <object>` + `@logs <object>` universal verbs | Sub-wave B + D wire probes |
| Onboarding-deferred channel adds | "core first, channels later" 5-tier flow | Sub-wave B reorders tiers in the unified `/onboard` route |

---

## 3. New entry kinds (minimal — additive Rule 2)

| Kind | Purpose | Sub-wave |
|---|---|---|
| `domain_pack_selected` | Tier 2 records which pack the installer picked; fan-out to N `domain_proposed` + N `classification_proposed` + N `policy_proposed` entries follows | C |
| `person_invited` | Real co-admin invite emit (today's Tier 2 has stub) | A or C — pick during impl |

KIND_REGISTRY: 109 → **111** (+2). 9-kind headroom under 120 ceiling.

If F1 cascade correctness requires new emitter kinds, may add 1-3 more (cap at 114). Investigate at sub-wave A; document in the close-out.

---

## 4. New surfaces

### 4.1 Unified `/onboard` route (Sub-wave B)

Replaces the scattered onboarding pages today. Tab structure:

```
/onboard
├── /chat       — connector marketplace for channel adapters (reuses /lake/connectors connector-row shape, scoped to channel kinds)
├── /source     — data-source marketplace (reuses /lake/connectors)
├── /domain     — domain pack picker + per-domain owner assignment (Sub-wave C wires writes)
├── /person     — co-admin invites + PersonIdentity discovery
├── /policy     — policy list (read-only this wave; pack-seeded by Sub-wave C)
├── /agent      — link to existing /people/agents/new (no new surface; just navigation)
└── /subscription — link to existing /people/agents/[id]/subscriptions/new (no new surface)
```

Each tab renders the same shape: capability + status badges per object kind + a "Add" / "Invite" / "Pick" verb.

### 4.2 `@status <object>` + `@logs <object>` views (Sub-wave B)

Per-object detail surfaces. Render:
- Status: works / degraded / failed (with the underlying probe result + recovery hint)
- Logs: most recent ledger entries for the object (raw-ledger scan; same shape as v2.A subscription audit panel)

Object types covered: connector instance, channel install, domain, person, policy, agent.

### 4.3 Tier 2 governance baseline (Sub-wave C write-back)

Today `Tier2Client.tsx:83-86` has empty confirm callbacks. Wave wires them to:
- POST `/api/v1/write_actions/domain_pack_selected/{pack_id}` — emits the new ledger entry + fan-out
- POST `/api/v1/write_actions/person_invited/{platform_id}` — emits per-invitee

---

## 5. Domain pack shape (Sub-wave C)

YAML in `apps/worm-core/src/wormbase_core/onboarding/packs/`:

```yaml
# generic.yaml
pack_id: generic
display_name: "Generic Org"
description: "Minimal pack for orgs without a clear vertical match."

domains:
  - id: general
    name: General
    default_classification: internal
    owner_role: tenancy.admin

policies:
  - id: retention_default
    applies_to_domains: [general]
    rule: "data_retention_days: 365"

classification_defaults:
  - pattern: "*_pii"
    classification: pii
  - pattern: "email"
    classification: pii
```

4 packs: `generic` / `saas` / `marketplace` / `fintech`. Each pack is a declarative bundle. Selection emits `domain_pack_selected` + the fan-out ledger entries in a single PEVR batch.

---

## 6. F1 InstallCascadePanel correctness fix (Sub-wave A)

Research 1 found 5 of 9 cells wait for emitter names no producer writes:
- `emit_default_lake_provisioned`
- `emit_lake_bronze_ingested`
- `emit_lake_silver_promoted`
- `emit_lake_gold_published`
- `emit_autoresearch_armed`

Real producers emit `emit_source_proposed/confirmed/connected/profiled` + `emit_source_bronzed/silvered/golded`. Investigation at Sub-wave A picks one of:
- (a) **Rename UI cells** to match real emitter names (preferred — zero new kinds)
- (b) **Add 5 new emitter kinds** that fire from the existing producer code (cleaner semantic but +5 kinds — 109 → 114)

Subagent picks during impl; commit message documents the choice. **Recommendation: (a)** — the existing emitters are the truth-of-record; the UI cells should match them.

---

## 7. F3 dispatcher hooks (Sub-wave A)

`service.py:283` carries `# mentioned_in_conversation needs a SemanticInterpretation —` (unfinished). Two flows are factory-only today:

- **`mentioned_in_conversation`**: needs a semantic-interpretation trigger predicate. Read `chat_received` entries; classify via existing semantic-trigger machinery (the chat-presence package); dispatch to `MentionedInConversationFlow.on_mention(...)` when a data reference is detected.
- **`kpi_gap_triggered`**: read `kpi_proposed` / `kpi_gap_*` entries; dispatch to `KpiGapTriggeredFlow.on_gap(...)` when a gap is observed.

Both need test coverage. The semantic-interpretation piece for `mentioned_in_conversation` may be substantial; if it's >M effort, Sub-wave A ships a stub trigger predicate (matches a literal `data:` prefix in chat) + documents the full semantic-interpretation as a Phase 2 carry-forward.

---

## 8. P5(Stripe) OAuth reference impl (Sub-wave D)

Today `connect/[connector]/callback/route.ts:27-40` returns 303 to credentials form with `oauth_unconfigured=1`. Sub-wave D replaces this for Stripe specifically:

- Stripe OAuth Connect flow (`https://connect.stripe.com/oauth/authorize`)
- Callback handler exchanges code for tokens
- Token storage via existing `CredentialBroker` (Vault if configured; env otherwise)
- Connection state recorded via existing `source_connected` ledger entry

Stripe is the cleanest OAuth target: well-documented, free dev keys, no domain verification required.

Other 3 connectors (Salesforce, HubSpot, GSheets) follow the same template in future waves; the Stripe wire is the reference.

---

## 9. Env knobs

Most likely **none** — onboarding is net-additive UI/UX. The new `/onboard` route is always-visible (it's the consolidation of scattered pages, not a new feature flag).

If F3 ships a stub semantic-interpretation predicate, gate via `WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED=true` (default OFF until production-ready predicate lands).

If Stripe OAuth uses env-resident keys (`STRIPE_OAUTH_CLIENT_ID` + `STRIPE_OAUTH_CLIENT_SECRET`): document as required-for-feature, not opt-in.

---

## 10. Tests

| Sub-wave | Layer | Expected tests |
|---|---|---|
| A | F1 cascade-cell wiring + F2 write-back + F3 dispatcher | ~12-18 |
| B | `/onboard` route + per-tab + capability badges + status/logs views | ~15-22 |
| C | Domain pack YAML loader + seed logic + Tier 2 write-back | ~8-12 |
| D | Connector marketplace polish + status probes + Stripe OAuth flow | ~10-15 |

Aggregate ~45-67 new tests.

---

## 11. Status: DESIGN APPROVED

Implementation plan at `docs/superpowers/plans/2026-05-30-institutional-onboarding-impl.md`.
