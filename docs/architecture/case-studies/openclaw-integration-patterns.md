# OpenClaw Integration Patterns

OpenClaw is the open-source channel gateway WormBase uses for messaging
platform integration (Slack, Discord, Teams, WhatsApp via Baileys, and
50+ other platforms). This document characterizes OpenClaw's onboarding
pattern, distills the load-bearing primitives, and identifies where the
pattern translates 1:1 to WormBase's institutional-onboarding surfaces
and where institutional concerns require net-new shapes that OpenClaw
itself does not model.

Companion documents:

- [`channel-adapters.md`](../channel-adapters.md) — adapter contract
  and how WormBase wires OpenClaw into the ledger substrate.
- [ADR-0001](../decisions/ADR-0001-listener-shaped-channel-adapter.md)
  — the decision to use OpenClaw's global event log over Hermes's
  responder-shaped hook system.

---

## Headline

OpenClaw's onboarding is shaped around **one unified verb that compiles
to N heterogeneous auth flows under the hood**. `openclaw channels add`
handles token paste, OAuth, QR scan, and paired-device challenges; the
user-facing simplicity comes from a single command surface; the
per-platform heterogeneity is hidden inside the adapter.

Three primitives carry the weight of the pattern: **status-honest
capability badges** (`production` / `preview` / `coming_soon`), **per-
adapter capability sets declared as data** (`{ingest, send, dm,
file_upload, voice}`), and **status probing as a first-class verb**
(`channels status --probe`). Together they make heterogeneous-but-honest
integration visible to the operator.

For institutional onboarding, the OpenClaw shape translates 1:1 on a few
axes (unified verb, status badges, capability declarations, plugin
registry) and not at all on others (org-vs-individual identity,
multi-stakeholder approval, governance baseline, domain ontology,
source-profiling depth, grant model). The institutional analog —
documented in WormBase as `@onboard <object>` — extends OpenClaw's model
from "1 protocol, N messaging platforms" to "1 protocol, N institutional
integration types."

---

## 1. OpenClaw's onboarding shape

### 1.1 The verb pattern

