# Production Dashboard + Multi-Channel Identity — PRD

> **Status:** authoritative product spec. Supersedes `2026-04-22-prd.md` §3 (dashboard) and §5 (identity). Aligned with `2026-04-26-wormbase-product-arc.md` (canonical 5-step arc).
>
> **Author:** Ricardo Alanis (CEO) + Claude (architect, hackathon).
>
> **Demo:** Thursday 2026-04-30, a16z institutional-AI track.

---

## 0. CEO framing

WormBase is a **B2B institutional-AI platform**, not a hackathon prototype. What ships Thursday is what we ship to the first paying pilot Monday. Implications:

- Every feature on the dashboard has a **primary user role** and a **daily or weekly use**.
- Every abstraction (sources, channels, identity, roles) is **real and pluggable**, not stubbed.
- Every feature reads ledger truth. **No demo-only seams in the repo.**
- Onboarding is **60 seconds installer-to-aha**, because the alternative is a 6-week pilot with a sales engineer and we can't afford that.
- The product surfaces **all three pricing primitives** of the institutional-AI thesis: per-seat, per-source-connector, per-conversation-volume.

Five durable bets:

1. **Source abstraction** — a `Connector` interface, day-one connectors covering the SaaS / data-warehouse / file / stream surface, room for plugins.
2. **Channel abstraction** — a `ChannelAdapter` interface; Slack day one, Discord/Teams stub-but-real day one, others as plugins.
3. **Identity** — `Person` is canonical and platform-agnostic; `PersonIdentity` is multi-platform-native; `Install` is the OAuth grant + installer link.
4. **Roles** — three independent role facets (tenancy / domain / resource), composable, audit-trailed via the ledger.
5. **Dashboard is the product surface** — production-level, role-aware, ledger-truth-only, multi-tenant from the first commit.

Anything that does not serve those five bets is out of scope for Thursday.

---

## 1. The principle (durable, supersedes prior demo-mode reasoning)

```
Real users (and LLM-driven personas) drive real channel platforms.
Real channel platforms emit wire events to the channel-adapter.
The channel-adapter writes ledger entries (the only writer of flow-driven entries).
The dashboard reads ledger projections.
```

The dashboard never knows whether the actor was a human, an LLM-as-persona, or a recorded fixture replayed through the wire. Only that the ledger says X happened.

**No flow-bypass shortcuts in the repo.** If a flow doesn't fire end-to-end live, the wire is the bug; fix the wire. The only acceptable determinism backstop is **wire-replay**: a tool that loads recorded JSONL events and feeds them through `channel-adapter` in replay mode. Same code path as production, deterministic input.

`wormbase-worm-core simulate-flows` (committed in `b7356ab`) is **deleted** as part of this PRD. It was a flow-bypass, not a wire tool, and violated this principle.

---

## 2. Source abstraction

### 2.1. The `Connector` contract

Every data source — internal or external, push or pull, file or stream — implements a single Connector interface:

```python
class Connector(Protocol):
    """A connector to a data source. Pluggable. New connectors register
    themselves; no core changes required."""

    kind: str                          # "stripe" | "snowflake" | "csv" | ...
    capability: set[Capability]        # {discover, profile, sample, watch}
    classification_hints: list[Hint]   # PII patterns, regulated-data signals

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle: ...
    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]: ...
    async def profile(self, handle: AuthHandle, resource_id: ResourceId) -> Profile: ...
    async def sample(self, handle: AuthHandle, resource_id: ResourceId, n: int) -> bytes: ...
    async def watch(self, handle: AuthHandle, resource_id: ResourceId) -> AsyncIterator[Change]: ...
```

A Connector implementation is a class + a JSON-schema config + a registration. No core changes ever required to add one. The Connector contract is **stable across all four medallion layers** — discover feeds source proposals, profile feeds bronze, sample feeds silver enrichment, watch feeds gold reactivity.

### 2.2. Connector registry

```
packages/connectors/
├── base.py              # Connector protocol + types
├── registry.py          # name -> Connector lookup
├── csv_local.py         # files dropped in chat
├── postgres.py          # generic Postgres
├── snowflake.py         # SaaS warehouse
├── bigquery.py          # SaaS warehouse
├── s3_csv.py            # S3 buckets of CSV
├── stripe.py            # Stripe API
├── salesforce.py        # CRM
├── hubspot.py           # CRM
├── gsheets.py           # Google Sheets
└── http_csv.py          # generic URL → CSV
```

Day-one ships **all eleven** connectors above. Each is a 100-300 LOC adapter, mostly auth + paging + schema discovery. Each ships with one integration test (against a recorded fixture) and one connection test (against the live service, gated behind a CI secret).

### 2.3. Source-building flows are connector-agnostic

The six source-building flows (drop_and_profile, credential_in_dm, mentioned_in_conversation, dashboard_form, kpi_gap_triggered, lake_discovery) all funnel into the same `propose → confirm → connect → profile → cascade` ledger sequence. The Connector handles the per-source specifics; the flows handle the per-trigger specifics. Adding a new connector adds zero flow code.

### 2.4. On-thesis criteria

C2 (deterministic output — same source bytes always yield identical bronze/silver/gold), C3 (compounding state — connector list grows; lake grows), C7 (domain specialization — connectors carry domain hints).

---

## 3. Channel abstraction

### 3.1. The `ChannelAdapter` contract

```python
class ChannelAdapter(Protocol):
    platform: Platform              # "slack" | "discord" | "teams" | ...
    capability: set[ChannelCap]     # {ingest, send, file_upload, dm, voice}

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle: ...
    async def install(self, handle: AuthHandle) -> InstallRecord: ...
    async def listen(self, handle: AuthHandle) -> AsyncIterator[InfraEvent]: ...
    async def send(self, handle: AuthHandle, channel: ChannelRef, msg: OutMessage) -> MessageRef: ...
    async def list_workspace_members(self, handle: AuthHandle) -> list[PlatformMember]: ...
```

Wire events from every adapter normalize to a single `InfraEvent` shape:

```python
InfraEvent {
  source: "channel_message" | "file_drop" | "dm" | "reaction" | "edit" | ...
  platform: "slack" | "discord" | "teams" | ...
  platform_channel_id: str          # raw native id
  channel_id: UUID                  # WormBase-internal stable id
  platform_user_id: str             # raw native id
  person_id: UUID | None            # WormBase-internal Person, resolved if known
  message_id: str
  ts: datetime
  text: str | None
  payload: dict
  company_id: UUID
}
```

**The dashboard never sees `platform_*` fields except in /channels and /people merge surfaces.** Everything else reasons about `channel_id` and `person_id`.

### 3.2. Day-one adapters

- **`slack`** — full ingest, send, file_upload, dm. Production-grade.
- **`discord`** — stub-but-real: real bot account, real install flow, real listen loop. Send + file_upload may be skeletal but the wire-event normalization is complete. Proves the abstraction.
- **`teams`** — stub-but-real, same shape as Discord.

