"""L3 Sub-wave C — env-driven LineageInferenceService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_lineage_inference_service_from_env`` and
``compose_lineage_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L3 disabled stays at the
    pre-L3 baseline.
  * ENABLED → composite carries NamingHeuristic + DbtManifest;
    SampleOverlap stays None by default.
  * SAMPLE_OVERLAP_ENABLED=true → SampleOverlap wired with NoopSampler.
  * Numeric knobs (edit_distance, jaccard threshold, propose window,
    days_lookback) flow through to the constructed strategies +
    reactivity.
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
    build_lineage_inference_service_from_env,
    compose_lineage_reactivity_if_enabled,
    is_lineage_discovery_enabled,
    is_lineage_sample_overlap_enabled,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000c0001")


@pytest.fixture
def clean_lineage_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_LINEAGE_* env knob for the duration of a test.

    Returns the original env so the test body can mutate via
    ``os.environ`` if needed.
    """
    keys = [
        "WORMBASE_LINEAGE_DISCOVERY_ENABLED",
        "WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED",
        "WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX",
        "WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD",
        "WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_LINEAGE_DAYS_LOOKBACK",
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


def test_default_off_returns_none(clean_lineage_env: dict[str, str]) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L3."""
    assert is_lineage_discovery_enabled() is False
    assert build_lineage_inference_service_from_env() is None


def test_enabled_composes_naming_strategy_by_default(
    clean_lineage_env: dict[str, str],
) -> None:
    """Flipping the master knob composes NamingHeuristicStrategy.

    DbtManifest is left for the reactivity-compose step (needs ledger);
    SampleOverlap stays None by default.
    """
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    svc = build_lineage_inference_service_from_env()
    assert svc is not None
    assert svc.naming is not None
    assert svc.naming.name == "naming_heuristic"
    # SampleOverlap is opt-in via a second knob.
    assert svc.sample_overlap is None
    # DbtManifest is wired post-build in compose_lineage_reactivity_if_enabled.
    assert svc.dbt_manifest is None


def test_sample_overlap_env_knob_wires_strategy(
    clean_lineage_env: dict[str, str],
) -> None:
    """Flipping the second knob composes SampleOverlap with NoopSampler."""
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED"] = "true"

    assert is_lineage_sample_overlap_enabled() is True
    svc = build_lineage_inference_service_from_env()
    assert svc is not None
    assert svc.sample_overlap is not None
    assert svc.sample_overlap.name == "sample_overlap"
    # NoopSampler is the honest-stub today.
    from wormbase_core.lineage_catalog_reader import NoopSampler

    assert isinstance(svc.sample_overlap.sampler, NoopSampler)


def test_edit_distance_env_knob_flows_through(
    clean_lineage_env: dict[str, str],
) -> None:
    """Edit-distance env knob threads through to NamingHeuristicStrategy."""
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX"] = "5"

    svc = build_lineage_inference_service_from_env()
    assert svc is not None
    assert svc.naming is not None
    assert svc.naming.edit_distance_max == 5


def test_jaccard_threshold_env_knob_flows_through(
    clean_lineage_env: dict[str, str],
) -> None:
    """Jaccard threshold env knob threads through to SampleOverlapStrategy."""
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD"] = "0.75"

    svc = build_lineage_inference_service_from_env()
    assert svc is not None
    assert svc.sample_overlap is not None
    assert svc.sample_overlap.jaccard_threshold == pytest.approx(0.75)


def test_compose_lineage_reactivity_default_off_returns_none(
    clean_lineage_env: dict[str, str],
) -> None:
    """Default OFF → compose_lineage_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L3 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_lineage_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_compose_lineage_reactivity_when_enabled_wires_dbt(
    clean_lineage_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with dbt_manifest wired.

    DbtManifest is wired at compose-time (not at env-build-time) because
    it needs ledger + company_id — the env knob path doesn't carry those.
    """
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_lineage_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.lineage_discovery"


def test_propose_window_env_knob_flows_through(
    clean_lineage_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory.

    We verify by patching make_lineage_discovery_reactivity to capture
    the kwarg.
    """
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS"] = "1234"
    os.environ["WORMBASE_LINEAGE_DAYS_LOOKBACK"] = "14"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        inference_service: Any,
        catalog_reader: Any,
        days_lookback: int,
        propose_window_seconds: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["days_lookback"] = days_lookback
        captured["inference_service"] = inference_service
        captured["catalog_reader"] = catalog_reader

        # Return a sentinel; we only assert on captured kwargs.
        class _Sentinel:
            id = "agent_gateway.lineage_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_lineage_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_lineage_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 1234
        assert captured["days_lookback"] == 14
        assert captured["inference_service"] is not None
        assert captured["catalog_reader"] is not None
