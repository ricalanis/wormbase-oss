# `/people` — User guide

## What it does

The People tab is the production team-management surface. Three sections in
one page:

1. **Roster** — every active Person in the tenant. Name, position, tenancy
   role, domain count, resource count, status, identity icons (one per
   connected platform).
2. **Pending proposals** — Persons the worm has auto-discovered from chatter
   but no admin has confirmed. Bulk-confirm in one click.
3. **Identity merge** — admin-only. Merge two Persons into one (when the
   worm proposes a duplicate from a different platform), or split a Person
   that turned out to be two humans sharing an email.

Daily surface for tenancy admins. Members and observers see a read-only
view filtered by their domain access.

## First action

Confirm the worm's auto-discovered teammates:

1. Open `/people`. The **Pending proposals** drawer opens automatically if
   any are waiting.
2. Each proposal carries the platform identity the worm saw (e.g.
   `@bob` on Slack), the inferred name from `users.info`, the inferred
   email if the platform exposes it, and a confidence score.
3. Check the boxes for everyone who's actually a teammate. Click **Confirm
   N**. One click writes N `emit_person_confirmed` ledger entries in a
   single API call.
4. For proposals that are not real teammates (bots, archived accounts, etc.)
   click **Reject**. Writes `emit_person_archived` with reason
   `not_a_teammate`.

To invite a new admin who isn't yet on Slack:

1. Click **Invite by email** in the header.
2. Enter email + name + position. Submit. Writes `emit_person_proposed`
   (proposed by you) + `emit_role_assigned {role: tenancy.admin}`. The
   invitee receives an SSO email link; on first sign-in their Person row
   transitions to `status=active`.

## Advanced

- **Click a Person row** to open the `PersonDetailDrawer`. Three sections:
  identities (one per platform), role grants (tenancy / domain / resource —
  flat join), audit log (every grant change in chronological order, sourced
  from the ledger).
- **Edit role grants** — click any role row. Tenancy roles toggle directly;
  domain + resource grants open a picker. Each change writes the matching
  `emit_role_assigned` / `emit_role_revoked` / `emit_domain_role_assigned` /
  `emit_resource_role_assigned` entry.
- **Identity merge** — open the IdentityMergePanel. Pick two Persons. The
  worm warns if positions or domains conflict. Confirm to write
  `emit_identity_linked` for each `PersonIdentity` row migrated to the
  surviving `person_id` and `emit_person_archived` for the loser.
- **Identity split** — open the same panel; pick a Person; select which
  `PersonIdentity` rows go to the new Person. Writes
  `emit_identity_unlinked` for each migrated identity and
  `emit_person_proposed` for the new Person.
- **Position assignment** — auto-proposed by the worm from chatter signal
  (whoever asks "what's our Q3 net revenue?" four times this quarter gets
  `position=CFO` proposed). Admin clicks **Confirm position** in the
  drawer; writes `emit_position_confirmed`.

## Behind the scenes

Reads from `projection_people`, a fold of these ledger entries:

```
emit_person_proposed       (auto-discovery or invite)
emit_person_confirmed      (admin click — bulk or single)
emit_person_archived       (soft delete)
emit_role_assigned         (tenancy facet)
emit_role_revoked
emit_domain_role_assigned  (domain facet)
emit_resource_role_assigned (resource facet)
emit_identity_linked       (multi-platform merge)
emit_identity_unlinked     (split)
emit_position_proposed
emit_position_confirmed
```

Bulk confirm uses `bulk_confirm_persons` orchestrator on worm-core — one
HTTP request, N ledger entries, all written in one transaction with one
PEVR chain root.

The auto-discovery loop runs in `apps/worm-core/src/wormbase_core/identity_discovery.py`
on a 30-second cycle. Every unknown `platform_user_id` in a wire event
triggers `emit_person_proposed`; the loop calls
`ChannelAdapter.list_workspace_members` to enrich the proposal with email
+ display name + avatar.

The PersonDetailDrawer's role grants render via the same `useNavForRole`
join the dashboard chrome uses — no duplication.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Pending proposals never appear | Identity discovery loop not running | `make worm-restart`; check logs for `identity_discovery` |
| Invite by email reports 401 | `WORMBASE_LEDGER_API_TOKEN` mismatch between dashboard + worm-core | Set both to the same value; restart |
| Identity merge silent | UI state desync | Hard refresh; the merge writes are atomic at the DB layer |
| Person row missing position | Worm hasn't seen enough chatter signal | Wait 24h, or set position manually via drawer |
| Bulk confirm partial success | One Person's email collided with an existing active Person | Open the IdentityMergePanel; merge instead of confirm |
