"""Property-based tests for WormBase (Wave-6 W6.A1).

Hypothesis-driven invariant checks over the substrate. Each test names a
named invariant in its docstring; tests that merely "exercise" code without
verifying a property are off-spec for this directory.

Categories:
    - Hash-chain determinism + integrity
    - Payload roundtrip stability across every kind in KIND_REGISTRY
    - Projection determinism under shuffled checkpoint sequencing
    - Reactivity predicate algebra (associative / commutative / involutive /
      distributive / de Morgan / identity)
    - Reactivity DailyBudget rollover across midnight UTC, DST, leap seconds,
      UUID v4 vs v7 owners

CI knobs are set in ``conftest.py`` (max_examples=200, derandomize=True).
"""

from __future__ import annotations
