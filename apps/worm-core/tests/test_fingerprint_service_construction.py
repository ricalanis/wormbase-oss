"""L5 Sub-wave C — env-driven FingerprintService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_fingerprint_service_from_env`` and
``compose_fingerprint_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L5 disabled stays at the
    pre-L5 baseline.
  * ENABLED → composite always carries ColumnName; ValuePattern +
    Distribution default to None.
  * VALUE_PATTERN_ENABLED=true → ValuePattern wired with
    L3's NoopSampler honest-stub.
  * DISTRIBUTION_ENABLED=true → Distribution wired with
    L7's NoopHistoricalStatsReader honest-stub.
  * propose_window_seconds env knob flows through to the factory.
  * sample_size=20 is the canonical default flowed into the factory.
  * MIN_CONFIDENCE env knob is read without crash (forward compat).
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
    build_fingerprint_service_from_env,
    compose_fingerprint_reactivity_if_enabled,
    is_fingerprint_discovery_enabled,
    is_fingerprint_distribution_enabled,
    is_fingerprint_value_pattern_enabled,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000e0001")


@pytest.fixture
def clean_fingerprint_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_FINGERPRINT_* env knob for the test."""
    keys = [
        "WORMBASE_FINGERPRINT_DISCOVERY_ENABLED",
        "WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED",
        "WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED",
        "WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_FINGERPRINT_MIN_CONFIDENCE",
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
    clean_fingerprint_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L5."""
    assert is_fingerprint_discovery_enabled() is False
    assert build_fingerprint_service_from_env() is None


def test_enabled_composes_column_name_only_by_default(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """Flipping the master knob composes ColumnName always.

    ValuePattern + Distribution stay None by default (opt-in via the
    second + third knobs). ColumnName is the productive-today strategy
    that requires no upstream sampler / stats.
    """
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    svc = build_fingerprint_service_from_env()
    assert svc is not None
    # The composite is a LakeLoopComposite[ProposedSemanticType]; the
    # strategies dict carries the wiring contract.
    assert svc.strategies.get("column_name") is not None
    assert svc.strategies.get("value_pattern") is None
    assert svc.strategies.get("distribution") is None


def test_value_pattern_env_knob_wires_with_noop_sampler(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """VALUE_PATTERN_ENABLED=true → ValuePattern wired with NoopSampler.

    Reuses L3's NoopSampler — no new reader Protocol introduced. The
    strategy fires on the structural code path but returns [] until a
    real connector-backed sampler lands.
    """
    from wormbase_core.lineage_catalog_reader import NoopSampler

    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED"] = "true"

    assert is_fingerprint_value_pattern_enabled() is True

    svc = build_fingerprint_service_from_env()
    assert svc is not None
    value_pattern = svc.strategies.get("value_pattern")
    assert value_pattern is not None
    assert isinstance(value_pattern.sampler, NoopSampler)


def test_distribution_env_knob_wires_with_noop_historical_stats_reader(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """DISTRIBUTION_ENABLED=true → Distribution wired with NoopHistoricalStatsReader.

    Reuses L7's NoopHistoricalStatsReader — no new reader Protocol
    introduced. The strategy fires on the structural code path but
    returns [] until Wave 1 catalog mirror emits per-column stats.
    """
    from wormbase_core.quality_catalog_reader import (
        NoopHistoricalStatsReader,
    )

    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED"] = "true"

    assert is_fingerprint_distribution_enabled() is True

    svc = build_fingerprint_service_from_env()
    assert svc is not None
    distribution = svc.strategies.get("distribution")
    assert distribution is not None
    assert isinstance(distribution.stats_reader, NoopHistoricalStatsReader)


def test_compose_fingerprint_reactivity_default_off_returns_none(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """Default OFF → compose_fingerprint_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L5 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_fingerprint_reactivity_if_enabled(ledger=ledger)
    assert reactivity is None


def test_compose_fingerprint_reactivity_when_enabled(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_fingerprint_reactivity_if_enabled(ledger=ledger)
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.fingerprint_discovery"


def test_propose_window_env_knob_flows_through(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory."""
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS"] = "5678"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        fingerprint_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
        sample_size: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["fingerprint_service"] = fingerprint_service
        captured["catalog_reader"] = catalog_reader
        captured["sample_size"] = sample_size

        class _Sentinel:
            id = "agent_gateway.fingerprint_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_fingerprint_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_fingerprint_reactivity_if_enabled(
            ledger=ledger,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 5678
        assert captured["fingerprint_service"] is not None
        assert captured["catalog_reader"] is not None
        # sample_size=20 is the canonical default (per spec — N for
        # value-pattern M/N matching).
        assert captured["sample_size"] == 20


def test_min_confidence_env_knob_read_without_crash(
    clean_fingerprint_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    The composite doesn't currently route it (Sub-wave B keeps per-
    strategy confidence); this test pins that setting the knob does
    not break the build path (forward compat).
    """
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_MIN_CONFIDENCE"] = "0.75"

    svc = build_fingerprint_service_from_env()
    assert svc is not None