This is the demonstration that "WormBase is not a Slack add-on." The CEO answer to "do you support Teams?" is "yes, here's the connect button, and here's the same dashboard rendering Teams-sourced ledger entries."

### 3.3. On-thesis criteria

C7 (domain specialization — chat-as-substrate, not a general bot), C8 (unprompted surface — every adapter starts listening on install).

---

## 4. Identity model

### 4.1. `Person`

The canonical identity of a real human (or service account) in a tenant.

```python
Person {
  id: UUID
  tenant_id: UUID
  name: str
  email: str | None              # SSO-resolvable when present
  position: str                  # "CFO" | "CMO" | "Data Engineer" | ...
  status: "active" | "invited" | "proposed" | "archived"
  created_at: datetime
  proposed_by: UUID | None       # the worm if auto-discovered
  confirmed_by: UUID | None      # an admin Person
}
```

A Person exists at the tenancy layer. Persons are not bound to channel platforms.

### 4.2. `PersonIdentity`

```python
PersonIdentity {
  id: UUID
  person_id: UUID                # FK
  platform: Platform             # "slack" | "discord" | ...
  platform_user_id: str          # raw native id
  display_name: str
  email_at_platform: str | None
  avatar_url: str | None
  added_at: datetime
}
```

One `Person` may have many `PersonIdentity` rows — `@bob` on Slack, `bob#1234` on Discord, `bob@company.com` on Teams = one Bob.

Identity merge: when the worm proposes a Person and the email matches an existing Person, an admin can confirm a merge — the new `PersonIdentity` row attaches to the existing `person_id`, not creating a duplicate.

Identity split: if a Person turns out to be two people sharing an email (rare, but support staff often do this), an admin can split: the `PersonIdentity` rows are repartitioned across two `Person` rows.

Both merge and split are ledger entries with audit trail.

### 4.3. `Install`

```python
Install {
  id: UUID
  tenant_id: UUID
  platform: Platform
  installer_person_id: UUID      # the human who clicked @connect
  oauth_grant: encrypted_blob    # KMS-wrapped OAuth payload
  installed_at: datetime
  status: "active" | "revoked"
  scopes: list[str]
  bot_user_id: str               # platform-native bot id
}
```

One `Install` per `(tenant_id, platform)`. The installer is the OAuth grantor and inherits the bootstrap admin grant.

### 4.4. Auto-discovery

When the channel-adapter sees a `platform_user_id` it doesn't know:

1. **Wire event** — channel-adapter writes `emit_chat_received` (or `emit_file_received`) carrying the unknown `platform_user_id`.
2. **Discovery loop** — a periodic worker scans for unknown ids, queries the platform's workspace member API for `email + display_name`.
3. **Match attempt** — does a Person with that email already exist? If yes, propose `emit_identity_link_proposed` (link a new PersonIdentity to an existing Person). If no, propose `emit_person_proposed` (create a new Person + PersonIdentity).
4. **Admin confirmation** — `/people` shows pending proposals; one-click batch-confirm.
5. **Once confirmed** — all subsequent wire events from that `platform_user_id` carry the resolved `person_id`.

This is **agentic team-building** (parallel to agentic source-building). The worm builds the team it works for.

### 4.5. On-thesis criteria

C1 (unprompted — worm proposes Persons), C3 (compounding — team graph grows), C6 (auditable — every Person + identity + role-grant has a receipt).

---

## 5. Roles (three independent facets)

### 5.1. Tenancy role

```python
TenancyRole = "installer" | "admin" | "member" | "observer"
```

- **installer** — the OAuth grantor. One per (tenant, platform). Auto-admin.
- **admin** — full mutation rights on tenant config (domains, policies, classification defaults, role grants, install management). Multiple per tenant. Granted by another admin.
- **member** — default for confirmed Persons. Can be assigned domain ownership and resource maintenance. Can converse with the worm.
- **observer** — read-only across the entire tenant ledger. For auditors, board members, compliance.

Ledger entry: `emit_role_assigned {person_id, role, granted_by, ts}`. Revocation is `emit_role_revoked {person_id, role, revoked_by, ts}`.

### 5.2. Domain role

```python
DomainRole = "owner" | "contributor"
```

- **owner** — answers to data quality, governance, and on-call for that functional area. Confirms classification defaults, signs off on KPI definitions, gets pinged when the worm has a question.
- **contributor** — can edit domain artifacts (KPIs, processes, sources within the domain) without owning them.

Ledger entry: `emit_domain_role_assigned {person_id, domain_id, role, granted_by, ts}`. Multiple owners per domain are allowed; one is conventional.

### 5.3. Resource role

```python
ResourceRole = "maintainer" | "contributor"
```

- **maintainer** — owns a specific source / table / mart / KPI / policy. On the hook when it breaks.
- **contributor** — can edit but is not the on-call.

Ledger entry: `emit_resource_role_assigned {person_id, resource_id, resource_type, role, granted_by, ts}`.

### 5.4. Composability

