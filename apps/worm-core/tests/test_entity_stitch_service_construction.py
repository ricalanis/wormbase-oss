"""L8 Sub-wave C — env-driven EntityStitchService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_entity_stitch_service_from_env`` and
``compose_entity_stitch_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L8 disabled stays at the
    pre-L8 baseline.
  * ENABLED → composite always carries NameMatch + SchemaShape;
    SampleOverlap defaults to None.
  * NameMatch always has ``use_semantic_type_anchor=False`` by default
    (anchor opt-in via its own env knob).
  * SEMANTIC_TYPE_ANCHOR_ENABLED=true → NameMatch wired with
    LedgerConfirmedSemanticTypeReader (REUSED from L6 — second
    consumer of the same Protocol).
  * SAMPLE_OVERLAP_ENABLED=true → SampleOverlap wired with
    L7's NoopSampler (honest-stub today).
  * propose_window_seconds env knob flows through to the factory.
  * MIN_CONFIDENCE env knob is read without crash (env-resolution-layer
    placement per Sub-wave B handoff concern #3 — forward compat).
  * Reactivity id is the canonical
    ``agent_gateway.entity_stitch_discovery``.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_entity_stitch_service_from_env,
    compose_entity_stitch_reactivity_if_enabled,
    is_entity_stitch_discovery_enabled,
    is_entity_stitch_sample_overlap_enabled,
    is_entity_stitch_semantic_type_anchor_enabled,
)


@pytest.fixture
def clean_entity_stitch_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_ENTITY_STITCH_* env knob for the test."""
    keys = [
        "WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED",
        "WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED",
        "WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED",
        "WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE",
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
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L8."""
    assert is_entity_stitch_discovery_enabled() is False
    ledger = InMemoryLedger()
    assert build_entity_stitch_service_from_env(ledger=ledger) is None


def test_enabled_composes_name_match_and_schema_shape_by_default(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """Flipping the master knob composes NameMatch + SchemaShape always.

    SampleOverlap stays None by default (opt-in via its own knob).
    SchemaShape is the productive-on-bare-catalog-metadata catch-all
    that requires no upstream reader; NameMatch's fuzzy-name path is
    always available even without the anchor.
    """
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None
    assert svc.strategies.get("name_match") is not None
    assert svc.strategies.get("schema_shape") is not None
    assert svc.strategies.get("sample_overlap") is None


def test_name_match_default_has_anchor_disabled(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """Default (anchor knob off) wires NameMatch with use_semantic_type_anchor=False.

    The fuzzy-name path is independent of the anchor and productive
    today. The anchor is opt-in via its own knob.
    """
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    assert is_entity_stitch_semantic_type_anchor_enabled() is False

    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None
    name_match = svc.strategies.get("name_match")
    assert name_match is not None
    assert name_match.use_semantic_type_anchor is False
    assert name_match.confirmed_semantic_type_reader is None


def test_semantic_type_anchor_env_knob_wires_with_reused_l6_reader(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """ANCHOR_ENABLED=true → NameMatch wired with REUSED L6 reader.

    Verifies the strategy receives a real
    :class:`LedgerConfirmedSemanticTypeReader` — the same impl L6
    Sub-wave C ships. L8 introduces NO new cross-axis adapter; it
    reuses L6's verbatim (second consumer of L6's Protocol).
    """
    from wormbase_core.column_classification_semantic_reader import (
        LedgerConfirmedSemanticTypeReader,
    )

    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED"
    ] = "true"

    assert is_entity_stitch_semantic_type_anchor_enabled() is True

    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None
    name_match = svc.strategies.get("name_match")
    assert name_match is not None
    assert name_match.use_semantic_type_anchor is True
    assert isinstance(
        name_match.confirmed_semantic_type_reader,
        LedgerConfirmedSemanticTypeReader,
    )


def test_sample_overlap_env_knob_wires_with_noop_sampler(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """SAMPLE_OVERLAP_ENABLED=true → SampleOverlap wired with L7's NoopSampler.

    Honest-stub today via L7's NoopSampler (empty samples → 0.0 Jaccard
    → below threshold → no proposals). Future wave wires the production
    sampler.
    """
    from wormbase_core.lineage_catalog_reader import NoopSampler

    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED"
    ] = "true"

    assert is_entity_stitch_sample_overlap_enabled() is True

    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None
    sample_overlap = svc.strategies.get("sample_overlap")
    assert sample_overlap is not None
    assert isinstance(sample_overlap.sampler, NoopSampler)


def test_compose_entity_stitch_reactivity_default_off_returns_none(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """Default OFF → compose_entity_stitch_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L8 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_entity_stitch_reactivity_if_enabled(ledger=ledger)
    assert reactivity is None


def test_compose_entity_stitch_reactivity_when_enabled(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with the canonical id."""
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_entity_stitch_reactivity_if_enabled(ledger=ledger)
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.entity_stitch_discovery"


def test_propose_window_env_knob_flows_through(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory."""
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ[
        "WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS"
    ] = "9876"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        stitch_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["stitch_service"] = stitch_service
        captured["catalog_reader"] = catalog_reader

        class _Sentinel:
            id = "agent_gateway.entity_stitch_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction."
        "make_entity_stitch_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_entity_stitch_reactivity_if_enabled(
            ledger=ledger,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 9876
        assert captured["stitch_service"] is not None
        assert captured["catalog_reader"] is not None


def test_min_confidence_env_knob_read_without_crash(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """MIN_CONFIDENCE knob is read at build time without crashing.

    Per Sub-wave B handoff concern #3 (mirrors L6 posture), the filter
    belongs at the env-resolution layer (gate-shaped) rather than
    baked into the strategies. The Sub-wave B composite doesn't
    currently route it (per-strategy confidence holds today); this
    test pins that setting the knob does not break the build path
    (forward compat).
    """
    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE"] = "0.8"

    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None


def test_schema_shape_lookup_closure_returns_empty_today(
    clean_entity_stitch_env: dict[str, str],
) -> None:
    """SchemaShape's parent_table_columns_lookup closure returns [] today.

    Per Sub-wave B handoff concern #2 + L8 design: the closure pattern
    is fine for now; the LedgerCatalogReader does not yet expose
    per-column lists (external_catalog_imported payload shape doesn't
    carry them), so the lookup degrades to empty list and the strategy
    is a no-op. When future catalog_table_imported entries carry
    columns, the strategy lights up without code change here.
    """
    import asyncio

    os.environ["WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"] = "true"

    ledger = InMemoryLedger()
    svc = build_entity_stitch_service_from_env(ledger=ledger)
    assert svc is not None
    schema_shape = svc.strategies.get("schema_shape")
    assert schema_shape is not None
    lookup = schema_shape.parent_table_columns_lookup
    assert lookup is not None
    result = asyncio.run(lookup("source_a", "table_x"))
    assert result == []
