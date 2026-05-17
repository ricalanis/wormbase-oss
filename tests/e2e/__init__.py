"""W6.A6 — full-stack end-to-end tests.

Each test in this directory drives the whole stack (worm-core +
channel-adapter + dashboard + sim-harness + the wire) and asserts an
invariant that only an integration test can witness. Heavy-stack tests
gate on ``WORMBASE_HARNESS_UP=1`` (`make up` brought the dev compose
up); the determinism backstop variants gate on nothing — they replay
the canonical JSONL fixture through the in-process channel-adapter
and never touch a real platform.

Per CLAUDE.md: the only acceptable determinism backstop is wire-replay
through the live channel-adapter. No flow-bypass shortcuts. Tests in
this directory honor that — every assertion lands on a ledger entry
produced by the same PEVR primitive a production write would use.
"""
