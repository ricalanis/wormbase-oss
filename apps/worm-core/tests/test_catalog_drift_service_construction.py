"""L2 Sub-wave C — env-driven CatalogDriftService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_catalog_drift_service_from_env`` and
``compose_catalog_drift_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L2 disabled stays at the
    pre-L2 baseline.
  * ENABLED with no sub-knobs → composite has all three slots None
    (master switch composes the empty composite; honest Optional-
    Effect Injection — L2 has no always-on strategy).
  * TABLE_SET_ENABLED=true → composite carries TableSetDriftStrategy.
  * COLUMN_SET_ENABLED=true → composite carries ColumnSetDriftStrategy.
  * COLUMN_TYPE_ENABLED=true → composite carries ColumnTypeDriftStrategy.
  * MIN_CONFIDENCE env knob is read without crash (env-resolution-
    layer placement per Sub-wave B handoff concern #3; default 0.7).
  * Reactivity id is the canonical
    ``agent_gateway.catalog_drift_discovery``.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_catalog_drift_service_from_env,
    compose_catalog_drift_reactivity_if_enabled,
    is_catalog_drift_column_set_enabled,
    is_catalog_drift_column_type_enabled,
    is_catalog_drift_discovery_enabled,
    is_catalog_drift_table_set_enabled,
)


@pytest.fixture
def clean_catalog_drift_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_CATALOG_DRIFT_* env knob for the test."""
    keys = [
        "WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED",
        "WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED",
        "WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED",
        "WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED",
        "WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE",
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
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L2."""
    assert is_catalog_drift_discovery_enabled() is False
    ledger = InMemoryLedger()
    assert build_catalog_drift_service_from_env(ledger=ledger) is None


def test_enabled_with_no_substrategies_composes_empty_composite(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """Flipping the master knob composes the composite with ALL slots None.

    L2 (like L1) diverges from L6/L8 in that no strategy is always-on
    — each strategy targets a different snapshot layer.
    """
    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("table_set") is None
    assert svc.strategies.get("column_set") is None
    assert svc.strategies.get("column_type") is None


def test_table_set_env_knob_wires_strategy(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """TABLE_SET_ENABLED=true → composite carries TableSetDriftStrategy."""
    from wormbase_agent_gateway.catalog_drift import TableSetDriftStrategy

    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED"] = "true"

    assert is_catalog_drift_table_set_enabled() is True

    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None
    table_set = svc.strategies.get("table_set")
    assert table_set is not None
    assert isinstance(table_set, TableSetDriftStrategy)


def test_column_set_env_knob_wires_strategy(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """COLUMN_SET_ENABLED=true → composite carries ColumnSetDriftStrategy."""
    from wormbase_agent_gateway.catalog_drift import ColumnSetDriftStrategy

    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED"] = "true"

    assert is_catalog_drift_column_set_enabled() is True

    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None
    column_set = svc.strategies.get("column_set")
    assert column_set is not None
    assert isinstance(column_set, ColumnSetDriftStrategy)


def test_column_type_env_knob_wires_strategy(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """COLUMN_TYPE_ENABLED=true → composite carries ColumnTypeDriftStrategy."""
    from wormbase_agent_gateway.catalog_drift import ColumnTypeDriftStrategy

    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED"] = "true"

    assert is_catalog_drift_column_type_enabled() is True

    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None
    column_type = svc.strategies.get("column_type")
    assert column_type is not None
    assert isinstance(column_type, ColumnTypeDriftStrategy)


def test_compose_catalog_drift_reactivity_default_off_returns_none(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """Default OFF → compose_catalog_drift_reactivity_if_enabled returns None.

    Byte-identical-when-disabled contract: when None comes back,
    cli.py skips reactivity_registry.register, preserving the
    pre-L2 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_catalog_drift_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is None


def test_compose_catalog_drift_reactivity_when_enabled(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_catalog_drift_reactivity_if_enabled(
        ledger=ledger,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.catalog_drift_discovery"


def test_min_confidence_env_knob_read_without_crash(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    Per Sub-wave B handoff concern #3 (mirrors L6 + L8 + L1 posture),
    the filter belongs at the env-resolution layer (gate-shaped)
    rather than baked into the strategies. L2's floor is 0.7
    (between L1's 0.4 and L6/L8's 0.6).
    """
    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE"] = "0.5"

    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None


def test_all_substrategy_knobs_enable_full_composite(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """Flipping every sub-knob wires all three strategy slots."""
    os.environ["WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED"] = "true"

    ledger = InMemoryLedger()
    svc = build_catalog_drift_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("table_set") is not None
    assert svc.strategies.get("column_set") is not None
    assert svc.strategies.get("column_type") is not None


def test_substrategy_knobs_without_master_switch_returns_none(
    clean_catalog_drift_env: dict[str, str],
) -> None:
    """Sub-strategy knobs without master switch → factory returns None.

    The master switch is the kill-switch; sub-strategy knobs only
    have an effect when the master is also on. Mirrors L1 + L6 + L8.
    """
    os.environ["WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED"] = "true"
    os.environ["WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED"] = "true"

    ledger = InMemoryLedger()
    assert build_catalog_drift_service_from_env(ledger=ledger) is None
