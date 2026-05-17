# `/domains` — User guide

## What it does

The Domains tab is the **per-domain governance lens**. A grid of cards,
one per domain (e.g. sales, product, finance, ops, customer success).
Each card carries:

- domain name + classification default (color-coded: green public →
  red regulated)
- owner Person (drillthrough to `/people/{id}`; reassignable via
  drag-and-drop from the people roster)
- contributor chips (one per Person with `domain.contributor`)
- resources owned by the domain (sources, KPIs, processes — count
  badges)
- recent activity (the last 5 ledger entries scoped to this domain)
- domain data product roster with freshness indicators (green ≤ 7d,
  amber ≤ 30d, red older)

Polls `/api/governance/domain` every 10 seconds so admins watch the
worm "ratify" governance changes live.

This is the admin's daily surface.

## First action

Pick a domain pack at install (Tier 2 of onboarding):

1. During Tier 2, the domain pack picker writes `emit_domain_registered`
   for each pack-default domain (sales, product, finance, ops, ...) with
   the installer as owner.
2. After install, `/domains` shows the seeded grid. Each card has the
   installer as owner; admins re-assign as people roster fills out.

To assign a domain owner:

1. On any card, click the owner avatar → **Reassign**. Picker opens
   showing every Person in the tenant.
2. Pick the new owner. Writes
   `emit_domain_role_assigned {domain_id, person_id, role: owner,
   granted_by: <you>}` AND `emit_domain_role_revoked` for the
   previous owner.
3. The card updates within one polling cycle.

To add a contributor:

1. On any card, click the **+ Contributor** chip. Picker opens.
2. Pick a Person. Writes
   `emit_domain_role_assigned {role: contributor}`.
3. The Person can now edit domain artifacts (KPIs, processes, sources)
   without owning them.

## Advanced

- **Drag-and-drop a Person** from the roster onto a card to add them as
  contributor. Same write path.
- **Edit classification default** — owner-only. Click the
  classification badge → picker. Writes `emit_classification_default_changed`.
  Affects every new resource registered in this domain.
- **Drill into a resource** — click any resource count badge on a card.
  Filtered list opens (e.g. all KPIs in `finance`).
- **Domain data product roster** — each card shows the artifacts in
  this domain with freshness badges. Click a stale (red) badge to
  re-run the artifact (admin-only).
- **Domain audit log** — click the **History** chip on any card. Opens
  `/trace` filtered to `domain_id=<this>`.
- **Archive a domain** — admin-only, confirmable. Writes
  `emit_domain_archived`. Resources in the domain become unowned (must
  be reassigned). Useful when reorganizing.

## Behind the scenes

Reads from `projection_domains` + `projection_domain_resources` +
`projection_domain_role_grants`, folds of:

```
emit_domain_registered          (Tier 2 domain pack picker)
emit_domain_archived            (admin click)
emit_domain_role_assigned       (owner / contributor grants)
emit_domain_role_revoked
emit_classification_default_changed  (per-domain default)
emit_resource_classified        (any resource attaches to a domain)
```

The domain-pack templates live at
`packages/governance/src/wormbase_governance/packs/{saas,marketplace,fintech,custom}.yml`.
Each pack pre-seeds: domains, default classifications, common policy
templates. Customer starts from a working baseline, not a blank canvas.

Resource ownership at the domain layer is **lazy** — when the worm
processes a new source, KPI, or process, it auto-proposes the owning
domain via the classification + ontology lookup. Admins confirm via the
domain card's drill-in.

## Five concepts of governance

The Domains tab surfaces the **Domain** concept from the five-concept
governance model:

- **Person** `{id, name, email, role}` — `/people`
- **Domain** `{id, name, default_classification, owner_person}` — this tab
- **Resource** `{id, type, identifier, domain, owner_person, classification}` — `/sources`, `/kpis`, etc.
- **Classification** — enum {public, internal, confidential, pii, regulated}
- **Policy** `{id, name, applies_to, rule, gate_impl}` — `/policies`

Every ledger entry is implicitly tagged with `domain_id` and
`classification` via the resource it touches. Governance views are
aggregations over the ledger — no separate database, no portal, no
workflow engine. **Governance is code, not a binder.**

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Card grid empty after install | Tier 2 domain pack picker skipped | Re-run via `/onboarding/tier2`; or write `emit_domain_registered` via API |
| Owner avatar shows "Unknown" | Owner Person archived | Reassign to an active Person |
| Classification badge red but no resources | Pack default applied; no resources yet | Connect a source to surface real data |
| Drag-drop silent | Browser doesn't support HTML5 drag events | Use the `+ Contributor` chip instead |
| Recent activity empty | Domain has no ledger entries yet | Idle domain; surface activity by connecting a source or proposing a KPI |
