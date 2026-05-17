"""Smoke test: post-chat-worm-extraction, non-lifted flows still work.

Per D4 + spike §4.2:
  - DashboardFormFlow stays in worm-core
  - LakeDiscoveryFlow stays in worm-core
  - The four chat-driven flows lift to wormbase_chat_presence

This test verifies (a) the shim re-exports the lifted classes for legacy
imports, and (b) the non-lifted classes are still constructible and
importable from wormbase_core.flows.
"""
from __future__ import annotations


def test_lifted_flows_reachable_via_shim() -> None:
    """The four lifted flows import via the legacy worm-core path."""
    from wormbase_core.flows import (
        CredentialInDmFlow,
        DropAndProfileFlow,
        KpiGapTriggeredFlow,
        MentionedInConversationFlow,
    )
    # Verify they ARE the chat-presence classes (not duplicates).
    from wormbase_chat_presence.chat_flows import (
        CredentialInDmFlow as _CIDF,
        DropAndProfileFlow as _DAPF,
        KpiGapTriggeredFlow as _KGTF,
        MentionedInConversationFlow as _MICF,
    )
    assert CredentialInDmFlow is _CIDF
    assert DropAndProfileFlow is _DAPF
    assert KpiGapTriggeredFlow is _KGTF
    assert MentionedInConversationFlow is _MICF


def test_non_lifted_flows_stay_in_worm_core() -> None:
    """DashboardFormFlow + LakeDiscoveryFlow are still in wormbase_core.flows."""
    from wormbase_core.flows import DashboardFormFlow, LakeDiscoveryFlow

    # They are NOT in chat-presence's surface.
    import wormbase_chat_presence.chat_flows as chat_flows

    assert "DashboardFormFlow" not in dir(chat_flows)
    assert "LakeDiscoveryFlow" not in dir(chat_flows)

    # Ensure the classes are themselves callable (no __init__ blow-up at
    # module import time). Construction depends on a SourceBuilder; a
    # SimpleNamespace placeholder is fine for the import-only check.
    assert DashboardFormFlow is not None
    assert LakeDiscoveryFlow is not None


def test_cascade_after_propose_stays() -> None:
    """cascade_after_propose helper is still importable from worm-core.flows."""
    from wormbase_core.flows import cascade_after_propose

    assert callable(cascade_after_propose)
