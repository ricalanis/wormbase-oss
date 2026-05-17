"""Pytest + Hypothesis settings for the property-based test suite.

Wave-6 W6.A1 acceptance: ``max_examples=200`` + ``derandomize=True`` for CI
stability so flake-free reruns produce identical examples. The
``derandomize`` profile disables Hypothesis's database-driven random seed
selection — every run hits the same shrunken-counterexample search path.
"""

from __future__ import annotations

from hypothesis import HealthCheck, Verbosity, settings


# Two profiles:
#
#   * ``ci``       — derandomized, 200 examples, suppress the slow-data-fetch
#                    health check because some strategies build datetime grids
#                    that briefly look slow to Hypothesis on first warmup.
#   * ``dev``      — same example count, but allows Hypothesis to remember
#                    failures between runs (the default). Use locally when
#                    you want the example database to grow.
#
# CI is the default profile so deflakes are reproducible; opt into ``dev``
# via ``HYPOTHESIS_PROFILE=dev pytest tests/property/``.

settings.register_profile(
    "ci",
    max_examples=200,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    verbosity=Verbosity.normal,
)

settings.register_profile(
    "dev",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    verbosity=Verbosity.normal,
)

# Activate the CI profile by default; tests can override per-call via
# ``@settings(...)``. Reading the env once here keeps the rest of the
# suite free of profile bookkeeping.
import os as _os

_profile = _os.environ.get("HYPOTHESIS_PROFILE", "ci")
settings.load_profile(_profile)
