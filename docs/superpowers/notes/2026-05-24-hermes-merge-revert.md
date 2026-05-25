# 2026-05-24 — Hermes merge + revert (post-mortem)

> What's on `main` after this session:
> - **OpenClaw remains the chat gateway.** No code change to the runtime path.
> - **GCP + Coolify deploy infrastructure is in place** (provisioned + documented). Independent of gateway choice.
> - **`feat/hermes-migration` branch still exists on `origin`** — unmerged. Two revert commits on main record that the merge was attempted + rolled back.
>
> Future maintainers: read this before re-attempting the merge.

---

## Sequence of events (commit timeline)

```
1c2a8c8  Revert "Merge feat/hermes-migration..."  ← main HEAD after this session
63214ec  Revert "refactor(infra): rename OPENCLAW_* → HERMES_*..."
1f6f568  refactor(infra): rename OPENCLAW_* → HERMES_*... (reverted)
aea9480  Merge feat/hermes-migration: Hermes replaces OpenClaw (Phases 1-4) (reverted)
6cea754  docs: GCP + Coolify Cloud deploy runbook   ← state main returned to (logically)
da4e682  chore(compose): parameterize WORMBASE_LEDGER_DSN
bc8ef4c  feat(agent-driven-loop): plumb L1 source-candidate discovery
```

The two `Revert "..."` commits net out the merge + the followup rename, leaving the working tree byte-equivalent to `6cea754` (the state before the Hermes work landed).

## What was attempted

The `feat/hermes-migration` branch ships a 4-phase migration:

| Phase | Commit | Scope |
|---|---|---|
| 1 | `fa65f35` | Hermes wire-tap HTTP consumer in channel-adapter (additive) |
| 2 | `3088414` | Gateway selector via compose profiles + Makefile |
| 3 | `9fb57ce` | Gateway parity contract tests |
| 4 | `d44ea97` | **OpenClaw retirement** — deletes `infra/openclaw/`, `openclaw_log_tail.py`, the silent-mode plugin |

The full branch was merged (`aea9480`), followed by a Sprint 1 cleanup that renamed `OPENCLAW_*` env vars + Makefile targets to `HERMES_*` (`1f6f568`).

## Why it was reverted

