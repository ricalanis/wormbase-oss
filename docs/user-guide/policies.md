# `/policies` — User guide

## What it does

The Policies tab lists every governance policy in the tenant — a
**rule-as-code** attached to a domain × classification × resource scope.
Each row carries:

- policy name + rule-as-code summary
- applies-to scope (domain / classification / resource)
- maintainer Person
- effect (block / mask / log / allow)
- last fired (timestamp + count)
- "Test against ledger" — picks a sample of recent entries and shows
  what the policy would have decided

Polls `/api/governance/policy` every 10 seconds so admins see
classification changes ratify into the live ledger without a page
reload.

This is the admin's weekly surface.

## First action

Pick a domain pack at install — pre-seeded policies arrive automatically:

1. SaaS pack pre-seeds: PII redaction policy on `confidential`+
   classifications, retention policy (90 days for chat, 7 years for
   financials), masking policy on KPI exports.
2. Open `/policies`. The seeded policies render as rows.
3. Click any row → drawer opens with the rule-as-code, the gate
   implementation reference, and recent fire history.

To author a policy:

1. Click **New policy** in the header.
2. Pick scope: domain (e.g. `finance`), classification (e.g. `pii`),
   or specific resource.
3. Pick effect: `block` / `mask` / `log` / `allow`.
4. Write the rule-as-code (Python expression, evaluated against the
   ledger entry being decided). Example:
   ```python
   ledger_entry["payload"].get("contains_email") and \
       ledger_entry["classification"] == "pii"
   ```
5. Submit. Writes `emit_policy_proposed`. Admins confirm via
   `emit_policy_confirmed`; from then on the gate fires this policy
   against every matching entry.

## Advanced

- **Test against ledger** — open any policy → **Test**. Picks a sample
  of 100 recent entries and shows what the policy decided. Useful to
  validate before promoting to confirmed.
- **Disable a policy** — owner-only. Writes `emit_policy_disabled`. The
  policy stays in the table for audit but stops firing.
- **Audit a policy fire** — every fire writes `emit_policy_fired
  {policy_id, target_entry_id, decision, ts}`. Click the policy's
  fire-history chip to open `/trace?policy_id=<id>` filtered to fires.
- **Policy templates library** — admin-only. `/policies/templates` lists
  pre-baked policy patterns (retention, masking, access, throttling).
  Click any to instantiate against your scope.
- **Per-Person policy fire log** — open `/people/{id}` → `Policy fires`
  section shows policies that have applied to actions this Person
  initiated. Useful for "what did the gate prevent this Person from
  doing?" audits.

## Effect semantics

| Effect | What it does | Ledger writes |
|---|---|---|
| `block` | Refuses the write; gate emits a denial entry | `emit_policy_fired {decision: block}` + `emit_<original_kind>_blocked` |
| `mask` | Allows the write but redacts the payload at read time | `emit_policy_fired {decision: mask}`; original entry stays |
| `log` | Allows the write; just logs the fire | `emit_policy_fired {decision: log}`; original entry stays |
| `allow` | No-op; useful for explicit allow-list policies | `emit_policy_fired {decision: allow}` |

## Behind the scenes

Reads from `projection_policies` + `projection_policy_fires`, folds of:

```
emit_policy_proposed       (admin form or pack template instantiation)
emit_policy_confirmed      (admin click)
emit_policy_disabled       (owner click)
emit_policy_archived
emit_policy_fired          (one per gate fire — write or read)
```

The policy engine lives at
`packages/governance/src/wormbase_governance/policy_engine.py`. On every
ledger write, the engine queries `projection_policies` for matching
scope, evaluates the rule-as-code against the entry, and writes a
`emit_policy_fired` regardless of decision (so audits are complete).
Block decisions short-circuit the original write; mask decisions wrap
the payload renderer at read time.

The rule-as-code language is sandboxed Python — no I/O, no imports
beyond a stdlib whitelist, 50ms execution cap per evaluation.

## Five concepts — Policy

The Policies tab surfaces the **Policy** concept from the
five-concept governance model:

- Person → `/people`
- Domain → `/domains`
- Resource → `/sources`, `/kpis`, etc.
- Classification — enum
- **Policy** — this tab

The principle: **any rule that cannot be expressed as a gate
implementation is out of scope** — it belongs in a policy document
elsewhere. Governance is code, not a binder.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Policy fire count flat | Policy scope mismatched to actual entries | Open **Test against ledger**; verify scope predicates |
| Test against ledger times out | Sample size too large or rule expensive | Reduce sample size in the test panel |
| Policy fires but writes still go through | Effect is `log`, not `block` | Change effect to `block`; reconfirm |
| Rule-as-code rejects on save | Sandboxed Python failed validation | Check imports / execution cap; rewrite per the syntax doc |
| Mask decision still leaks payload | Renderer not policy-aware | File a bug — every read renderer must call `applyPolicyMasks` |
