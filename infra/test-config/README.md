# Test-only service configuration

This directory holds configuration files mounted into the containers
defined by `infra/docker-compose.test.yml`. Nothing here ever ships
to production or to the dev stack.

## Contents

- `slack-mock.json` (TBD) — Mockoon spec for the mock Slack Web API
  served on `localhost:18790` during integration tests. Wired into
  `slack-mock` service when L5 tests need real Slack-side behavior.
- `worm-core-test.env` (TBD) — env overrides for `worm-core-test`
  beyond what's already in `docker-compose.test.yml`.

## Conventions

- All ports here are 1xxxx-range to stay clear of the dev compose
  (5432 -> 5433, 18789 -> 18790, etc.).
- No secrets ever live here — tests use deterministic stub tokens.
- This directory is bind-mounted read-only into the relevant services.
