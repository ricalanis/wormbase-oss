"""Confirm legacy module imports + emits DeprecationWarning."""
from __future__ import annotations

import warnings


def test_legacy_module_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        # Force re-import to ensure the warning fires this run.
        import importlib
        import wormbase_identity_tracker.legacy as legacy_module
        importlib.reload(legacy_module)
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "IdentityDiscoveryLoop" in str(w.message)
        for w in captured
    )


def test_legacy_loop_class_present() -> None:
    from wormbase_identity_tracker.legacy import IdentityDiscoveryLoop

    # Class shape preserved for the byte-equivalence test.
    assert hasattr(IdentityDiscoveryLoop, "run_once")
    assert hasattr(IdentityDiscoveryLoop, "run_forever")
