"""Chaos / failure-injection tests (W6.A3).

Each test in this directory names a failure mode AND the invariant the
system must preserve under that failure. Every test asserts:

    (a) graceful degradation OR retry,
    (b) honest UX state (an error code or projection rendered to the user),
    (c) no half-state writes (the ledger delta after the failure matches
        what the spec promises),
    (d) rate-limit / budget counters are not corrupted.

Tests use ``unittest.mock`` / ``pytest-mock`` and patch at the highest
reasonable level — the dependency's client surface, not the wrapped
function. Each test exercises the actual production code path; no test
silently swallows an error.

The shared marker is ``chaos`` so you can run only this category via::

    pytest -m chaos
"""