Two operational blockers — both pre-existing in the branch, documented in
`docs/superpowers/notes/2026-05-21-openclaw-retirement.md` §5 ("Known blockers
carried into Phase 5 / live verification"):

1. **H1 NO-GO (Hermes inbound coverage gap).** Hermes v0.11.0's `agent:start`
   hook fires only on agent-engaged messages (mentions / DMs / target
   channels). The WormBase lurker contract requires ingest of *every* inbound
   regardless of agent engagement. Without an upstream Hermes hook that fires
   on every inbound, the `chat_received` invariant cannot be maintained under
   pure-Hermes mode. The structural parity tests pass; the live behavioural
   verification is what's missing.

2. **WhatsApp inbound under pure-Hermes is unwired.** The channel-adapter's
   `whatsapp_envelope_watcher` reads OpenClaw's daily `web-inbound` log file
   to surface WhatsApp messages. With OpenClaw retired, the log file
   disappears and the watcher has nothing to consume. The retirement notes
   acknowledge this:
   > "The watcher still listens to the OpenClaw daily log when one is
   > mounted — operators running an *external* OpenClaw alongside Hermes
   > during a hybrid window continue to get full WhatsApp inbound coverage."
   
   In other words, Phase 4 implicitly assumes a hybrid OpenClaw+Hermes
   deployment for WhatsApp tenants — but Phase 4 also deletes the means to
   run OpenClaw. Self-contradictory under pure-Hermes.

The Altis design partner (kickoff Monday 2026-05-25) is a WhatsApp-primary
tenant. Shipping under either blocker breaks the customer demo.

## What stays on main from this session (unrelated to Hermes)

These commits are **NOT reverted** — they're independent infrastructure work:

| Commit | Stays | Why it's safe |
|---|---|---|
| `bc8ef4c` | Yes | L1 source-candidate plumbing — env-var-gated, OpenClaw-compatible |
| `da4e682` | Yes | `WORMBASE_LEDGER_DSN` parameterization — overridable env var with local-dev default; no behavior change for existing setups |
| `6cea754` | Yes | GCP + Coolify Cloud deploy runbook — pure docs; works against OpenClaw |

The GCP VM (`wormbase-prod`, `35.238.203.171`), Cloud SQL Postgres
(`wormbase-prod-db`, private IP `10.84.0.3`), GCS bucket, Secret Manager,
firewall rules, and managed Coolify integration **all still exist** on the
Google Cloud side. They're gateway-agnostic.

## Re-merge checklist (when revisiting Hermes)

Before merging `feat/hermes-migration` again, verify:

- [ ] **Hermes inbound hook coverage:** confirm `agent:start` (or a new
      Hermes hook) fires on *every* inbound message, not just agent-engaged
      ones. The H1 spike notes
      (`docs/superpowers/notes/2026-04-27-hermes-h1-spike.md`) are the
      original source. Re-run the spike against the current Hermes version.

- [ ] **WhatsApp ingest path under pure-Hermes:** decide on one of:
  - (a) Hybrid deployment — keep an OpenClaw container alongside Hermes
    solely for the WhatsApp daily-log file. Document the deploy shape.
  - (b) Direct Baileys integration in channel-adapter — bypass the gateway
    layer for WhatsApp ingress. Larger code change.
  - (c) Wait for Hermes to ship a WhatsApp adapter with equivalent inbound
    coverage to OpenClaw + Baileys.

- [ ] **Live verification run:** before merging, exercise the install-arc
      7-beat scenario (`tests/integration/test_full_install_arc_live.py` or
      equivalent) against a live Hermes deployment. Compare ledger hashes
      against the OpenClaw baseline. Spec §6 Phase 3.

- [ ] **WhatsApp shadow throttle status:** the test SIM was under a
      soft-throttle as of 2026-05-21 (see `docs/known_issues.md`). Pair a
      fresh SIM if the throttle hasn't cleared, OR test on Slack-only.

## Sequencing for an easy re-merge

When the re-merge happens, follow this order to minimise conflict surface:

1. **Land structural changes on main first** (small, reviewable commits):
   - Add `HermesEventConsumer` alongside `OpenClawLogTailer` (Phase 1 alone).
   - Add the gateway-selector compose profile (Phase 2 alone).
   - Add the parity tests (Phase 3 alone).
   - Both gateways are present + selectable. **No retirement yet.**

2. **Soak time** (≥1 week of pure-Hermes operation on a non-customer-facing
   tenant) to surface H1 + WhatsApp-ingress gaps live.

3. **Retire OpenClaw** (Phase 4) only after Soak passes. By then:
   - The WhatsApp inbound path under pure-Hermes is verified working.
   - The `chat_received` lurker invariant has been observed live.
   - Customer-facing tenants have been migrated tenant-by-tenant, with
     fallback documented per tenant.

The branch `feat/hermes-migration` currently bundles all four phases as one
merge. Re-merging via cherry-pick (P1, then P2, then P3, then later P4 as a
separate PR) gives the soak window and the gradual rollout that this attempt
skipped.

## What "easy to maintain" means now

- The `feat/hermes-migration` branch on `origin` is the **final-state target**
  — preserved as-is so a future cherry-pick / re-merge has a known base.
- Main on `1c2a8c8` is **OpenClaw stable**. Customer-facing.
- The two revert commits (`63214ec`, `1c2a8c8`) preserve git history of the
  attempt. Anyone doing `git log` on main sees both the merge and the revert,
  so the decision is auditable.
- This post-mortem (`2026-05-24-hermes-merge-revert.md`) lives in
  `docs/superpowers/notes/` next to the original retirement notes, so the
  context for the next attempt is one `grep -r hermes docs/` away.

## Cross-references

- Migration spec: `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md`
- H1 spike note: `docs/superpowers/notes/2026-04-27-hermes-h1-spike.md`
- Retirement notes (from the merged-then-reverted Phase 4): see git history at `aea9480^{commit}:docs/superpowers/notes/2026-05-21-openclaw-retirement.md`
- WhatsApp pairing procedure (still under `infra/openclaw/` after revert): `infra/openclaw/WHATSAPP_PAIRING.md`
- GCP + Coolify deploy runbook (unaffected): `docs/superpowers/runbooks/gcp-coolify-deploy.md`
- Altis kickoff runbook (unaffected, but tenant-switch §2 references OpenClaw entrypoint): `docs/superpowers/runbooks/2026-05-25-altis-kickoff-runbook.md`
