"""L1 Sub-wave C — env-driven SourceCandidateService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_source_candidate_service_from_env`` and
``compose_source_candidate_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L1 disabled stays at the
    pre-L1 baseline.
  * ENABLED with no sub-knobs → composite has all three slots None
    (master switch composes the empty composite; honest Optional-
    Effect Injection per spec §4.8 — L1 has no always-on strategy).
  * KPI_GAP_ENABLED=true → composite carries
    KpiGapAcquisitionStrategy wired with LedgerKpiNodeReader.
  * CHANNEL_MENTION_ENABLED=true → composite carries
    ChannelMentionAcquisitionStrategy wired with
    LedgerSilverConversationReader.
  * COMPLEMENTARITY_ENABLED=true → composite carries
    ComplementaritySourceStrategy wired with
    LedgerConnectedSourceReader.
  * MIN_CONFIDENCE env knob is read without crash (env-resolution-
    layer placement per Sub-wave B handoff concern #3 — forward
    compat).
  * Reactivity id is the canonical
    ``agent_gateway.source_candidate_discovery``.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_source_candidate_service_from_env,
    compose_source_candidate_reactivity_if_enabled,
    is_source_candidate_channel_mention_enabled,
    is_source_candidate_complementarity_enabled,
    is_source_candidate_discovery_enabled,
    is_source_candidate_kpi_gap_enabled,
)


@pytest.fixture
def clean_source_candidate_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_SOURCE_CANDIDATE_* env knob for the test."""
    keys = [
        "WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED",
        "WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED",
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED",
        "WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED",
        "WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE",
    ]
    original: dict[str, str] = {}
    for k in keys:
        if k in os.environ:
            original[k] = os.environ[k]
            del os.environ[k]
    try:
        yield original
    finally:
        for k in keys:
            os.environ.pop(k, None)
        for k, v in original.items():
            os.environ[k] = v


def test_default_off_returns_none(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L1."""
    assert is_source_candidate_discovery_enabled() is False
    ledger = InMemoryLedger()
    assert build_source_candidate_service_from_env(ledger=ledger) is None


def test_enabled_with_no_substrategies_composes_empty_composite(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """Flipping the master knob composes the composite with ALL slots None.

    L1 diverges from L6/L8 in that no strategy is always-on — every
    L1 strategy reads a different platform projection and operators
    opt in per-projection.
    """
    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("kpi_gap") is None
    assert svc.strategies.get("channel_mention") is None
    assert svc.strategies.get("complementarity") is None


def test_kpi_gap_env_knob_wires_strategy_with_ledger_reader(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """KPI_GAP_ENABLED=true → KpiGap composed with LedgerKpiNodeReader."""
    from wormbase_core.source_candidate_readers import LedgerKpiNodeReader

    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED"] = "true"

    assert is_source_candidate_kpi_gap_enabled() is True

    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None
    kpi_gap = svc.strategies.get("kpi_gap")
    assert kpi_gap is not None
    assert isinstance(kpi_gap.kpi_node_reader, LedgerKpiNodeReader)


def test_channel_mention_env_knob_wires_strategy_with_ledger_reader(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """CHANNEL_MENTION_ENABLED=true → ChannelMention composed with
    LedgerSilverConversationReader."""
    from wormbase_core.source_candidate_readers import (
        LedgerSilverConversationReader,
    )

    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED"
    ] = "true"

    assert is_source_candidate_channel_mention_enabled() is True

    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None
    channel_mention = svc.strategies.get("channel_mention")
    assert channel_mention is not None
    assert isinstance(
        channel_mention.silver_conversation_reader,
        LedgerSilverConversationReader,
    )


def test_complementarity_env_knob_wires_strategy_with_ledger_reader(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """COMPLEMENTARITY_ENABLED=true → Complementarity composed with
    LedgerConnectedSourceReader."""
    from wormbase_core.source_candidate_readers import (
        LedgerConnectedSourceReader,
    )

    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED"
    ] = "true"

    assert is_source_candidate_complementarity_enabled() is True

    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None
    complementarity = svc.strategies.get("complementarity")
    assert complementarity is not None
    assert isinstance(
        complementarity.connected_source_reader,
        LedgerConnectedSourceReader,
    )


def test_compose_source_candidate_reactivity_default_off_returns_none(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """Default OFF → compose_source_candidate_reactivity_if_enabled
    returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L1 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_source_candidate_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is None


def test_compose_source_candidate_reactivity_when_enabled(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_source_candidate_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.source_candidate_discovery"


def test_min_confidence_env_knob_read_without_crash(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    Per Sub-wave B handoff concern #3 (mirrors L6 + L8 posture), the
    filter belongs at the env-resolution layer (gate-shaped) rather
    than baked into the strategies. L1's floor is 0.4 (lower than
    other axes' 0.6) because triage is the right place for low-
    confidence noise.
    """
    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE"] = "0.3"

    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None


def test_all_substrategy_knobs_enable_full_composite(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """Flipping every sub-knob wires all three strategy slots."""
    os.environ["WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED"] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED"
    ] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED"
    ] = "true"

    ledger = InMemoryLedger()
    svc = build_source_candidate_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("kpi_gap") is not None
    assert svc.strategies.get("channel_mention") is not None
    assert svc.strategies.get("complementarity") is not None


def test_substrategy_knobs_without_master_switch_returns_none(
    clean_source_candidate_env: dict[str, str],
) -> None:
    """Sub-strategy knobs without master switch → factory still returns None.

    The master switch is the kill-switch; sub-strategy knobs only
    have an effect when the master is also on. Mirrors L6 + L8.
    """
    os.environ["WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED"] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED"
    ] = "true"
    os.environ[
        "WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED"
    ] = "true"

    ledger = InMemoryLedger()
    assert build_source_candidate_service_from_env(ledger=ledger) is None