A Person holds N grants across all three facets. Carol the CFO can simultaneously be:
- `tenancy.admin` (she helps run the tenant)
- `domain.owner` of `finance` (she owns the financial KPI tree)
- `domain.contributor` to `revenue` (she edits but doesn't own)
- `resource.maintainer` of `kpi.q3_net_revenue`
- `resource.contributor` to `source.stripe_payouts`

Five independent ledger grants, queryable as a flat join. The /people surface renders the Person's full role surface.

### 5.5. Defaults

- The installer auto-grants themselves `tenancy.admin` and (during Tier 2) `domain.owner` of every domain in the picked pack.
- A confirmed Person defaults to `tenancy.member`. Admins promote / demote.
- The worm proposes `resource.maintainer` grants based on chatter (whoever drops a file or pastes credentials is the proposed maintainer).
- An admin confirms or reassigns proposals.

### 5.6. On-thesis criteria

C6 (auditable governance — every grant is a receipt), C7 (domain specialization — three independent role facets, not one flat ACL).

---

## 6. Lifecycle (the first 60 seconds)

### 6.1. Tier 0 — Landing (`/`)

A signed-out marketing surface that is also the entry to the install flow:

- "Connect WormBase to your Slack / Discord / Teams" (one button per supported platform)
- "Or paste your work email and we'll start without a channel" (email-only path; channel can be connected later)

No dashboard chrome until Tier 1 completes.

### 6.2. Tier 1 — Installer auth (≤ 30s)

1. Click "Connect to Slack" (or Discord/Teams).
2. Platform OAuth redirect. Installer grants the WormBase bot scopes.
3. On callback:
   - Tenant is auto-provisioned (UUIDv5 of installer's email-domain) **or** existing tenant is detected (if installer's email domain is already a tenant — single-tenant-per-email-domain default; admins can override).
   - `Install` row written, `oauth_grant` KMS-wrapped.
   - `Person` row created for the installer (name + email + avatar from platform).
   - `emit_role_assigned {person_id: installer, role: installer}` and `... {role: admin}` written.
4. Installer lands on `/onboarding/tier2`.

### 6.3. Tier 2 — Domain pack + co-admin invites (≤ 20s)

A single screen:

- Domain pack picker (saas / marketplace / fintech / custom). Picking a pack writes `emit_domain_registered` for each pack-default domain (sales, product, finance, ops, ...) with the installer as owner.
- "Invite co-admins" — three input slots (email or `@username` from the connected platform). Each invite writes `emit_person_proposed` + `emit_role_assigned {role: admin}`. Invitees get an SSO email link.
- Classification defaults — pre-filled from the pack; "next" confirms.
- "Open the worm to all channels" toggle (on by default for member-by-member workspaces, off for large workspaces).

### 6.4. Tier 3 — First source + first KPI (≤ 10s)

Two prompts side-by-side:

- "Drop a file in your worm channel **or** click here to add a source" — links to `/sources/new` with the connector picker (CSV, Postgres, Snowflake, Stripe, ...). Whichever path the installer picks, the dashboard streams the bronze/silver/gold cascade in real time.
- "What's the first KPI you want the worm to track?" — free-text. The worm parses, proposes a KPI tree node, and starts watching for source-data that satisfies it.

### 6.5. Aha-moment SLA

Within **60 seconds** of installer hitting the Slack/Discord install button:

- A real `Install` row exists.
- A real `Person` (installer) exists, role-graded.
- A real `Source` is connected and has bronze emitted.
- A real `KPI` is proposed.
- The worm has posted **once** in the channel introducing itself.
- The dashboard `/dashboard` ramp gauges have first-moved.

If any of these miss the SLA, the install is failing. Surfaced via a yellow banner with diagnostic.

### 6.6. Days 1-7 — auto-team-discovery

- Worm watches chatter. Every new `platform_user_id` triggers `emit_person_proposed`.
- After 7 days (or 50 unique users, whichever first), `/people` shows pending proposals; admin batch-confirms.
- Each newly-confirmed Person gets a personalized welcome DM ("Hi Bob — I've been listening for a few days. Here's what I think you do; tell me your role.").
- Position assignment (CFO, Data Eng, etc.) auto-proposes from chatter signal; admin confirms.
- Once a Person has a position, the autoresearch loop starts firing for them — first experiments visible in `/research` within 24h.

### 6.7. On-thesis criteria

C1 (unprompted — worm proposes Persons + sources), C2 (deterministic — install flow is reproducible), C3 (compounding — team + lake + KPI tree all grow), C8 (unprompted surface — worm posts the welcome DMs).

---

## 7. Dashboard surface (production rewrite)

### 7.1. Role × tab utility matrix

| Role | Daily surfaces | Weekly surfaces |
|---|---|---|
| Installer (first day) | /onboarding, /channels, /people | /policies, /domains |
| Admin | /people, /domains, /policies, /channels, /data-products | /trace, /notebooks |
| CFO / Finance | /kpis, /data-products, /research | /decisions, /processes, /notebooks |
| CMO / Marketing | /kpis, /data-products, /research | /decisions, /notebooks |
| Data Engineer | /sources, /notebooks, /trace | /system-map, /processes, /research |
| Operations / COO | /processes, /system-map, /decisions | /kpis, /data-products |
| Member (default) | /dashboard, /data-products, /research | /activity, /notebooks |
| Observer / Auditor | /trace, /data-products, /policies | /domains, /system-map, /decisions, /notebooks |

**Every role has at least three daily-useful surfaces.** This is the "complete demo" criterion. **`/data-products` and `/notebooks` (§16) are now surfaced for every role** — they are the auditability + reproducibility lens that connects "what was decided" to "what artifact informed it."

### 7.2. `/people` — the team management surface

Production-grade Person + identity + role surface.

**Sections:**
- **Roster** — table of all Persons in the tenant. Columns: name, position, tenancy role, domain count, resource count, status. Sortable.
- **Pending proposals** — Persons the worm has auto-discovered but admin hasn't confirmed. Batch confirm / merge / reject.
- **Person detail** (drill-in) — per-Person card: name, email, position, identities (one row per platform), role grants (three sections: tenancy / domain / resource), audit log of grant changes (from ledger).
- **Invite flow** — modal with email-or-platform-handle input; sends SSO link or platform DM.
- **Identity merge / split** — admin tool. Choose two Persons → merge into one (the worm warns if positions or domains conflict). Or choose one Person → split into two by selecting which identities go where.

**Actions write to ledger:** `emit_person_proposed`, `emit_person_confirmed`, `emit_person_archived`, `emit_role_assigned`, `emit_role_revoked`, `emit_domain_role_assigned`, `emit_resource_role_assigned`, `emit_identity_linked`, `emit_identity_unlinked`.

### 7.3. `/channels` — promoted from /settings

Per-platform install management.

**Sections:**
- **Connected platforms** — one card per `Install`. Shows platform, installer, install time, status, granted scopes, bot user.
- **Channel roster** — per platform, list of channels the worm is in. Per-channel toggles: lurk-only / responsive / proactive. Per-channel mute (e.g. for HR-confidential channels).
- **Connect another platform** — buttons for every supported `ChannelAdapter`.
- **Revoke install** — confirmable destructive action; writes `emit_install_revoked`.

### 7.4. `/sources` — production rewrite

Adds maintainer + classification + connector fields to existing surface.

**Per-source row:**
- Name, kind (connector type), URI (or remote ref), bronze/silver/gold timestamps + hashes
- Maintainer (Person, drillthrough)
- Owner domain (drillthrough)
- Classification (public / internal / confidential / pii / regulated; color-coded)
- "Reprofile" button (writes `emit_source_reprofile_requested`)
- "Cascade" button (re-runs medallion; admin-only)

**New: `/sources/new`** — connector picker page. Lists every registered Connector with its capability badges. Picking one opens a config form generated from the connector's JSON schema.

### 7.5. `/domains` — production rewrite

Per-domain card grid with owner + contributor + resource roster.

**Per-domain card:**
- Domain name + classification default
- Owner (Person, drillthrough; can be reassigned via drag-and-drop from /people)
- Contributors (chip list)
- Resources owned by the domain (sources, KPIs, processes — count badges)
- Recent activity (ledger entries scoped to this domain)

### 7.6. `/policies` — production rewrite

Policy table with applies-to scoping.

**Per-policy row:**
- Name, rule-as-code summary, applies-to (domain / classification / resource)
- Maintainer (Person)
- Last fired (timestamp + count)
- Effect (block / mask / log / allow)
- "Test against ledger" — picks a sample of recent entries and shows what the policy would have decided.

### 7.7. `/onboarding` — production wizard

Tier 1 + Tier 2 + Tier 3 as the production install flow. Replaces the demo-only onboarding pages. SSR-rendered, real ledger writes, no fixture data.

### 7.8. `/kpis`, `/decisions`, `/processes`, `/system-map`, `/research`, `/activity`, `/trace`

Existing surfaces — already wired to ledger projections. PRD-level changes:

- All carry the same `Tenant chip + Person chip + role badge` header (see 7.10).
- All filter by current Person's `domain.contributor`-or-better grants (members see what they have access to; observers see everything).
- All add a "share view" button that produces a deep-link URL that another Person can open and see the same view, scoped to their own permissions.

### 7.9. Tenant switcher header chip

Top-right header, every page:

```
[ baseworm ▾ ] [ Carol Reyes — admin ]
```

- Tenant switcher (existing) — replaces all data on switch.
- Person chip — shows current Person's name + tenancy role + position. Clickable → `/people/{me}`.
- Logout / sign-in.

### 7.10. Role-aware navigation chrome

The left-nav adapts to the current Person's role:

- **Installer (first-day)** — Onboarding tab pinned at top with progress badge.
- **Admin** — full nav: People, Domains, Policies, Channels, Sources, KPIs, Processes, System Map, Decisions, Research, Trace, Activity.
- **Member** — Dashboard, KPIs, Research, Activity, Decisions, Processes (read-only).
- **Observer** — read-only nav, all tabs visible, no action buttons.

Implemented as a single `useNavForRole(person)` hook that maps role facets to nav items.

### 7.11. On-thesis criteria

C2 (deterministic — same role + same ledger always renders the same view), C6 (auditable — every action writes a receipt), C7 (domain specialization — role-aware nav, not a one-size-fits-all dashboard).

---

## 8. Sim reframe (from flow-bypass to wire-driver)

### 8.1. Sim-harness drives real channel platforms

- Persona accounts are real platform users (Slack workspace bot tokens, one per persona).
- Every persona's say(...) becomes a real `chat.postMessage`.
- Every persona's drop(...) becomes a real `files_upload_v2`.
- Every persona's DM becomes a real `chat.postMessage` to a private channel.
- Every wire event lands in the channel-adapter the same way a real user's would.

### 8.2. Person provisioning via dashboard API

Sim no longer writes Persons directly to the ledger. It calls the dashboard's `POST /api/people` endpoint, which writes the Person via the same path a real installer would. This guarantees the sim exercises the production code path.

### 8.3. `wire-replay` tool (the deterministic backstop)

```bash
wormbase wire-replay --tenant baseworm --jsonl fixtures/demo-c-plus-b.wire.jsonl
```

Reads a JSONL of recorded `InfraEvent`s, feeds them through `channel-adapter` in replay mode at production speed. Same code path, deterministic input. Used for:
- CI determinism tests
- L6 demo gates
- The "Slack flaked mid-presentation" backstop

The recording side: `wormbase wire-record --tenant baseworm --out fixtures/demo-c-plus-b.wire.jsonl` runs alongside a sim demo and captures every InfraEvent the channel-adapter emits.

### 8.4. `simulate-flows` deletion

Commit `b7356ab` is reverted. The PRD has no place for a flow-bypass tool. Wire-replay is the only acceptable substitute.

### 8.5. On-thesis criteria

C2 (deterministic — wire-replay is bit-for-bit reproducible), C6 (auditable — sim writes are indistinguishable from production writes).

---

## 9. Wire fix (root-cause)

### 9.1. `files_upload_v2` → `emit_file_received`

Hypothesis (live, today): sim-harness uploads succeed but OpenClaw's JSONL log doesn't capture the `file_shared` event for them, OR the channel-adapter's log-tail filter drops the event.

Investigation (this is the workstream): trace one upload end-to-end via:
1. Slack API response (success / fail + file id)
2. OpenClaw's `slack:` event log (file_shared event present?)
3. OpenClaw's JSONL output (file row written?)
4. channel-adapter's log-tail consumer (file row consumed?)
5. ledger (`channel_adapter.emit_file_received` row present?)

Whichever step drops the event is the bug. Fix and add an L5 integration test.

### 9.2. Mention relevance gate

Hypothesis: the gate's archetype-match logic doesn't trigger for "we should pull our Stripe data so the gross-net rec is clean." Either:
- The "Stripe" archetype isn't registered for the saas pack, OR
- The relevance gate's confidence threshold is too high, OR
- The dispatcher chain's `should_react` predicate is wrong.

Investigation: instrument the gate; log every mention + decision. Find the failing case. Patch.

### 9.3. Coverage

After both fixes: an L5 integration test asserts the full demo-c-plus-b scenario produces every expected ledger entry, end-to-end, on the live wire. No `simulate-flows` invocation anywhere in CI.

---

## 10. Demo arc (7 beats, ~3 minutes)

The demo is the install-and-onboard story, not "watch our prototype work." Tight beats:

1. **(0-30s) Install on stage.** Ricardo on stage; clicks "Connect to Slack" on the WormBase landing page. OAuth completes. Tenant created. Installer Person created. First admin grant. Worm posts "hi" in #general. **The audience watches a real install in 30 seconds.**

2. **(30-60s) Pick domain pack + invite.** Tier 2: SaaS pack, three invites. Co-admin Persons created. Domains seeded. Classifications confirmed. **The audience watches a 60-second team setup.**

3. **(60-100s) First file drop.** Co-admin (LLM persona on real Slack) drops `sales-q3.csv`. Worm proposes the source. /sources flips bronze (audience sees real-time render). Cascade fires; silver and gold land within 2 seconds. emit_kpi_proposed lands.

4. **(100-150s) Conversational mention → proactive offer.** Co-admin: "we should also pull our Stripe data." Worm posts proactively in the channel: "I can wire Stripe up — DM me an API key." Co-admin DMs the key. Stripe source connects. Cascade fires.

5. **(150-180s) Q&A with citations.** Carol asks "what's our Q3 net?" Worm answers with **receipts**: source ids, hashes, computation timestamp. Audience sees /trace render the receipt chain in real time.

6. **(180-220s) Multitenancy + role-aware nav.** Tenant switcher: baseworm → democorp → back. Same product surface, separate ledger, sparser lake. Same code path. **Then:** flip Person chip from "admin" to "member" view; nav chrome adapts; same data, different lens.

7. **(220-260s) Self-improvement per user.** /research opens. Carol's CFO-position autoresearch experiments from the past virtual week. 8 keeps, 15 discards. Headline: "Q3 forecast accuracy +4%." This is the C5 institutional-AI close.

**~260s total.** Tight, scripted, every beat ledger-truth-only. No narrator crutches. No "narrate this beat — pre-recorded ledger insert."

### 10.1. On-thesis criteria fired in the arc

C1 (worm proposes sources, Persons, KPIs, experiments), C2 (deterministic install + cascades + receipts), C3 (lake + team + experiments compound through the demo), C5 (research tab), C6 (every action receipted), C7 (role-aware nav, position-aware autoresearch), C8 (worm posts unprompted welcome + proactive offer). **Seven of eight criteria visible in 4 minutes.**

---

## 11. Cleanup pass (the strong-implementation work)

Catalog of demo-only seams and tight-coupling shortcuts to delete or refactor:

### 11.1. Code-level

- **`wormbase-worm-core simulate-flows`** — delete. Revert `b7356ab`.
- **`personas.yml`** — promote to `Person` table. Sim-harness reads from the table; admin can edit Persons via /people; no YAML.
- **`source_builder._proposals` / `._source_ids`** — `_private` attributes reached from `cli.py` and `service.py`. Promote to public methods (`get_proposal(cid)`, `get_source_id(cid)`) or extract a public `SourceLedgerView` class.
- **Slack-only assumptions in channel-adapter** — extract `SlackChannelAdapter` from the generic `ChannelAdapter` base. Discord and Teams adapters live alongside.
- **Source-type-specific code paths in source-builder** — extract `Connector` base; existing CSV / Postgres handling become `CsvConnector` / `PostgresConnector`.
- **Hardcoded persona lists in dashboard** — replace with ledger reads.
- **`fixtures/` references in production paths** — every fixture should be sim-only or replay-only. Production code never touches fixtures.

### 11.2. Doc-level

- Repo-root `CLAUDE.md` gets the identity model, role facets, and dashboard-truth principle.
- `2026-04-26-wormbase-product-arc.md` Step 1 expanded to cover installer-Person creation + auto-user-discovery.
- `docs/demo-runbook.md` rewritten for the 7-beat arc (no narrator crutches; the 14-beat C+B scenario is retired in favor of the 7-beat install arc).
- New `docs/architecture/connectors.md` and `docs/architecture/channel-adapters.md` describe the abstractions.

### 11.3. Test-level

- L5 integration test for the full 7-beat arc on the live wire (no simulate-flows).
- L6 demo gate F1 (demo runtime ≤ 3m30s) covers the 7-beat arc.
- L6 demo gate N2 (no placeholders on screen) gates fixture-references in dashboard.

---

## 12. Out of scope for Thursday

To prevent scope creep, these are **explicitly out** for the 4-day push:

- Voice agent live-call (the screencap fallback stays; ElevenLabs live cuts only if Step 5 demo time allows).
- Pricing UI (no Stripe billing integration on dashboard; pricing primitives are visible via the data they imply, not via a billing screen).
- SSO beyond Slack/Discord/Teams platform OAuth (no Google Workspace SSO, no SAML).
- Mobile dashboard (desktop-first; mobile is a polish phase post-demo).
- Real Discord and Teams adapter `send` and `file_upload` implementations (stubs are fine; the listen + install paths are real).
- Connector implementations beyond the eleven listed in 2.2 (e.g. no Notion, no Jira, no Linear connectors day-one — they're plugins, not core).

---

## 13. Acceptance gates (PRD-level success criteria)

Each gate is testable. Gates a-h ship by Thursday.

| Gate | Assertion | Layer |
|---|---|---|
| a | Installer can install via Slack OAuth and reach `/dashboard` in ≤ 30s | L6 demo gate |
| b | A new Person auto-discovered from chatter reaches `/people` pending proposals in ≤ 60s | L5 integration |
| c | A file dropped in a connected channel writes `emit_file_received` + `emit_source_proposed` + cascade entries in ≤ 5s | L5 integration |
| d | The 7-beat demo arc runs end-to-end on real Slack with zero narrator crutches | L6 demo gate |
| e | `simulate-flows` is absent from the repo (search returns nothing) | linter / grep gate |
| f | All eleven day-one connectors implement the `Connector` Protocol and pass their integration test | L4 service |
| g | All three day-one channel adapters (Slack / Discord / Teams) implement `ChannelAdapter` and pass `listen` smoke tests | L4 service |
| h | Every dashboard tab renders correctly under each role lens (installer / admin / member / observer) | L2 component |
| i | wire-replay reproduces a recorded JSONL into bit-identical ledger entries (modulo timestamps) | L5 integration |
| j | The dashboard's `/people` allows merge of two Persons into one with audit trail | L2 + L5 |

---

## 14. Open questions for the plan stage

- Connector secrets storage: KMS-wrapped in Postgres, or a dedicated secrets service? **Default:** KMS-wrapped in Postgres for Thursday; dedicated service is post-demo.
- Multi-Person SSO: do we support a Person being represented by both an SSO email and a platform identity simultaneously, with the SSO email being the canonical identity? **Default:** yes.
- Tenant-per-email-domain default: too aggressive for orgs with multi-domain corporate emails. **Default:** keep the auto-detect; admins can override at install time.
- The "open the worm to all channels" toggle (Tier 2): on by default for ≤ 50 members, off for > 50. **Default:** ship that heuristic.

---

## 16. Data products + notebooks

### 16.1. Principle

Every analysis output the worm produces — chart, table, board-deck breakdown, anomaly report, retention cohort, runway model, autoresearch experiment — is a **first-class data product**: a tracked, replayable artifact with full provenance and consumption trace. Not a one-shot chat reply.

This closes a gap in §10's demo arc: beat 5 ("Carol asks Q3 net revenue, worm answers with citations") today produces a chat receipt but nothing the user can come back to, drill into, or share with a board member. With this surface, the answer becomes an artifact at `s3://wormbase/{tenant}/data-products/{id}/{run_id}.html`, addressable from `/data-products`, citable in audits, replayable from pinned source-hashes.

**Every artifact carries:**
- **Generation provenance** — sources used (with their bronze/silver/gold hashes), the worm's intermediate steps, the requestor (Person + role + position), the domain, the question that triggered it.
- **Consumption trace** — every Person who viewed it, every channel it was shared to, every decision that cited it.
- **Replay primitive** — re-run against pinned source-hashes produces a bit-identical artifact.

Notebooks are first-class authored artifacts: multi-cell, replayable, signable. The autoresearch loop's wins (PRD §10 beat 7 — Carol's CFO experiments) become published notebooks, not just metric deltas.

### 16.2. Ledger entries (extends §15.1)

| Tool | Args |
|---|---|
| `emit_data_product_proposed` | `{data_product_id, name, kind: "chart"\|"table"\|"report", requested_by_person_id, sources_required[], domain_id, parameters, prompted_by_message_id?}` |
| `emit_data_product_generated` | `{data_product_id, contents_uri, content_hash, kind, source_hashes[], generated_by, duration_ms, ts}` |
| `emit_data_product_consumed` | `{data_product_id, consumed_by_person_id, channel?, surface, ts}` (surface ∈ "dashboard"\|"chat"\|"voice"\|"export") |
| `emit_data_product_archived` | `{data_product_id, archived_by, reason}` |
| `emit_notebook_proposed` | `{notebook_id, name, cells[], kernel: "python_local"\|"python_pandas"\|"sql_postgres"\|..., proposed_by_person_id, domain_id}` |
| `emit_notebook_run` | `{notebook_id, run_id, cell_outputs[], cell_hashes[], duration_ms, kernel_state_hash, status: "ok"\|"error", run_by}` |
| `emit_notebook_published` | `{notebook_id, run_id, owner_person_id, domain_id, version, published_by}` |
| `emit_notebook_archived` | `{notebook_id, archived_by, reason}` |

Cell outputs are inline JSON for primitive types; large outputs (DataFrames, plots) materialize to object storage and the entry carries the `contents_uri` + `content_hash`.

### 16.3. Projection tables (extends §15.1)

| Table | Key columns |
|---|---|
| `projection_data_products` | `data_product_id, tenant_id, name, kind, status, requested_by_person_id, domain_id, latest_run_seq, generated_at, content_hash, contents_uri` |
| `projection_data_product_runs` | `run_id, data_product_id, tenant_id, generated_by, ts, source_hashes[], content_hash, duration_ms` |
| `projection_data_product_consumption` | `consumption_id, data_product_id, person_id, surface, ts, channel?` |
| `projection_notebooks` | `notebook_id, tenant_id, name, kernel, status, owner_person_id, domain_id, latest_run_id, latest_published_run_id, version` |
| `projection_notebook_runs` | `run_id, notebook_id, tenant_id, status, ts, run_by, kernel_state_hash, duration_ms` |

### 16.4. Storage strategy

- **Artifact bytes** in object storage. Default backend is S3-compatible (LocalStack in dev, real S3 in prod). Path scheme: `s3://${bucket}/${tenant_id}/data-products/${data_product_id}/${run_id}.${ext}` and `.../notebooks/${notebook_id}/${run_id}.html`. The ledger carries the `contents_uri` + `content_hash`; never the bytes.
- **Notebook source** as YAML-spec (cells = list of `{kind: "code"|"markdown"|"sql", source: str, language: str}`). Simpler than `.ipynb`, easier to diff in PRs. A converter to `.ipynb` for export ships in F4.
- **Replay** = re-run the YAML against pinned source-hashes. If the source bytes have changed (hash mismatch), the run is flagged "source drift" and a new artifact is generated with a new ID — the old one stays accessible.

### 16.5. Notebook execution model

- **Day-one kernel**: `python_local` — a sandboxed Python subprocess with `pandas`, `numpy`, `matplotlib` available, with the lake's silver/gold tables exposed as DataFrames via a thin connector adapter.
- **Future kernels**: `sql_postgres`, `sql_snowflake`, `python_databricks` — slot into the same `Connector.notebook_kernels` capability (B1's `Connector` Protocol gets an optional `notebook_kernel(handle, source) -> AsyncIterator[CellOutput]` method).
- **Cell-level provenance**: each cell's output carries the hash of its inputs (predecessor cell outputs + source data). Replay determinism guaranteed at the cell level.
- **Resource limits**: cells time out at 30s default; admins can extend per-notebook. Memory cap at 512MB. Out-of-bounds runs write `emit_notebook_run` with `status: "error"`.

### 16.6. Dashboard surface

- **`/data-products`** — table of all artifacts in the tenant. Filters: domain, person (requested_by, generated_by, consumed_by), kind, date range, classification. Each row: name, kind, owner, generated_at, source count, consumption count, freshness badge. Click drills into the rendered artifact + source hashes + replay button + consumption history. Bulk actions (admin-only): archive, re-run.
- **`/notebooks`** — table of notebooks. Click drills into the notebook viewer (read-only by default; admins + maintainers can re-run; admins can publish a new version). Each notebook shows cells + the latest run's cell outputs side-by-side. Diff view for comparing two runs.
- **`/people/{id}` extension** — three new sections:
  - "Data products requested" — what this Person triggered the worm to produce
  - "Data products consumed" — what they viewed (the audit trail)
  - "Notebooks authored" — what they own as maintainer
- **`/domains/{id}` extension** — "Domain data product roster" with freshness indicators (green = generated within last 7 days; amber = 30 days; red = older). Admins click to re-run stale artifacts.

### 16.7. Agentic generation patterns

- **KPI question → data product**: when the worm answers a `@WormBase what is …` question, it writes `emit_data_product_proposed` + `emit_data_product_generated` + posts the chat reply with a link back to the artifact. The chat reply's existence is unchanged; the artifact is the new addition.
- **Autoresearch loop → notebook**: each "keep" experiment from the per-Person autoresearch loop publishes a notebook artifact summarizing the experiment, the metric delta, the kept hypothesis. The notebook lives at `/notebooks/<auto>` and shows up on the Person's `/people/{id}` page under "Notebooks authored" with `owner_person_id = <the_person_the_loop_ran_for>` (the worm authors on their behalf).
- **Process_extractor → recurring data product proposal**: when the same data question recurs in chatter (the existing `emit_recurring_question` entry from W2.J), the worm proposes a recurring data product (e.g. "Should I generate a weekly Q3-net rollup automatically?"). Admin confirms; from then on the worm regenerates on schedule, writing `emit_data_product_generated` weekly.
- **Decision_recorded → cited data products**: when the process_extractor records a decision (`emit_decision_recorded`), and that decision references an artifact, the artifact's `consumption_count` increments. Auditors can trace decision → artifact → source bytes → ingest provenance.

### 16.8. On-thesis criteria

- **C2 deterministic output** — every artifact replayable from pinned source-hashes
- **C3 compounding state** — artifacts accumulate; consumption history compounds
- **C5 metric-governed self-improvement** — autoresearch wins materialize as published notebooks (not just metric deltas)
- **C6 auditable governance** — every artifact + consumption is a ledger receipt
- **C7 domain specialization** — per-domain rollups; per-position kernel routing
- **C8 unprompted surface, prompted depth** — worm publishes proactively; Person opens for depth

### 16.9. Demo arc impact (extends §10)

- **Beat 5 (Carol Q3 net)** — the worm's answer now drops a `data_product_id` link. Audience flips to `/data-products`, sees the artifact land in real time, opens it. Source hashes visible. Replay button re-runs. **Two seconds of new screen-time, one big new credibility beat.**
- **Beat 7 (Carol's CFO research)** — the autoresearch loop's wins are notebooks. Audience opens `/notebooks`, sees the latest published one, scrolls through cells, sees the metric delta inside the notebook, not just on a dashboard tile. **Strongest C5 evidence the demo will have.**

### 16.10. Out of scope for Thursday (extends §12)

- Custom kernel spec (only `python_local` ships)
- Notebook collaborative editing (single-author, single-publisher per version)
- Real S3 storage in dev (use LocalStack; prod swap is config-only)
- Notebook → PDF export pipeline (post-demo polish)
- Public sharing links (every artifact is tenant-scoped)

### 16.11. Acceptance gates (extends §13)

- **k**: A KPI question in chat produces a `data_product_id` link visible in `/data-products` within 5s. (L5 integration)
- **l**: The autoresearch loop produces at least one `emit_notebook_published` entry per (Person × position) per virtual week. (L4 service)
- **m**: Replay of a published notebook against the same source-hashes produces a bit-identical content_hash. (L4 service)
- **n**: `/data-products` filtered by `(domain=finance, person=Carol)` returns the right subset under the role lens. (L2 component)

---

## 17. Connector-first onboarding + wizard-vs-bot fork

> **REVISED 2026-04-27 — partial walkback.** The user flagged that connector-first front-loads too much friction: Tier 0 should be one tap (chat platform connect), with a default `LocalLakeConnector` pre-provisioned per tenant providing all three medallion layers from minute zero. External data sources are progressive enhancement, added later via conversation OR `/sources/new`. Bronze/silver/gold can land in any combination per connector — not a forced sequence. See `feedback_minimal_friction_onboarding.md` for the durable principle.
>
> **What stays from §17:** wizard-vs-bot fork (now post-install nudge); setup_mode persistence; `SetupConversationLoop`; the connector grid itself (it moves from `/onboarding` front door to `/sources/new`, where it always lived from Block D4).
>
> **What walks back:** Tier 0 = connector grid → Tier 0 = chat-platform connect; T1a per-connector OAuth as install-blocking → T1a = post-install action available from `/sources/new`.
>
> **Block I in the plan tracks the rework.**

### 17.1. Principle (supersedes §6 lifecycle)

The original PRD §6 lifecycle assumed channel-first onboarding ("Connect to Slack" as Tier 1). That's wrong. **The first connection is a data source from the connector catalog.** A single-person evaluator should be able to prove the product against their own data without committing a Slack workspace. The chat platform connect becomes one option among N, not THE option.

After the first source is connected and the medallion cascade has fired (bronze → silver → gold + first KPI proposed), the user picks how to complete the rest of the setup:

- **Wizard:** existing dashboard Tier 2 + Tier 3 — domain pack, classification defaults, admin invites, KPI tree definition. GUI-driven. Same as the original PRD.
- **Bot:** the worm DMs the installer in a connected chat platform and leads a structured setup conversation. One question at a time; user replies; worm writes the corresponding ledger entry. Same outputs as the wizard, different surface. **Requires a chat platform to be connected.**

Both paths produce identical ledger output. Only the UX differs.

### 17.2. Tier sequence (revised)

```
T0  Land           connector grid + "or connect a chat platform" + "sign in"
T1a Connect source (per-connector OAuth or credential paste)
                   • Stripe / Salesforce / HubSpot / GSheets → OAuth
                   • Snowflake / BigQuery / Postgres → credential paste
                   • CSV → upload + tiny "about you" form (name + email + position)
T1b Cascade        bronze + silver + gold + first KPI proposed (≤ 5s after connect)
T2  What's next    three buttons:
                   • "Add another source" → loop back to T0 connector grid
                   • "Connect chat platform" → existing OAuth flow
                   • "Continue setup" → fork: wizard or bot
T3a (wizard path)  domain pack picker + admin invites + classification defaults +
                   KPI tree definition (existing Tier 2 + Tier 3 dashboard pages)
T3b (bot path)     worm DMs installer with first setup question; conversation
                   walks through domains/classifications/invites/KPIs; each
                   answer writes a ledger entry; worm posts dashboard link
                   when done
```

### 17.3. Tenant resolution (unchanged from PRD §6.2)

Tenant slug derives from the installer's email domain at first connect. For connectors with OAuth-extracted identity (Stripe → email, Snowflake → username + workspace, Salesforce → user.email), no extra form needed. For credentials-only connectors (Postgres, CSV upload), a 3-field form (name, email, position) precedes the connect.

If a tenant for the email domain already exists, the installer joins as a member (status="proposed"; existing admin must confirm). If no existing tenant, a fresh one is provisioned with this installer as the OAuth grantor.

### 17.4. Setup-mode persistence

A new ledger entry: `emit_setup_mode_chosen {tenant_id, mode: "wizard" | "bot", chosen_by_person_id}`. Written when the user clicks "Continue setup" in T2 and picks a path. Tenant-level — one mode per tenant. Admins can switch later via `/settings`.

Read-side projection: extend `projection_installs` with a `setup_mode` column populated by folding the entry. Default: `null` (not chosen yet). The dashboard's onboarding-redirect guard checks this — if Install exists but `setup_mode = null`, redirect to T2; if `setup_mode = "bot"`, the worm-core's `SetupConversationLoop` takes over.

### 17.5. Bot-path implementation

**New worm-core module:** `apps/worm-core/src/wormbase_core/setup_conversation.py` — `SetupConversationLoop` class. Runs alongside the existing reactivity loops (chat poller, process_extractor, autoresearch, identity_discovery). Algorithm:

1. Poll the ledger for tenants where `setup_mode == "bot"` AND `setup_progress` is incomplete.
2. For each: read the next question from the YAML-scripted setup conversation.
3. DM the installer via `SlackChannelAdapter.send` (or Discord/Teams adapter as appropriate). Use `conversations.open` to get the DM channel.
4. Listen for the installer's reply via the existing chat_received poller. Route by tenant + person + DM-channel-id. Each reply is a tagged "setup answer" entry (`emit_setup_answer_received {tenant_id, step_id, person_id, answer_text}`).
5. Parse the answer (per step's `expects` schema): one-of, free_text, mention-list. Write the corresponding domain ledger entry: `emit_domain_registered`, `emit_role_assigned`, `emit_kpi_proposed`, etc.
6. Advance `setup_progress` (a separate projection table); post the next question. Loop until done.
7. When all steps complete: post a "Setup complete — your dashboard is at $URL" message + write `emit_setup_completed {tenant_id, completed_at}`.

**Setup conversation YAML** at `apps/worm-core/setup_conversations/saas-default.yml` (and per-domain-pack variants). Each step:

```yaml
- id: domain_pack
  bot_says: "Welcome! What's your team's primary focus? Reply with one of: saas, marketplace, fintech, custom."
  expects: one_of
  options: [saas, marketplace, fintech, custom]
  on_answer: emit_domain_registered_for_pack
  next: classification_default

- id: classification_default
  bot_says: "Got it. For your sales data, default classification: internal or confidential?"
  expects: one_of
  options: [internal, confidential]
  on_answer: emit_classification_default
  next: invite_admins

- id: invite_admins
  bot_says: "Who else should be admin? Tag them, e.g. @bob @carol. Or 'skip'."
  expects: free_text
  on_answer: parse_mentions_emit_role_assigned
  next: first_kpi

- id: first_kpi
  bot_says: "What's your most important KPI for the next quarter? (Free-text — I'll propose; you confirm in the dashboard.)"
  expects: free_text
  on_answer: emit_kpi_proposed
  next: done

- id: done
  bot_says: "All set! Your dashboard is at $DASHBOARD_URL. The worm is now lurking and will start helping. /research will show experiments for your role within 24h."
  on_answer: emit_setup_completed
```

The YAML is loaded at worm-core boot, parsed into a `SetupScript` Pydantic model, used by `SetupConversationLoop` per tenant.

### 17.6. Wizard-path implementation

Existing Tier 2 + Tier 3 dashboard pages (per the onboarding-reconciliation pass) handle this. After the user picks "wizard" in T2, they're routed through `/onboarding/tier2` and `/onboarding/tier3`. Each form submission writes the same ledger entries the bot path would write.

The dashboard's onboarding-redirect guard ensures that until `setup_completed` is in the ledger, every visit to a non-onboarding URL redirects to the next pending tier.

### 17.7. Acceptance gates (extends §13)

- **o**: From T0 land to T1b cascade-complete in ≤ 30s for the connector with the smallest credentials surface (CSV upload). (L6 demo gate)
- **p**: User picks "bot" in T2; worm DMs installer with first question in ≤ 10s. (L5 integration)
- **q**: Bot path completes 5 steps (domain → classification → invite → kpi → done) in ≤ 3 minutes of real chat. (L5 integration, scripted answers)
- **r**: Wizard path completes T2 + T3 in ≤ 90s. (L6 demo gate)
- **s**: Both paths produce the same SET of ledger entries (same `tool` names, modulo timestamps + entry_ids). (L4 service)

### 17.8. Demo arc impact (extends §10)

Beat 1 of the install-arc-7beat scenario inverts:

- **Old beat 1** (0-30s): Install on stage via Slack OAuth.
- **New beat 1** (0-30s): Connector-first install on stage. Installer signs in (email magic link or pre-seeded SSO), picks Stripe (most photogenic — instant numbers), OAuth handshake, cascade fires, audience watches `/sources` go bronze → silver → gold + a KPI propose. **30 seconds to first ledger receipt + first dashboard render.**

Beat 2 (was: domain pack + invites in Tier 2): **NEW** — "What's next?" screen, demo presenter clicks the "Use the worm in chat" button. Worm DMs installer; first setup question lands in Slack. **Audience sees the bot path live.**

Beat 3+ — installer answers two questions in chat (domain → "saas", classification → "internal"); worm acknowledges; ledger entries land. Audience flips to /trace; sees `emit_domain_registered + emit_classification_default` receipts.

The remaining beats (3 file drop, 4 mention proactive offer, 5 Q&A, 6 multitenancy, 7 research) follow as before but compressed since beats 1 + 2 carry more product weight.

This is a **stronger demo** — first 60 seconds show the source connect AND the bot driving setup, both load-bearing for the institutional-AI thesis.

### 17.9. Out of scope for Thursday (extends §12)

- Bot path on Discord/Teams (Slack only for the bot loop in v1; Discord/Teams remain "preview" per the capability-honesty pass).
- Switching `setup_mode` mid-flight (must complete one path or restart from T2).
- Multi-installer / multi-Install per tenant during onboarding (single-installer per tenant; later admin grants can come from invite flow).

---

## 15. Appendices

### 15.1. Ledger entry vocabulary additions (for §3 implementation)

```
emit_install_completed     {tenant_id, platform, installer_person_id, scopes}
emit_install_revoked       {install_id, revoked_by}
emit_person_proposed       {person_id, name, email, proposed_by, identity}
emit_person_confirmed      {person_id, confirmed_by}
emit_person_archived       {person_id, archived_by, reason}
emit_role_assigned         {person_id, role: tenancy, granted_by}
emit_role_revoked          {person_id, role: tenancy, revoked_by}
emit_domain_role_assigned  {person_id, domain_id, role: domain, granted_by}
emit_resource_role_assigned{person_id, resource_id, resource_type, role, granted_by}
emit_identity_linked       {person_id, platform, platform_user_id, linked_by}
emit_identity_unlinked     {person_id, platform, platform_user_id, unlinked_by}
emit_position_proposed     {person_id, position, proposed_by}
emit_position_confirmed    {person_id, position, confirmed_by}

# data products + notebooks (§16)
emit_data_product_proposed   {data_product_id, name, kind, requested_by_person_id, sources_required, domain_id, parameters}
emit_data_product_generated  {data_product_id, contents_uri, content_hash, kind, source_hashes, generated_by, duration_ms}
emit_data_product_consumed   {data_product_id, consumed_by_person_id, surface, channel, ts}
emit_data_product_archived   {data_product_id, archived_by, reason}
emit_notebook_proposed       {notebook_id, name, cells, kernel, proposed_by_person_id, domain_id}
emit_notebook_run            {notebook_id, run_id, cell_outputs, cell_hashes, status, kernel_state_hash, duration_ms, run_by}
emit_notebook_published      {notebook_id, run_id, owner_person_id, domain_id, version, published_by}
emit_notebook_archived       {notebook_id, archived_by, reason}
```

### 15.2. Workstream decomposition (for the writing-plans step)

| # | Workstream | Files (approx) | Wall-clock |
|---|---|---|---|
| W1 | Source abstraction layer + 11 connectors | 25-30 | ~45m parallel |
| W2 | Channel abstraction + Slack/Discord/Teams adapters | 12-15 | ~25m parallel |
| W3 | Identity model (schema + projections + auto-discovery) | 10-12 | ~25m parallel |
| W4 | Role model (3 facets + projections + audit trail) | 8-10 | ~20m parallel |
| W5 | Onboarding rewrite (Tier 0/1/2/3 wizards, real OAuth) | 15-20 | ~35m parallel |
| W6 | Dashboard production rewrite (10+ tabs role-aware) | 30-40 | ~60m parallel |
| W7 | Sim reframe (delete simulate-flows, real channels, wire-replay) | 12-15 | ~25m parallel |
| W8 | Wire fix (file_received + relevance gate + L5 tests) | 6-8 | ~20m parallel |
| W9 | Demo arc rewrite (7-beat scenario + runbook) | 5-7 | ~15m parallel |
| W10 | Cleanup pass (delete demo seams, refactor _private) | 10-15 | ~20m parallel |
| W11 | Data products + notebooks (§16): entries + projections + storage + UI surfaces | 25-30 | ~40m parallel |
| W12 | Connector-first onboarding + wizard-vs-bot fork (§17): T0 grid + setup_mode + bot conversation loop + YAML | 20-25 | ~35m parallel |

**Total parallel wall-clock estimate: ~60-90m** (slowest workstream gates everything; W6 + W11 + W12 are biggest).
**Review bandwidth on the human side is the actual constraint** — pace dispatches so commits land at human-reviewable cadence.

### 15.3. Self-review (per writing-plans)

- Spec coverage vs CEO directive: ✓ (1) source abstraction §2, ✓ (2) team-can-join §4-6, ✓ (3) every feature × user §7.1, ✓ (4) clean implementation §11.
- Placeholder scan: no TBDs, no "implement later," no "TODO."
- Internal consistency: identity model in §4 referenced consistently in §6 (lifecycle), §7 (dashboard /people), §8 (sim reframe). Role grants vocabulary in §15.1 matches §5.
- Ambiguity: §14 lists every choice that could go two ways with an explicit default. Plan stage can override defaults.
- Scope: all four CEO directives covered; out-of-scope §12 explicit.

---

**Next step (per the brainstorming skill flow):** user reviews this PRD. On approval, the writing-plans skill produces the implementation plan with tasks per workstream. After plan approval, parallel subagents dispatch.
