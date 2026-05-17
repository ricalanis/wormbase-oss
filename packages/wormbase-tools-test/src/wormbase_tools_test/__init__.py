"""wormbase-tools-test — SurfaceDriver Protocol conformance harness.

Public API:

* :func:`assert_authenticate_valid_returns_authhandle` — invariant 1
* :func:`assert_authenticate_invalid_raises` — invariant 2
* :func:`assert_discover_stable_ordering` — invariant 3
* :func:`assert_profile_idempotent` — invariant 4
* :func:`assert_sample_deterministic` — invariant 5
* :func:`assert_watch_cancellable` — invariant 6
* :func:`run_full_conformance` — convenience wrapper running all six

The pytest plugin in :mod:`wormbase_tools_test.plugin` adds a
``--connector`` flag and a parametrized test class that calls each of
the six asserts; programmatic use is also supported.
"""

from __future__ import annotations

from .invariants import (
    INVARIANT_NAMES,
    assert_authenticate_invalid_raises,
    assert_authenticate_valid_returns_authhandle,
    assert_discover_stable_ordering,
    assert_profile_idempotent,
    assert_sample_deterministic,
    assert_watch_cancellable,
    is_authhandle_shaped,
    is_profile_shaped,
    is_resource_proposal_shaped,
    run_full_conformance,
)

__version__ = "0.1.0"

__all__ = [
    "INVARIANT_NAMES",
    "__version__",
    "assert_authenticate_invalid_raises",
    "assert_authenticate_valid_returns_authhandle",
    "assert_discover_stable_ordering",
    "assert_profile_idempotent",
    "assert_sample_deterministic",
    "assert_watch_cancellable",
    "is_authhandle_shaped",
    "is_profile_shaped",
    "is_resource_proposal_shaped",
    "run_full_conformance",
]
