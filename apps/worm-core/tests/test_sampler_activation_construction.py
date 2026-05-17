"""Sampler activation Wave — construction-site env-knob tests.

Pins the contract that ``WORMBASE_SAMPLER_ACTIVATION_ENABLED`` swaps
:class:`NoopSampler` for :class:`ConnectorSampler` at the L3 / L5 / L8
construction sites in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``,
WITHOUT changing the registry count, KIND_REGISTRY, or any other
observable when the env knob is unset.

Default-OFF tests assert byte-identical behaviour: NoopSampler is
used and no construction-time exception is raised. Env-ON tests assert
the swap and verify the tenant scoping (the bound ``company_id`` lands
on the ConnectorSampler instance).
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
    _build_active_sampler_if_enabled,
    compose_entity_stitch_reactivity_if_enabled,
    compose_fingerprint_reactivity_if_enabled,
    compose_lineage_reactivity_if_enabled,
    is_sampler_activation_enabled,
)
from wormbase_core.connector_sampler import ConnectorSampler
from wormbase_core.lineage_catalog_reader import NoopSampler


_COMPANY = UUID("00000000-0000-0000-0000-0000000c0001")

# All env knobs touched by these tests — wiped before and after each.
_ENV_KEYS = (
    "WORMBASE_SAMPLER_ACTIVATION_ENABLED",
    "WORMBASE_LINEAGE_DISCOVERY_ENABLED",
    "WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED",
    "WORMBASE_FINGERPRINT_DISCOVERY_ENABLED",
    "WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED",
    "WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED",
    "WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED",
)


@pytest.fixture
def clean_env() -> Iterator[None]:
    """Wipe all relevant env knobs before / after each test."""
    original: dict[str, str] = {}
    for k in _ENV_KEYS:
        if k in os.environ:
            original[k] = os.environ[k]
            del os.environ[k]
    try:
        yield
    finally:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in original.items():
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Env-knob helper
# ---------------------------------------------------------------------------


def test_default_off_is_sampler_activation_disabled(
    clean_env: None,
) -> None:
    assert is_sampler_activation_enabled() is False


def test_env_on_is_sampler_activation_enabled(clean_env: None) -> None:
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    assert is_sampler_activation_enabled() is True


# ---------------------------------------------------------------------------
# _build_active_sampler_if_enabled — the central gate
# ---------------------------------------------------------------------------


def test_default_off_builds_noop_sampler(clean_env: None) -> None:
    ledger = InMemoryLedger()
    sampler = _build_active_sampler_if_enabled(
        ledger=ledger, company_id=_COMPANY,
    )
    assert isinstance(sampler, NoopSampler)


def test_env_on_builds_connector_sampler(clean_env: None) -> None:
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    ledger = InMemoryLedger()
    sampler = _build_active_sampler_if_enabled(
        ledger=ledger, company_id=_COMPANY,
    )
    assert isinstance(sampler, ConnectorSampler)
    assert sampler.company_id == _COMPANY


# ---------------------------------------------------------------------------
# L3 — compose_lineage_reactivity_if_enabled
# ---------------------------------------------------------------------------


def _capture_factory(captured: dict[str, Any]) -> Any:
    """Patch sub for the reactivity factory: capture kwargs + return sentinel."""

    class _Sentinel:
        id = "captured"

    def _fake(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _Sentinel()

    return _fake


def test_l3_default_off_keeps_noop_sampler(clean_env: None) -> None:
    """L3 with sample_overlap on but activation off → NoopSampler unchanged."""
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_lineage_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_lineage_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    inference = captured["inference_service"]
    assert isinstance(inference.sample_overlap.sampler, NoopSampler)


def test_l3_env_on_swaps_to_connector_sampler(clean_env: None) -> None:
    """L3 with activation env on → ConnectorSampler with bound company_id."""
    os.environ["WORMBASE_LINEAGE_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED"] = "true"
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_lineage_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_lineage_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    inference = captured["inference_service"]
    assert isinstance(inference.sample_overlap.sampler, ConnectorSampler)
    assert inference.sample_overlap.sampler.company_id == _COMPANY


# ---------------------------------------------------------------------------
# L5 — compose_fingerprint_reactivity_if_enabled
# ---------------------------------------------------------------------------


def test_l5_default_off_keeps_noop_sampler(clean_env: None) -> None:
    """L5 with value_pattern on but activation off → NoopSampler unchanged."""
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_fingerprint_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_fingerprint_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    service = captured["fingerprint_service"]
    value_pattern = service.strategies["value_pattern"]
    assert isinstance(value_pattern.sampler, NoopSampler)


def test_l5_env_on_swaps_to_connector_sampler(clean_env: None) -> None:
    """L5 with activation env on → ConnectorSampler with bound company_id."""
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED"] = "true"
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_fingerprint_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_fingerprint_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    service = captured["fingerprint_service"]
    value_pattern = service.strategies["value_pattern"]
    assert isinstance(value_pattern.sampler, ConnectorSampler)
    assert value_pattern.sampler.company_id == _COMPANY


def test_l5_env_on_without_company_id_keeps_noop_sampler(
    clean_env: None,
) -> None:
    """L5 activation env on but company_id=None → stays NoopSampler (safe)."""
    os.environ["WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED"] = "true"
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_fingerprint_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_fingerprint_reactivity_if_enabled(
            ledger=ledger,  # no company_id
        )
        assert reactivity is not None
    service = captured["fingerprint_service"]
    value_pattern = service.strategies["value_pattern"]
    # Without a tenant binding, we keep NoopSampler — safer fallback.
    assert isinstance(value_pattern.sampler, NoopSampler)


# ---------------------------------------------------------------------------
# L8 — compose_entity_stitch_reactivity_if_enabled
# ---------------------------------------------------------------------------


def test_l8_default_off_keeps_noop_sampler(clean_env: None) -> None:
    """L8 with sample_overlap on but activation off → NoopSampler unchanged."""
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_entity_stitch_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_entity_stitch_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    service = captured["stitch_service"]
    sample_overlap = service.strategies["sample_overlap"]
    assert isinstance(sample_overlap.sampler, NoopSampler)


def test_l8_env_on_swaps_to_connector_sampler(clean_env: None) -> None:
    """L8 with activation env on → ConnectorSampler with bound company_id."""
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED"] = "true"
    os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
    captured: dict[str, Any] = {}
    with patch(
        "wormbase_core.agent_gateway_construction"
        ".make_entity_stitch_discovery_reactivity",
        side_effect=_capture_factory(captured),
    ):
        ledger = InMemoryLedger()
        reactivity = compose_entity_stitch_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY,
        )
        assert reactivity is not None
    service = captured["stitch_service"]
    sample_overlap = service.strategies["sample_overlap"]
    assert isinstance(sample_overlap.sampler, ConnectorSampler)
    assert sample_overlap.sampler.company_id == _COMPANY
