"""L6 Sub-wave C — env-driven ColumnClassificationService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_column_classification_service_from_env`` and
``compose_column_classification_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L6 disabled stays at the
    pre-L6 baseline.
  * ENABLED → composite always carries NamingPattern; SemanticType +
    DomainDefault default to None.
  * SEMANTIC_TYPE_ENABLED=true → SemanticType wired with
    LedgerConfirmedSemanticTypeReader (the 2nd cross-axis impl).
  * DOMAIN_DEFAULT_ENABLED=true → DomainDefault wired with
    LedgerDomainDefaultReader (reads existing governance state).
  * propose_window_seconds env knob flows through to the factory.
  * MIN_CONFIDENCE env knob is read without crash (env-resolution-layer
    placement per Sub-wave B handoff concern #3 — forward compat).
  * Reactivity id is the canonical
    ``agent_gateway.column_classification_discovery``.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_column_classification_service_from_env,
    compose_column_classification_reactivity_if_enabled,
    is_column_classification_discovery_enabled,
    is_column_classification_domain_default_enabled,
    is_column_classification_semantic_type_enabled,
)


@pytest.fixture
def clean_column_classification_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_COLUMN_CLASSIFICATION_* env knob for the test."""
    keys = [
        "WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED",
        "WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED",
        "WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED",
        "WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE",
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
    clean_column_classification_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L6."""
    assert is_column_classification_discovery_enabled() is False
    ledger = InMemoryLedger()
    assert build_column_classification_service_from_env(ledger=ledger) is None


def test_enabled_composes_naming_pattern_only_by_default(
    clean_column_classification_env: dict[str, str],
) -> None:
    """Flipping the master knob composes NamingPattern always.

    SemanticType + DomainDefault stay None by default (opt-in via the
    second + third knobs). NamingPattern is the productive-today
    strategy that requires no upstream reader.
    """
    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_column_classification_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("naming_pattern") is not None
    assert svc.strategies.get("semantic_type") is None
    assert svc.strategies.get("domain_default") is None


def test_semantic_type_env_knob_wires_with_ledger_reader(
    clean_column_classification_env: dict[str, str],
) -> None:
    """SEMANTIC_TYPE_ENABLED=true → SemanticType wired with the 2nd cross-axis impl.

    Verifies the strategy receives a real
    :class:`LedgerConfirmedSemanticTypeReader` (not a stub) — the 2nd
    cross-axis impl after L4's :class:`LedgerLineageEdgeReader`.
    """
    from wormbase_core.column_classification_semantic_reader import (
        LedgerConfirmedSemanticTypeReader,
    )

    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED"
    ] = "true"

    assert is_column_classification_semantic_type_enabled() is True

    ledger = InMemoryLedger()
    svc = build_column_classification_service_from_env(ledger=ledger)
    assert svc is not None
    semantic_type = svc.strategies.get("semantic_type")
    assert semantic_type is not None
    assert isinstance(
        semantic_type.semantic_type_reader,
        LedgerConfirmedSemanticTypeReader,
    )


def test_domain_default_env_knob_wires_with_ledger_reader(
    clean_column_classification_env: dict[str, str],
) -> None:
    """DOMAIN_DEFAULT_ENABLED=true → DomainDefault wired with governance reader.

    Verifies the strategy receives a real
    :class:`LedgerDomainDefaultReader` that reads existing onboarding
    governance state (graceful no-op when no pack is selected).
    """
    from wormbase_core.column_classification_domain_reader import (
        LedgerDomainDefaultReader,
    )

    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED"
    ] = "true"

    assert is_column_classification_domain_default_enabled() is True

    ledger = InMemoryLedger()
    svc = build_column_classification_service_from_env(ledger=ledger)
    assert svc is not None
    domain_default = svc.strategies.get("domain_default")
    assert domain_default is not None
    assert isinstance(
        domain_default.domain_default_reader,
        LedgerDomainDefaultReader,
    )


def test_compose_column_classification_reactivity_default_off_returns_none(
    clean_column_classification_env: dict[str, str],
) -> None:
    """Default OFF → compose_column_classification_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L6 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_column_classification_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is None


def test_compose_column_classification_reactivity_when_enabled(
    clean_column_classification_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_column_classification_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.column_classification_discovery"


def test_propose_window_env_knob_flows_through(
    clean_column_classification_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory."""
    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS"
    ] = "5678"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        classification_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["classification_service"] = classification_service
        captured["catalog_reader"] = catalog_reader

        class _Sentinel:
            id = "agent_gateway.column_classification_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction."
        "make_column_classification_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_column_classification_reactivity_if_enabled(
            ledger=ledger,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 5678
        assert captured["classification_service"] is not None
        assert captured["catalog_reader"] is not None


def test_min_confidence_env_knob_read_without_crash(
    clean_column_classification_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    Per Sub-wave B handoff concern #3, the filter belongs at the
    env-resolution layer (gate-shaped) rather than baked into the
    strategies. The Sub-wave B composite doesn't currently route it
    (per-strategy confidence holds today); this test pins that setting
    the knob does not break the build path (forward compat).
    """
    os.environ["WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE"] = "0.75"

    ledger = InMemoryLedger()
    svc = build_column_classification_service_from_env(ledger=ledger)
    assert svc is not None