OpenClaw's user-facing onboarding entry point is a single `openclaw
onboard` command. It is the only command a new user runs to reach a
working agent. Everything else (provider auth, gateway config, channel
install, daemon registration) cascades from inside this single verb.

Once the gateway is up, the `openclaw channels` family is the steady-
state verb for managing platform integrations:

```
openclaw channels add          # register a new account
openclaw channels login        # interactive auth (QR, OAuth)
openclaw channels logout       # tear down session
openclaw channels remove       # unregister
openclaw channels list         # show configured accounts
openclaw channels status       # health probe
openclaw channels logs         # per-account log retrieval
openclaw channels capabilities # probe per-channel features
openclaw channels resolve      # name → id lookup
```

The verb is stable across platforms. A user types `openclaw channels add
--channel telegram --token <bot-token>` for Telegram and `openclaw
channels add --channel nostr --private-key "$NOSTR_PRIVATE_KEY"` for
Nostr. Same verb, different per-channel flag set. The user's mental model
collapses to "channels are a thing I add"; the heterogeneity of
underlying auth is a flag suffix, not a different workflow.

### 1.2 The bootstrap wizard

The CLI wizard walks an unauthenticated user through eight stages (the
macOS app variant; CLI is condensed):

1. OS security approval (macOS-only — TCC permissions for automation,
   notifications, accessibility, screen recording, microphone, etc.)
2. Local network access — grant network discovery permissions
3. Security notice — review trust model + tool profile defaults
4. Gateway location — local / remote (SSH or Tailnet) / deferred
5. Permissions request — explicit per-capability grants
6. CLI installation — optional npm/pnpm/bun global install
7. Onboarding chat — dedicated agent introduction session
8. Bootstrapping — gateway first-boot, token issuance, daemon registration

The wizard **does not connect any messaging channel by default**. Channel
adds happen post-wizard, on demand, by the user invoking `channels add`
for each platform they care about. This is a deliberate "core first,
channels later" sequencing.

### 1.3 Per-platform auth heterogeneity (under one verb)

OpenClaw supports five auth shapes, all surfaced via the same
`channels add` verb:

| Auth shape | Platforms | Mechanism |
|---|---|---|
| Token paste | Telegram, Discord, Slack, Matrix (access-token mode) | User pastes a token from the platform's developer console: `--token`, `--bot-token`, `--app-token`, `--access-token`. Synchronous; no interactive step. |
| Key-pair | Nostr | `--private-key`. Same shape as token paste but cryptographically asymmetric. |
| CLI-bridged | Signal, iMessage | `--signal-number`, `--cli-path`. OpenClaw shells out to a platform CLI binary (signal-cli, AppleScript bridge for iMessage). |
| OAuth bot install | Slack (app-manifest workflow) | User creates an app via the platform's developer console using OpenClaw's published manifest, downloads tokens, pastes into `channels add`. The OAuth dance happens in the platform's UI, not OpenClaw's. |
| QR-pairing | WhatsApp (Baileys), Telegram (user-mode) | `openclaw channels login --channel whatsapp` — gateway prints a QR code; user scans with the primary phone via "Linked Devices"; pairing approved in-app. |

The OAuth flow is conspicuously absent for most platforms — OpenClaw
delegates OAuth to the platform's own UI, then brings the resulting
tokens back via `--token`. This is a deliberate architectural choice:
OpenClaw never hosts an OAuth redirect URL, never owns a `client_secret`,
never has a "Sign in with X" button. The user is the OAuth ferry.

### 1.4 Configuration shape

Channels persist as JSON blocks under
`channels.<platform>.accounts.<accountId>`. A representative shape:

```json
{
  "channels": {
    "defaults": { "groupPolicy": "allowlist" },
    "slack": {
      "enabled": true,
      "mode": "socket",
      "dmPolicy": "pairing",
      "accounts": {
        "main": {
          "appToken": "xapp-...",
          "botToken": "xoxb-...",
          "groupPolicy": "open",
          "allowBots": true
        }
      }
    },
    "whatsapp": {
      "enabled": true,
      "selfChatMode": false,
      "dmPolicy": "pairing",
      "allowFrom": ["..."]
    }
  },
  "bindings": [
    { "type": "route", "agentId": "main",
      "match": { "channel": "slack", "accountId": "main" } }
  ]
}
```

Notable properties:

- **Per-channel policy primitives** (`dmPolicy`, `groupPolicy`,
  `allowFrom`, `groupAllowFrom`) are config-shaped, not code-shaped.
  Operator policy changes admit edits to config + a restart; no SDK call
  needed.
- **Bindings** link channels to agents. The same channel can route to
  different agents based on `match` filters. This is OpenClaw's
  tenant-routing primitive.
- **Plugins are registered separately** under
  `plugins.entries.<name>.enabled`. Channel-level `enabled: true` is
  necessary but not sufficient: the plugin must also be registered in
  `plugins.entries`.

### 1.5 Status visibility + capability declarations

OpenClaw's status surface is **probe-based, not flag-based**.
`channels status --probe` invokes per-account reachability and optionally
deep capability checks, returning structured `{works, probe failed,
audit ok, audit failed}`.

When the gateway is unreachable, status falls back to config-only
summaries — a credential set via `SecretRef` that's unavailable reports
as "configured with degraded notes," not as "broken." The distinction
between *"I never configured this"* and *"I configured this but the
live world has changed"* is preserved.

A key lesson the docs explicitly call out: **do not use session surfaces
as a health signal**. A connected-but-quiet account is healthy even
when no recent traffic is visible. Health is a probe, not an
absence-of-traffic check.

WormBase mirrors this via three load-bearing dataclass fields on every
`ChannelAdapter`:

```python
platform: Platform
capability: set[ChannelCap]       # {"ingest","send","file_upload","dm","voice"}
status: AdapterStatus              # "production" | "preview" | "coming_soon"
status_note: str                   # operator-facing one-liner
```

Each adapter declares its own status. The dashboard's channels picker
reads these declarations directly — no out-of-band toggle, no truth split
between code and UI.

### 1.6 Plugin architecture

OpenClaw's plugin model has four extension surfaces: channel plugins,
memory plugins, tool plugins, provider plugins. Plugins are npm packages
discovered via the `openclaw.extensions` field in workspace
`package.json`. The loader hot-loads them, validates against JSON Schema,
and registers them at gateway boot.

There is no public marketplace surface — discovery is package-name-based.
A user has to know `@openclaw/whatsapp` exists to install it. Compare
with VS Code extensions or Slack's app directory: OpenClaw is at the
"package + manifest" stage, not the "browsable catalog with one-click
install" stage.

### 1.7 Identity model — minimal, per-account, no cross-platform stitching

OpenClaw's identity model is per-account: each `channels add` produces an
`accountId` scoped to one `(platform, gateway)` pair. There is no
cross-platform identity stitching in the OpenClaw core — a user with
both a WhatsApp number and a Slack ID is two separate accounts on
OpenClaw's side, with no first-class link.

WormBase builds the identity-stitching layer on top: `Person` +
`PersonIdentity` resolve OpenClaw's platform-native ids to internal
`person_id`s. This is the largest gap between OpenClaw's pattern and an
institutional analog: OpenClaw stops at "account on a channel";
institutional onboarding has to traverse to "Person across the org."

### 1.8 Failure modes + recovery

Recovery patterns are operator-driven, per-account, via CLI, with
operator-visible logs:

| Failure | Symptom | Recovery |
|---|---|---|
| QR code expired before scan | WhatsApp QR rotates every ~20s; visible in container logs | Re-run `channels login`; check container clock drift |
| Pairing succeeds but no messages | Linked-device demoted, or admit policy blocks | Check primary phone's Linked Devices panel; verify `groupPolicy` / `allowFrom` |
| Token revoked (Slack, Discord, Telegram) | API returns 401/403; status probe `probe failed` | Re-issue token in platform admin console; `channels add` overwrites |
| Session ended on another device (WhatsApp) | `connection_close` with `reason="loggedOut"` | Re-pair flow — no refresh-token in WhatsApp Web protocol |
| Account banned (Baileys WhatsApp) | Repeated `loggedOut` within hours | Rotate to fresh test number; appeals rarely granted |
| Plugin schema drift | `openclaw config validate` fails post-upgrade | Manual `openclaw config set <new-path>`; schema migration via CLI |
| History-replay flood | `messaging-history.set` floods on reconnect | Expected; WormBase tags as `delivery_mode="history_sync"`, gates speak-path with `LiveOnly` |

OpenClaw natively has no automatic re-pair, no token-refresh background
loop, no proactive notification. Recovery is operator-driven; the
operator's interface is the gateway log stream + CLI.

### 1.9 Outbound transport heterogeneity (under one verb)

A 2026 empirical probe found OpenClaw exposes **no plain HTTP send
route**. The outbound surface is the WebSocket Gateway, accessed via
`openclaw message send`. The CLI's `message send` subcommand is the
documented outbound surface for every channel; underneath, OpenClaw
routes to the subprocess CLI for WhatsApp, HTTP for Discord, Socket
Mode for Slack, etc. Verb-uniformity is the user-facing contract;
transport-heterogeneity is the implementation detail.

---

## 2. Pattern strengths — what to mirror

Each property below is rated for translation quality to institutional
onboarding and paired with the institutional analog.

### 2.1 Unified verb

**OpenClaw:** `openclaw channels add --channel <X>` — one verb, N
platforms.

**Institutional analog:** `@onboard <thing>` where `<thing>` ranges over
the institutional ontology: connector, channel, domain, person, role,
policy, agent, subscription. The verb compiles to the right wizard /
form / OAuth flow based on the noun.

**Translation quality:** direct. Most adjacent products (Fivetran,
Census) have separate "Add source" / "Add destination" verbs; OpenClaw's
typed-noun pattern is more general.

### 2.2 Status-honest capability badges

**OpenClaw:** `production` / `preview` / `coming_soon` per adapter,
declared in the adapter class, surfaced in the picker.

**Institutional analog:** every integration type (connector, channel,
agent grant, governance policy) carries the same three-state badge,
plus a fourth `requires_plan_upgrade` for SaaS billing.

**Translation quality:** direct, and arguably more important at
institutional scale — institutional integrations have more failure
modes than messaging.

### 2.3 Capability declarations as data

**OpenClaw:** `capability: set[ChannelCap]` — adapter declares which
verbs it supports; downstream code reads the set.

**Institutional analog:** every connector declares `{discover, profile,
sample, watch}` (already canonical in WormBase). Extends to **agents**
(which domains / classifications they can read, which they can act on)
and **roles** (which actions they can grant). Cross-cuts the role ×
domain × resource × classification matrix.

**Translation quality:** direct. The existing `Connector` Protocol
proves the shape extends.

### 2.4 Status probe as a verb

**OpenClaw:** `channels status --probe` invokes a live probe; falls
back to config-only when unreachable.

**Institutional analog:** `@status <object>` for every institutional
object — connector status, channel status, agent status, grant status,
policy status, lineage staleness. The dashboard's per-domain health
surface aggregates these.

**Translation quality:** strong; needs more nouns than OpenClaw
supports.

### 2.5 Plugin registry shape

**OpenClaw:** plugins are npm packages with an `openclaw.extensions`
manifest field. Discovered at load, registered in config, validated
against JSON Schema.

**Institutional analog:** WormBase already has
`wormbase_connectors.registry` and `wormbase_channel_adapters.registry`.
Extends to **governance policy templates** (`wormbase_policies.registry`),
**domain packs** (`wormbase_domain_packs.registry`), **agent skill
packs** (`wormbase_agent_skills.registry`). Each is additive; core stays
stable. The institutional version is multi-registry, not single-registry
like OpenClaw.

**Translation quality:** same shape, more registries.

### 2.6 Verb-uniform outbound

**OpenClaw:** `openclaw message send --channel <X> --target <Y>
--message <Z>` — one verb, N transports underneath.

**Institutional analog:** `@deliver <data_product>` to a Person /
domain / channel — one verb, N transports (Slack DM, email digest,
dashboard notification, Notion page write, JIRA ticket). The agent calls
`deliver`; the substrate routes to the right transport per Person's
preference.

**Translation quality:** direct.

### 2.7 Per-account log retrieval

**OpenClaw:** `channels logs --channel <X> --account <Y>` — per-
account, structured, time-bounded.

**Institutional analog:** `@logs <noun>` for every institutional
object. Maps onto the existing ledger substrate — the ledger is the
canonical log; this verb is the dashboard view over it. WormBase's
`/activity` and `/trace` tabs are this verb manifest.

**Translation quality:** direct; maps onto the existing substrate.

### 2.8 Onboarding-deferred channel adds

**OpenClaw:** `openclaw onboard` sets up gateway + provider + daemon but
does not connect any channel by default. Channels are an explicit
post-onboarding decision.

**Institutional analog:** a working data agent before any external
source is connected. WormBase commits to this via the minimal-friction
onboarding posture — Tier 0 is chat-platform connection only; a default
local data source plays all three medallion layers; external sources are
progressive enhancement.

**Translation quality:** direct. Already a WormBase commitment;
OpenClaw's pattern validates it.

### 2.9 What does NOT translate

- **OS-level permission grants** (TCC permissions on macOS) —
  institutional onboarding is org-scoped, not device-scoped. No analog
  needed.
- **CLI-first** — OpenClaw is a developer tool first; institutional
  onboarding has to surface in a web UI to non-developer admins. The
  verb pattern survives the medium shift, but the entry point isn't a
  terminal.
- **Provider-first sequencing** (pick LLM provider before anything else)
  — institutional users don't pick the LLM. The vendor picks. This
  stage disappears.
- **Per-account, single-tenant** — OpenClaw's gateway is single-
  operator. Institutional onboarding is multi-stakeholder from minute
  one.

---

## 3. Institutional concerns OpenClaw does not model

Net-new surfaces an institutional-onboarding UX must invent.

### 3.1 Org identity vs personal identity

OpenClaw: one operator, one machine, one set of credentials. Identity is
the OS user account.

Institutional: many people, one org. **Org-identity (`tenant_id`),
Person-identity (one per real human), and PersonIdentity (per-platform
fan-out)** are three orthogonal axes. The installer is one Person with
`tenancy.installer + tenancy.admin` grants; subsequent users have their
own grant surface.

UX consequence: onboarding has a "who am I" step (Person creation), a
"what org" step (tenant creation), and an "invite teammates" step. None
of these exist in OpenClaw.

### 3.2 Multi-stakeholder approval flow

OpenClaw: the operator decides. One pair of hands installs everything.

Institutional: legal, ops, IT, data, and security may each need to
consent to different parts of the integration. Installing a Slack bot
is the installer's call, but classifying customer email as `pii`
triggers a legal review.

UX consequence: onboarding has approval branches that wait for human
decisions before progressing. The wizard pauses; the right reviewer
gets notified; the org-onboarding sequence resumes when approved.

### 3.3 Governance + classification baseline before data flows

OpenClaw: no governance model. Messages flow; admit policies
(`allowlist`, `pairing`) are the only gate.

Institutional: every source carries `classification ∈ {public, internal,
confidential, pii, regulated}`. Policies attach to (domain,
classification, resource) triples. **The baseline must be set before
the first source ingest**, or PII flows into a public lake.

UX consequence: onboarding has a classification-defaults step — for each
domain, what's the default sensitivity? This is a policy-template picker
(SaaS / marketplace / fintech presets), not a one-click connect.

### 3.4 Domain pack picker

OpenClaw: no domain model. Channels and agents exist; there's no "this
channel belongs to finance" concept.

Institutional: data and conversations partition by business domain
(sales, product, finance, support, etc.). Each domain has an owner,
default classification, and a set of expected resources. Pre-seeded
domain packs ship as opinions about a vertical (SaaS, marketplace,
fintech).

UX consequence: onboarding has a domain-pack picker as Tier 2 of install.
Pick "SaaS startup" → get pre-seeded domains with default owners (the
installer) and default classifications. Customize from there.

### 3.5 Co-admin invites and role grants during onboarding

OpenClaw: roles don't exist. The operator is root.

Institutional: roles are three independent facets (tenancy, domain,
resource) × N grants per Person. Onboarding has to issue grants during
install — at minimum, the installer auto-grants themselves
`tenancy.admin + tenancy.installer + domain.owner(every-pack-domain)`.
Co-admin invites grant `tenancy.admin` to a second Person before that
Person has even joined.

### 3.6 Source connection has more shape than channel connection

OpenClaw channel connect: `add → login → verified`. Three states.

Institutional source connect: `proposed → confirmed → connected →
profiled → classified → first-sample → ingested → lineage-attached →
quality-gated`. Nine states, each a substrate-level write with
provenance.

UX consequence: the source-connection wizard is multi-page with progress
indicator (Fivetran-style), not a single-command verb. Status badges per
stage; aha moment is "first sample visible" plus "first KPI proposed
against it."

### 3.7 Quality and lineage axes activate per source

OpenClaw: no concept of data quality, no lineage.

Institutional: each new source brings its L3 lineage inference and L7
quality checks. These activate automatically on source connect. The user
doesn't ask for them; the worm proposes them; the admin confirms.

UX consequence: the source-add step triggers downstream worms (lineage,
quality) that produce proposals the admin reviews. The aha moment
expands beyond "first sample visible" to "first lineage edge proposed"
and "first quality check proposed."

### 3.8 Agents register with grants per domain

OpenClaw: agents are first-class but have no scoping. The default agent
sees everything.

Institutional: each agent (or named-actor worm) declares which domains
it has read/write grants in, at which classification levels. The
research-loop worm operating on PII data needs explicit consent;
without it, the substrate denies.

UX consequence: onboarding has an agent-grant matrix — for each worm,
which domain × classification cells does it operate in? Defaults are
conservative; admins widen explicitly.

### 3.9 Subscription / billing

OpenClaw: open source; no billing.

Institutional: WormBase is SaaS-first. Onboarding ties to a subscription
tier, seat count, source count, conversation volume, premium adapters
(on-prem inference unlocks). The connector/channel picker includes a
fourth `requires_plan_upgrade` state.

---

## 4. Adjacent product UX scan

Five products with overlapping shape — Fivetran (managed ELT), Airbyte
(open ELT), Atlan (data catalog + governance), Census (reverse ETL), dbt
Cloud (transformation IDE). Each has solved part of the
institutional-onboarding problem; none has solved it whole in the
OpenClaw shape.

### 4.1 Fivetran — connector catalog as the front door

Verb pattern: "Add source" / "Add destination" (two verbs). Catalog-
first: the user lands on a searchable directory of 700+ connectors.

Status badges: `Private preview` / `Beta` / `New` surfaced in the
catalog UI.

First-connect flow: select connector → credential paste → schema
selection → frequency picker → test connection → first sync. Five+
pages, progress indicator, save-and-resume.

Adjacent gap: no governance baseline. Fivetran assumes you have a
downstream catalog (Atlan, Alation, Collibra) to apply classification.
Onboarding is connector-only, not connector + domain + governance.

### 4.2 Airbyte — connector builder + catalog

Verb pattern: "Add source" + "Add destination" + "Create connection"
(three verbs).

Innovation surface: **Connector Builder** — no-code/low-code
configuration of a new connector via AI Assistant. The friction to add
a new connector drops from "write code" to "paste a doc URL." This is
the OpenClaw plugin-add equivalent with AI scaffolding.

Adjacent gap: community-led; uneven connector quality. Status honesty is
a known weak point — customers report only learning of connector issues
via external monitoring, not via Airbyte's own status surface. The
OpenClaw `--probe` discipline would be high-value here.

### 4.3 Atlan — domains and data products as the front door

Verb pattern: button-driven, no command syntax. Form-modal-heavy.

Onboarding shape: Month 1 is "core systems connected + governance
framework defined"; Month 2 is "priority domains with stewards trained";
production reach in 4-6 weeks. **Atlan is the slowest of the adjacent
products** — it accepts the cost of multi-stakeholder governance
up-front.

Domain-creation flow: Products sidebar → Get started → Overview → set
Name + Owners + optional theme + description → Create. Owners are
assignable at creation time — direct analog to a domain-pack picker
assigning owner Persons.

Adjacent gap: no channel layer. Atlan is read-only on the conversation
side; institutional knowledge accumulates via documentation, not via
lurking on chat. WormBase + OpenClaw composes Atlan's domain model with
OpenClaw's channel model.

### 4.4 Census — connect-flow for reverse ETL

Verb pattern: Destinations in left nav → select destination platform →
credential paste → schema mapping → activation cadence.

Innovation surface: **Census Connect** — embeddable client-side workflow
with end-to-end encryption that lets the customer's customer authorize
access from inside the customer's product UI. Reverse-OAuth equivalent.

Onboarding timing: "under 5 minutes" for first destination. **Fastest
first-aha of any product in this scan.**

Adjacent gap: unidirectional (warehouse → SaaS). Census's verb is
`destination`, not `connection`. WormBase's needs are bidirectional.

### 4.5 dbt Cloud — project + warehouse as the front door

Verb pattern: New project → Account Settings → Add new connection
(wizard in a new tab) → Test Connection → Save → choose compute
connection from dropdown.

Innovation surface: **the IDE is the onboarding** — once a warehouse is
connected, the user is dropped into a working SQL/code IDE. Aha moment
is "first model compiled and run."

Adjacent gap: transformation-first. dbt Cloud assumes you already have
a connected warehouse; it doesn't ingest sources. Composes with Fivetran
upstream, not as a replacement.

### 4.6 Synthesis: the common shape, the missing piece

All five adjacent products converge on a **connector-catalog → wizard →
test connection → first sync** sequence at the source layer. **None of
them implement a single verb that spans data + channels + governance +
agents.** The closest is Atlan (domains + connectors in one product),
but Atlan has no channel layer; its onboarding is 4-6 weeks because the
governance baseline is human-driven.

OpenClaw's `@connect` verb pattern, applied at the source layer, gives
Fivetran's catalog the verb-uniformity of OpenClaw. Applied at the
governance layer, it gives Atlan's domain creation the same primitive.
Applied at the agent-grant layer, it generalizes to roles. **The
institutional opportunity is: one verb (`@onboard <thing>`) where
`<thing>` ranges over the full institutional object set.**

---

## 5. What "institutional-OpenClaw" looks like

UX and behavioral level. Architecture follows in
[customer-journey.md](../product/customer-journey.md) and the
onboarding proposal.

### 5.1 The single verb

`@onboard <object>` is the institutional entry point. The verb is
stable; the noun ranges over the institutional ontology:

- `@onboard connector <kind>` — a data source
- `@onboard channel <platform>` — a chat platform
- `@onboard domain <pack-or-name>` — a business domain
- `@onboard person <email>` — a teammate
- `@onboard role <facet> <grant>` — a grant
- `@onboard policy <template>` — a governance rule
- `@onboard agent <skill>` — an agent skill pack
- `@onboard subscription <tier>` — a plan or seat

Each compiles to the right wizard / form / OAuth flow based on the
noun. The user's mental model collapses to "onboard is the verb for
connecting any institutional object."

### 5.2 The five-tier sequence

1. **Tier 0 — landing.** "Connect to <chat platform>" button. The first
   connection is a chat platform — not a data source — because the worm
   needs a surface to talk back from. Default local lake plays the
   bronze/silver/gold story until external sources land.
2. **Tier 1 — install + Person creation.** OAuth → tenant → installer
   Person → install grant. Sub-60-second SLA. Status badge: `connecting
   → connected → verified`.
3. **Tier 2 — governance baseline.** Domain pack picker (SaaS /
   marketplace / fintech), co-admin invites, classification defaults.
4. **Tier 3 — first source + first KPI.** Connector catalog opens; admin
   picks one (or accepts the default local lake). Connector wizard runs:
   credential → discover → profile → classify → sample. Worm proposes a
   first KPI off the first table.
5. **Aha moment.** Worm has posted in a channel, bronze cascade visible,
   KPI proposed, ramp first-moved. ≤60s total cumulative.

### 5.3 Status-honest catalogs at every layer

Every catalog the user browses (connectors, channels, domain packs,
policy templates, agent skill packs) carries the same three-state badge:
`production` / `preview` / `coming_soon`, plus a fourth
`requires_plan_upgrade` for SaaS billing.

Each catalog entry declares its capability set as data. The UI renders
only valid actions, per the OpenClaw `capability` pattern.

### 5.4 `@status` and `@logs` as universal verbs

Every institutional object answers to `@status` (live probe + structured
result `{works, degraded, failed}`) and `@logs` (ledger-replay view).
Operators investigate failures the same way regardless of what's broken.

### 5.5 Multi-stakeholder approval as a first-class state machine

Every onboarding step that needs approval pauses and routes to the right
reviewer. The state machine has three states: `pending_review → approved
→ applied` (or `→ rejected`). The state is a ledger entry; the reviewer
is a Person; the approval is a grant-scoped write.

OpenClaw has nothing like this. It's the largest UX surface
institutional onboarding adds.

### 5.6 Plugins are domain packs + policy templates + connector kinds + channel adapters

Generalize the OpenClaw plugin model from one extension surface to four
or five. The institutional plugin ecosystem ships:

- Connector kinds (already in `wormbase_connectors`)
- Channel adapters (already in `wormbase_channel_adapters`)
- Domain packs (new)
- Policy templates (new)
- Agent skill packs (already exists implicitly as the named-actor worms)

Each surface is a registry. New entries are additive. The catalog UI
reads from all five registries.

---

## What this synthesis is not

This document is a UX/behavioral characterization. It does not specify:

- Specific implementation phases or task decomposition (see the
  in-flight onboarding proposal).
- Specific dashboard component shapes (see
  [customer-journey.md](../product/customer-journey.md)).
- Specific ledger entry kinds added for any institutional verb (see the
  schema-evolution doctrine).

---

## Cross-references

- [ADR-0001: Listener-shaped channel adapter](../decisions/ADR-0001-listener-shaped-channel-adapter.md)
- [channel-adapters.md](../channel-adapters.md) — adapter contract and
  wiring.
- [customer-journey.md](../product/customer-journey.md) — end-to-end
  customer journey through WormBase including OpenClaw-integrated
  onboarding.
- [institutional-onboarding-proposal.md](../product/institutional-onboarding-proposal.md)
  — the architectural proposal that builds on this research.
