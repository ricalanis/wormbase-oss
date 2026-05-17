# Visual regression baselines

80 PNG snapshots — one per `(tab, role, state)` cell — checked into git
under `__snapshots__/`. The Playwright suite at `visual.spec.ts` diffs
each rendered page against its baseline at a 5% per-pixel tolerance.

## Canonical-seed dependency (W7.A6)

Baselines are captured against the **W7.A1 rich seed** of the
`baseworm` tenant. That seed produces:

- 4 confirmed personas (Alice / Bob / Carol / Dana)
- Carol granted `domain.owner(retention) + resource.maintainer(churn_rate)`
- Confirmed `churn_rate` KPI in domain `retention`
- 2 decisions, 1 process map (`customer_recovery_flow`), 1 data product
- Default local lake provisioned via `make tutorial`

Without this seed, every tab redirects to `/onboarding` (no `Install`
row) and every baseline collapses to the same image — defeating the
diff. **Always regenerate against the rich seed.**

If `SLACK_BOT_TOKEN_BASEWORM` is set in `.env`, the seed runs with
`--install-from-env` so the dashboard renders its post-onboarding
shell (the default state for the demo arc). Without the token, the
seed runs warmup-only and baselines capture the
onboarding-redirect chrome — surface that in the commit message.

## How to regenerate

One command:

```bash
make visual-baselines
```

This is idempotent — running it twice on a stable stack produces the
same baselines.

The target wraps:

1. `docker compose run --rm sim-harness wormbase demo seed --reset-first --rich` (with `--install-from-env` if a token is in `.env`)
2. 12s sleep for the projection runner
3. `pnpm exec playwright test tests/visual/ --update-snapshots` against `http://localhost:3000`
4. A no-update verification run (must report 0 pixel-diffs)

Prerequisites:

- Stack is up (`make up` or `make tutorial`)
- `pnpm install` has run
- `.env` is present (copy from `.env.example`)

## When to regenerate

Regenerate after **any intentional UI change** that shifts:

- Selectors or `data-testid` attributes used by the suite
- Layout (flex / grid / spacing changes)
- Copy in nav, header, or page titles
- Iconography or design tokens
- Empty-state copy or art

Do **not** regenerate to silence a failing diff caused by a regression
— investigate first. The whole point of the baselines is to catch
regressions, so a passing CI after `--update-snapshots` is only useful
if the diff was reviewed and intended.

## Reviewing the diff

After regeneration:

```bash
git diff --stat apps/dashboard/tests/visual/__snapshots__/
```

Expect:

- **Touched UI surface** → that tab's 4 role × 2 state cells change
- **Cross-cutting chrome change** (header, nav) → most or all 80 cells change
- **Random isolated diffs** → likely a flake; rerun `make visual-baselines` once

If a baseline changes for a non-data, non-UI reason (mid-render flake,
fonts not yet loaded, etc.), discard with `git checkout --` and rerun.

## Files

- `visual.spec.ts` — the test, 10 tabs × 4 roles × 2 states = 80 tests
- `__snapshots__/<tab>--<role>--<state>.png` — checked-in baselines
- This `README.md` — workflow + when-to-regenerate guidance
