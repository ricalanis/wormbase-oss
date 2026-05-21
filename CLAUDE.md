# CLAUDE.md — workspace-level notes for Claude Code

## Test invocation

`pytest packages/` from the workspace root **does not work** — each package
under `packages/*` has its own `tests/conftest.py`, and pytest's module-name
resolution collides on the shared `tests.conftest` name (O-B6 contract,
verified by `tests/contract/test_pytest_invocation.py`).

Use one of the supported per-package patterns instead:

- `make test-all` — loops pytest per package + the workspace `tests/`
  directory; the canonical "run everything" entry point.
- `cd packages/<name> && uv run pytest tests/` — run a single package's
  suite from inside that package.
- `uv run --directory packages/<name> pytest tests/` — same, but without
  changing the shell's CWD.

Apps follow the same pattern (`cd apps/<name> && uv run pytest tests/`).

The top-level `tests/` directory (integration / contract / e2e / demo)
uses the workspace venv and is runnable from root:
`uv run pytest tests/integration/...`.

## Smoke / CI tests

- `make qa-fast` — L1 unit + L3 contract + L1/L2 TS + silent-mode coverage
  guard. Pre-commit confidence check.
- `make qa` — adds service + integration layers. CI / pre-merge.
- `make silent-mode-coverage` — standalone grep guard for the
  `WORMBASE_SILENT_MODE` egress contract (see DEVELOPERS.md § Silent mode).
