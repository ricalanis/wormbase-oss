# `/settings` — User guide

## What it does

The Settings tab is **admin-only** tenant configuration. Sub-pages:

- `/settings/setup-mode` — switch between wizard and bot setup
- `/settings/tokens` — issue / revoke MCP bearer tokens per Person
- `/settings/research` — autoresearch loop tuning (cadence, thresholds)
- `/settings/mcp` — MCP rate-limit budgets per Person × tool
- `/settings/notifications` — per-Person notification preferences
- `/settings/inference` — inference router (remote vs own; model
  selection)
- `/settings/channels` — legacy redirect to `/channels`

Daily for admins during onboarding; weekly thereafter.

## First action

Switch setup mode mid-onboarding:

1. After the Tier 0 install, the post-install banner on `/dashboard`
   shows the wizard-vs-bot fork. If you initially picked wizard but
   want the worm to DM you the rest of the questions:
   1. Open `/settings/setup-mode`.
   2. Click **Switch to bot mode**. Writes
      `emit_setup_mode_chosen {mode: bot}`. The
      `SetupConversationLoop` in worm-core picks up within 30s and DMs
      you the next pending question.
2. To go the other way (bot → wizard), the same picker writes
   `emit_setup_mode_chosen {mode: wizard}`. The dashboard's onboarding
   redirect resumes routing to `/onboarding/tier2` and `/onboarding/tier3`.

## Advanced (per sub-page)

### `/settings/tokens`

- **Issue token** — pick a Person, scope (read-only / read-write),
  expiry (7 days / 30 days / never). Writes `emit_token_issued`. Token
  is generated once; copy it now or revoke and reissue.
- **Revoke token** — click any active token → **Revoke**. Writes
  `emit_token_revoked`. Token rejected on next call.
- See the [`/mcp`](mcp.md) user guide for how clients consume tokens.

### `/settings/research`

- **Cadence** — how often the autoresearch loop runs per Person. Default:
  30s in dev, 6h in prod.
- **Thresholds** — the keep/discard delta threshold (default: keep if
  observed delta ≥ 80% of expected delta).
- **Real execution allowlist** — by default experiments run as **mocked
  execution + ledger writes**. Admins can enable real execution for
  safe classes (cache tunings, query reformulations) per position.
- See [`/research`](research.md) for the full loop semantics.

### `/settings/mcp`

- **Per-(tenant, Person, tool) budgets** — N calls / hour, N calls /
  day. Limit exceeded → gate writes `emit_mcp_call_rate_limited`; tool
  returns 429.
- **Default budgets** — 1000 calls / hour, 10000 calls / day per Person
  per tool.
- **Audit visibility caps** — by default, observers see `<call denied>`
  not the full call args when the call's classification was `pii` /
  `regulated`. Admins can override per-Person but it's logged.

### `/settings/notifications`

- **Insight class subscriptions** — per Person. Choose which classes
  surface in `/activity`'s insights panel (recurring_question /
  decision_imminent / kpi_drift / process_deviation / source_drift).
- **Channel preference** — chat (worm DM) vs email (SSO).
- **Frequency** — immediate / daily digest / weekly digest.

### `/settings/inference`

- **Remote model** — Kimi K2.6 default. Swap via dropdown if customer
  has a contracted alternative (e.g. Claude Opus, GPT-4o).
- **Own model** — Gemma 4 (E4B) default. Customer can override per
  task class (embeddings, classification, summarization).
- **Per-tenant routing weight** — what % of commodity calls route to
  own-inference vs remote. Default 100% own.
- See `docs/architecture-overview.md` § 9 for the architectural split.

## Behind the scenes

Reads from per-feature projection tables (`projection_tokens`,
`projection_research_config`, etc.), folds of:

```
emit_setup_mode_chosen     (mode: wizard | bot)
emit_token_issued
emit_token_revoked
emit_research_config_updated
emit_mcp_budget_updated
emit_notification_preferences_updated
emit_inference_routing_updated
```

The setup-mode switcher is admin-only by `lib/role-nav.ts` — only
`tenancy.admin` sees the page; members + observers get a 403.

Tokens are stored salted-hashed in `projection_tokens`; the plaintext is
shown once at issue time and never re-displayed.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Setup-mode picker silent | `WORMBASE_LEDGER_API_TOKEN` mismatch | Re-set; restart |
| Switch to bot mode but no DM | `SetupConversationLoop` not running, or no chat platform connected | `make worm-logs \| grep SetupConversationLoop`; ensure Slack `Install` row exists |
| Token works for one query then 401s | Token had short expiry | Reissue with longer expiry |
| Research cadence change ignored | Loop reads config at boot only | `make worm-restart` after config changes |
| MCP budget update silent | Rate-limit gate caches budgets for 60s | Wait one minute; or restart worm-core |
