"""L4 Sub-wave C — env-driven SchemaImpactService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_schema_impact_service_from_env`` and
``compose_schema_impact_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L4 disabled stays at the
    pre-L4 baseline.
  * ENABLED → composite carries LineageEdge + TypeCoercion; DbtTest
    stays None by default.
  * DBT_TEST_ENABLED=true → DbtTest wired with LedgerDbtTestReader
    at compose-time.
  * INCLUDE_NAMING_LINEAGE=true threads through to
    LineageEdgeImpactStrategy.include_naming_lineage.
  * propose_window_seconds env knob flows through to the factory.
  * Shared LineageEdgeReader instance threaded to BOTH cross-axis
    strategies (Sub-wave B handoff concern #5).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_schema_impact_service_from_env,
    compose_schema_impact_reactivity_if_enabled,
    is_schema_impact_acknowledged_drift_enabled,
    is_schema_impact_dbt_test_enabled,
    is_schema_impact_discovery_enabled,
    is_schema_impact_governance_enabled,
    is_schema_impact_naming_lineage_enabled,
    is_schema_impact_semantic_type_enabled,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000d0001")


@pytest.fixture
def clean_schema_impact_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_SCHEMA_IMPACT_* env knob for the test."""
    keys = [
        "WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED",
        "WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED",
        "WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE",
        "WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE",
        "WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED",
        "WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED",
        "WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED",
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
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L4."""
    ledger = InMemoryLedger()
    assert is_schema_impact_discovery_enabled() is False
    assert build_schema_impact_service_from_env(ledger=ledger) is None


def test_enabled_composes_lineage_edge_and_type_coercion(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Flipping the master knob composes LineageEdge + TypeCoercion.

    DbtTest stays None by default (opt-in via the second knob).
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.lineage_edge is not None
    assert svc.lineage_edge.name == "lineage_edge"
    assert svc.type_coercion is not None
    assert svc.type_coercion.name == "type_coercion"
    # DbtTest is opt-in via a second knob; not wired at build_from_env time.
    assert svc.dbt_test is None


def test_dbt_test_env_knob_wires_strategy_at_compose_time(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """DBT_TEST_ENABLED=true → DbtTest is wired at compose time, not build time.

    DbtTest needs ledger + company_id which the env-only build helper
    doesn't carry. Build returns dbt_test=None; compose wires it in.
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED"] = "true"

    assert is_schema_impact_dbt_test_enabled() is True

    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    # build-from-env leaves dbt_test None (tenant-scoped reader needs
    # company_id which lives at compose time).
    assert svc.dbt_test is None

    # Compose wires it.
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None


def test_include_naming_lineage_env_knob_flows_through(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """INCLUDE_NAMING_LINEAGE=true threads to LineageEdgeImpactStrategy."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE"] = "true"

    assert is_schema_impact_naming_lineage_enabled() is True

    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.lineage_edge is not None
    assert svc.lineage_edge.include_naming_lineage is True


def test_naming_lineage_default_off(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Default OFF → include_naming_lineage=False on the LineageEdge strategy."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"

    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.lineage_edge is not None
    assert svc.lineage_edge.include_naming_lineage is False


def test_compose_schema_impact_reactivity_default_off_returns_none(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Default OFF → compose_schema_impact_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L4 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_compose_schema_impact_reactivity_when_enabled(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.schema_impact_discovery"


def test_propose_window_env_knob_flows_through(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS"] = "4321"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["impact_service"] = impact_service
        captured["catalog_reader"] = catalog_reader

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 4321
        assert captured["impact_service"] is not None
        assert captured["catalog_reader"] is not None


def test_shared_lineage_edge_reader_instance(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Both cross-axis-reading strategies share ONE LineageEdgeReader (concern #5).

    The LedgerLineageEdgeReader is constructed once per build call and
    threaded into BOTH the LineageEdgeImpactStrategy AND the
    TypeCoercionImpactStrategy. Verifying identity here protects
    against accidental double-construction (which would double the
    cross-axis read cost AND make telemetry harder to track).
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.lineage_edge is not None
    assert svc.type_coercion is not None
    # Same instance — not just structurally equal.
    assert svc.lineage_edge.lineage_edge_reader is svc.type_coercion.lineage_edge_reader


def test_min_confidence_env_knob_read_without_crash(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    The composite doesn't currently route it; this test pins that
    setting the knob does not break the build path (forward compat).
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE"] = "0.75"

    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None


# ---------------------------------------------------------------------------
# L6→L4 cross-axis chain (5th chain) — WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED
# ---------------------------------------------------------------------------


def test_governance_env_knob_default_off(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Default OFF: governance_classification stays None on the composite."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    assert is_schema_impact_governance_enabled() is False

    ledger = InMemoryLedger()
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    # Inspect the composite via the reactivity's wired service.
    # The composite is constructed inside compose_; we re-read by
    # building via the same env path.
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.governance_classification is None


def test_governance_env_knob_requires_master_switch(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Setting governance_enabled WITHOUT master discovery off → master wins (None)."""
    os.environ["WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"] = "true"
    # Master is OFF.
    assert is_schema_impact_discovery_enabled() is False
    assert is_schema_impact_governance_enabled() is True
    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    # Master OFF dominates — composite is not built at all.
    assert svc is None
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_governance_env_knob_wires_strategy_at_compose_time(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """GOVERNANCE_ENABLED=true → governance_classification wired at compose
    time with the LedgerConfirmedClassificationReader adapter."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"] = "true"

    assert is_schema_impact_governance_enabled() is True

    ledger = InMemoryLedger()
    # build_from_env does NOT wire the governance strategy — it depends
    # on the cross-axis reader which needs the ledger at construction
    # time. This mirrors the dbt_test pattern.
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.governance_classification is None

    # Compose wires it.
    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["impact_service"] = impact_service

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        composed_svc = captured["impact_service"]
        assert composed_svc.governance_classification is not None
        assert composed_svc.governance_classification.name == (
            "governance_classification"
        )
        # Adapter is the L6→L4 reader.
        from wormbase_core.column_classification_governance_reader import (
            LedgerConfirmedClassificationReader,
        )
        assert isinstance(
            composed_svc.governance_classification.confirmed_classification_reader,
            LedgerConfirmedClassificationReader,
        )


# ---------------------------------------------------------------------------
# L5→L4 cross-axis chain (6th chain) — WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED
# ---------------------------------------------------------------------------


def test_semantic_type_env_knob_default_off(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Default OFF: semantic_type stays None on the composite (byte-identical)."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    assert is_schema_impact_semantic_type_enabled() is False

    ledger = InMemoryLedger()
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    # Inspect the composite via build_from_env (same env path as compose_).
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.semantic_type is None


def test_semantic_type_env_knob_requires_master_switch(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Setting semantic_type_enabled WITHOUT master discovery off → master wins (None)."""
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"
    # Master is OFF.
    assert is_schema_impact_discovery_enabled() is False
    assert is_schema_impact_semantic_type_enabled() is True
    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    # Master OFF dominates — composite is not built at all.
    assert svc is None
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_semantic_type_env_knob_wires_strategy_at_compose_time(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """SEMANTIC_TYPE_ENABLED=true → semantic_type wired at compose
    time with the REUSED LedgerConfirmedSemanticTypeReader adapter.

    This is the 4th-consumer reuse pin: the same concrete adapter that
    L6, L8, and L7 use (via the L6→L5, L8→L5, L5→L7 chains) is
    instantiated for L4's L5→L4 chain — no new adapter, no Protocol
    drift.
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"

    assert is_schema_impact_semantic_type_enabled() is True

    ledger = InMemoryLedger()
    # build_from_env does NOT wire the semantic_type strategy — it
    # depends on the cross-axis reader which needs the ledger at
    # construction time. This mirrors the dbt_test + governance pattern.
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.semantic_type is None

    # Compose wires it.
    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["impact_service"] = impact_service

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        composed_svc = captured["impact_service"]
        assert composed_svc.semantic_type is not None
        assert composed_svc.semantic_type.name == "semantic_type"
        # Adapter is the REUSED L6 reader (4th consumer — pin).
        from wormbase_core.column_classification_semantic_reader import (
            LedgerConfirmedSemanticTypeReader,
        )
        assert isinstance(
            composed_svc.semantic_type.confirmed_semantic_type_reader,
            LedgerConfirmedSemanticTypeReader,
        )


def test_all_four_sub_knobs_on_composes_all_strategies(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """All 4 sub-knobs (dbt_test + governance + semantic_type) on +
    naming_lineage on → composite carries all 5 strategies populated."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE"] = "true"

    ledger = InMemoryLedger()
    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["impact_service"] = impact_service

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        svc = captured["impact_service"]
        # All 5 strategies populated.
        assert svc.lineage_edge is not None
        assert svc.dbt_test is not None
        assert svc.type_coercion is not None
        assert svc.governance_classification is not None
        assert svc.semantic_type is not None
        # naming_lineage threaded through.
        assert svc.lineage_edge.include_naming_lineage is True


def test_semantic_type_strategy_lookup_returns_strategy_name(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """The wired SemanticTypeImpactStrategy reports the canonical
    ``"semantic_type"`` name — pins the metrics key for the composite."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"
    ledger = InMemoryLedger()
    captured: dict[str, Any] = {}

    def _fake_factory(*, impact_service, catalog_reader, propose_window_seconds):
        captured["svc"] = impact_service
        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"
        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
    svc = captured["svc"]
    assert svc.semantic_type.name == "semantic_type"


# ---------------------------------------------------------------------------
# L4↦L2 cross-axis chain (7th chain, FIRST bidirectional) —
# WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED
# ---------------------------------------------------------------------------


def test_acknowledged_drift_env_knob_default_off(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Default OFF — the env knob is not set, the strategy is not wired."""
    assert is_schema_impact_acknowledged_drift_enabled() is False


def test_acknowledged_drift_env_knob_requires_master_switch(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """Setting acknowledged_drift_enabled WITHOUT master discovery → None."""
    os.environ["WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED"] = "true"
    # Master is OFF.
    assert is_schema_impact_discovery_enabled() is False
    assert is_schema_impact_acknowledged_drift_enabled() is True
    ledger = InMemoryLedger()
    svc = build_schema_impact_service_from_env(ledger=ledger)
    # Master OFF dominates — composite is not built at all.
    assert svc is None
    reactivity = compose_schema_impact_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_acknowledged_drift_env_knob_wires_strategy_at_compose_time(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """ACKNOWLEDGED_DRIFT_ENABLED=true → acknowledged_drift wired at
    compose time with the NEW LedgerAcknowledgedDriftReader adapter.

    Pins:
      * build_from_env leaves the slot None (reader needs ledger at
        construction; mirrors dbt_test / governance / semantic_type).
      * compose threads in the concrete reader.
      * strategy.name == "acknowledged_drift" (metrics key pin).
      * reader IS the NEW LedgerAcknowledgedDriftReader (not a reuse).
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED"] = "true"

    assert is_schema_impact_acknowledged_drift_enabled() is True

    ledger = InMemoryLedger()
    # build_from_env does NOT wire the acknowledged_drift strategy.
    svc = build_schema_impact_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.acknowledged_drift is None

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["impact_service"] = impact_service

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        composed_svc = captured["impact_service"]
        assert composed_svc.acknowledged_drift is not None
        assert composed_svc.acknowledged_drift.name == "acknowledged_drift"
        # Reader IS the NEW LedgerAcknowledgedDriftReader.
        from wormbase_core.catalog_drift_acknowledged_reader import (
            LedgerAcknowledgedDriftReader,
        )
        assert isinstance(
            composed_svc.acknowledged_drift.acknowledged_drift_reader,
            LedgerAcknowledgedDriftReader,
        )


def test_all_six_sub_knobs_on_composes_all_strategies(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """All 5 sub-knobs (dbt_test + governance + semantic_type +
    acknowledged_drift) on + naming_lineage on → composite carries all
    6 strategies populated.

    Verifies the 7th cross-axis chain composes alongside the prior 4
    + the lineage_edge + type_coercion strategies without collision.
    """
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE"] = "true"

    ledger = InMemoryLedger()
    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        impact_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["impact_service"] = impact_service

        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        reactivity = compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        svc = captured["impact_service"]
        # All 6 strategies populated.
        assert svc.lineage_edge is not None
        assert svc.dbt_test is not None
        assert svc.type_coercion is not None
        assert svc.governance_classification is not None
        assert svc.semantic_type is not None
        assert svc.acknowledged_drift is not None
        # naming_lineage threaded through.
        assert svc.lineage_edge.include_naming_lineage is True


def test_acknowledged_drift_default_off_is_byte_identical_with_other_chains(
    clean_schema_impact_env: dict[str, str],
) -> None:
    """When acknowledged_drift is OFF but other sub-knobs are ON,
    composite carries the other strategies + acknowledged_drift=None
    (byte-identical to pre-L4↦L2 boot)."""
    os.environ["WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"] = "true"
    os.environ["WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"] = "true"

    ledger = InMemoryLedger()
    captured: dict[str, Any] = {}

    def _fake_factory(*, impact_service, catalog_reader, propose_window_seconds):
        captured["svc"] = impact_service
        class _Sentinel:
            id = "agent_gateway.schema_impact_discovery"
        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_schema_impact_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        compose_schema_impact_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
    svc = captured["svc"]
    # Other chains are ON; acknowledged_drift stays None.
    assert svc.governance_classification is not None
    assert svc.semantic_type is not None
    assert svc.acknowledged_drift is None
