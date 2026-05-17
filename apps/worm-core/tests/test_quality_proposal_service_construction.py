"""L7 Sub-wave C — env-driven QualityProposalService construction tests.

Pins the env-knob → composite-strategy contract exposed by
``build_quality_proposal_service_from_env`` and
``compose_quality_reactivity_if_enabled`` in
``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.

Coverage:

  * Default OFF (no env knob set) → returns None; reactivity is not
    registered; reactivity count when L7 disabled stays at the
    pre-L7 baseline.
  * ENABLED → composite carries SchemaPattern; DbtTests wired at
    compose-time; HistoricalStats stays None by default.
  * HISTORICAL_STATS_ENABLED=true → HistoricalStats wired with
    NoopHistoricalStatsReader.
  * Numeric knobs (freshness default, low-cardinality, propose window)
    flow through to the constructed strategies + reactivity.
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
    build_quality_proposal_service_from_env,
    compose_quality_reactivity_if_enabled,
    is_quality_discovery_enabled,
    is_quality_historical_stats_enabled,
    is_quality_semantic_type_enabled,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000c0001")


@pytest.fixture
def clean_quality_env() -> Iterator[dict[str, str]]:
    """Strip every WORMBASE_QUALITY_* env knob for the duration of a test.

    Returns the original env so the test body can mutate via
    ``os.environ`` if needed.
    """
    keys = [
        "WORMBASE_QUALITY_DISCOVERY_ENABLED",
        "WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED",
        "WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED",
        "WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS",
        "WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS",
        "WORMBASE_QUALITY_LOW_CARDINALITY_MAX",
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


def test_default_off_returns_none(clean_quality_env: dict[str, str]) -> None:
    """Without the env knob, the factory returns None — byte-identical pre-L7."""
    assert is_quality_discovery_enabled() is False
    assert build_quality_proposal_service_from_env() is None


def test_enabled_composes_schema_pattern_by_default(
    clean_quality_env: dict[str, str],
) -> None:
    """Flipping the master knob composes SchemaPatternStrategy.

    DbtTests is left for the reactivity-compose step (needs ledger);
    HistoricalStats stays None by default.
    """
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    svc = build_quality_proposal_service_from_env()
    assert svc is not None
    assert svc.schema_pattern is not None
    assert svc.schema_pattern.name == "schema_pattern"
    # HistoricalStats is opt-in via a second knob.
    assert svc.historical_stats is None
    # DbtTests is wired post-build in compose_quality_reactivity_if_enabled.
    assert svc.dbt_tests is None


def test_historical_stats_env_knob_wires_strategy(
    clean_quality_env: dict[str, str],
) -> None:
    """Flipping the second knob composes HistoricalStats with NoopHistoricalStatsReader."""
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED"] = "true"

    assert is_quality_historical_stats_enabled() is True
    svc = build_quality_proposal_service_from_env()
    assert svc is not None
    assert svc.historical_stats is not None
    assert svc.historical_stats.name == "historical_stats"
    # NoopHistoricalStatsReader is the honest-stub today.
    from wormbase_core.quality_catalog_reader import NoopHistoricalStatsReader

    assert isinstance(svc.historical_stats.reader, NoopHistoricalStatsReader)


def test_freshness_default_env_knob_flows_through(
    clean_quality_env: dict[str, str],
) -> None:
    """Freshness-default env knob threads through to SchemaPatternStrategy."""
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS"] = "48"

    svc = build_quality_proposal_service_from_env()
    assert svc is not None
    assert svc.schema_pattern is not None
    assert svc.schema_pattern.freshness_default_hours == 48


def test_low_cardinality_env_knob_flows_through(
    clean_quality_env: dict[str, str],
) -> None:
    """Low-cardinality env knob threads through to SchemaPatternStrategy."""
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_QUALITY_LOW_CARDINALITY_MAX"] = "25"

    svc = build_quality_proposal_service_from_env()
    assert svc is not None
    assert svc.schema_pattern is not None
    assert svc.schema_pattern.low_cardinality_max == 25


def test_compose_quality_reactivity_default_off_returns_none(
    clean_quality_env: dict[str, str],
) -> None:
    """Default OFF → compose_quality_reactivity_if_enabled returns None.

    This is the byte-identical-when-disabled contract: when None comes
    back, cli.py skips reactivity_registry.register, preserving the
    pre-L7 boot graph.
    """
    ledger = InMemoryLedger()
    reactivity = compose_quality_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_compose_quality_reactivity_when_enabled_wires_dbt(
    clean_quality_env: dict[str, str],
) -> None:
    """When enabled, the reactivity is constructed with dbt_tests wired.

    DbtTests is wired at compose-time (not at env-build-time) because
    it needs ledger + company_id — the env knob path doesn't carry
    those.
    """
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    ledger = InMemoryLedger()
    reactivity = compose_quality_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    assert reactivity.id == "agent_gateway.quality_discovery"


def test_propose_window_env_knob_flows_through(
    clean_quality_env: dict[str, str],
) -> None:
    """Idempotency window env knob threads through to the factory.

    We verify by patching make_quality_discovery_reactivity to capture
    the kwarg.
    """
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS"] = "1234"

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        proposal_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["propose_window_seconds"] = propose_window_seconds
        captured["proposal_service"] = proposal_service
        captured["catalog_reader"] = catalog_reader

        # Return a sentinel; we only assert on captured kwargs.
        class _Sentinel:
            id = "agent_gateway.quality_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_quality_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        reactivity = compose_quality_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert reactivity is not None
        assert captured["propose_window_seconds"] == 1234
        assert captured["proposal_service"] is not None
        assert captured["catalog_reader"] is not None
        # DbtTests was wired in at compose-time before the factory call.
        assert captured["proposal_service"].dbt_tests is not None


# ---------------------------------------------------------------------------
# L5→L7 cross-axis chain (4th cross-axis chain) — sub-knob wiring
# ---------------------------------------------------------------------------


def test_semantic_type_default_off_no_strategy(
    clean_quality_env: dict[str, str],
) -> None:
    """Default-OFF byte-identical: SemanticType strategy is None on the composite
    when the sub-knob is unset. L7 stays in its pre-cross-axis posture."""
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    assert is_quality_semantic_type_enabled() is False
    ledger = InMemoryLedger()
    reactivity = compose_quality_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is not None
    # We can't easily reach the composite from the reactivity opaque
    # surface, so capture the proposal_service via the factory patch.
    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        proposal_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["proposal_service"] = proposal_service

        class _Sentinel:
            id = "agent_gateway.quality_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_quality_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        compose_quality_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        assert captured["proposal_service"].semantic_type is None


def test_semantic_type_enabled_wires_strategy(
    clean_quality_env: dict[str, str],
) -> None:
    """With the sub-knob on, SemanticTypeQualityCheckStrategy is wired
    with a :class:`LedgerConfirmedSemanticTypeReader`."""
    os.environ["WORMBASE_QUALITY_DISCOVERY_ENABLED"] = "true"
    os.environ["WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED"] = "true"
    assert is_quality_semantic_type_enabled() is True

    captured: dict[str, Any] = {}

    def _fake_factory(
        *,
        proposal_service: Any,
        catalog_reader: Any,
        propose_window_seconds: int,
    ) -> Any:
        captured["proposal_service"] = proposal_service

        class _Sentinel:
            id = "agent_gateway.quality_discovery"

        return _Sentinel()

    with patch(
        "wormbase_core.agent_gateway_construction.make_quality_discovery_reactivity",
        side_effect=_fake_factory,
    ):
        ledger = InMemoryLedger()
        compose_quality_reactivity_if_enabled(
            ledger=ledger, company_id=_COMPANY_ID,
        )
        from wormbase_agent_gateway.quality import (
            SemanticTypeQualityCheckStrategy,
        )
        from wormbase_core.column_classification_semantic_reader import (
            LedgerConfirmedSemanticTypeReader,
        )

        svc = captured["proposal_service"]
        assert svc.semantic_type is not None
        assert isinstance(svc.semantic_type, SemanticTypeQualityCheckStrategy)
        # Reader is the L6 adapter (3rd consumer; reused, not redeclared).
        assert isinstance(
            svc.semantic_type.confirmed_semantic_type_reader,
            LedgerConfirmedSemanticTypeReader,
        )


def test_semantic_type_sub_knob_requires_master_knob(
    clean_quality_env: dict[str, str],
) -> None:
    """Sub-knob on but master OFF → reactivity is None; cross-axis strategy
    never constructed. Byte-identical pre-L7 boot still holds."""
    os.environ["WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED"] = "true"
    assert is_quality_discovery_enabled() is False

    ledger = InMemoryLedger()
    reactivity = compose_quality_reactivity_if_enabled(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    assert reactivity is None


def test_ledger_confirmed_semantic_type_reader_is_3rd_consumer() -> None:
    """**Reader reuse pin**: ``LedgerConfirmedSemanticTypeReader`` is the
    SAME concrete adapter consumed by L6, L8, and L7.

    Pin: 3rd consumer of the same adapter (L6 = 1st, L8 = 2nd, L7 =
    3rd). Asserts the import path is the same symbol — no per-axis
    duplication of the adapter class. Validates the "extract once,
    reuse N times" doctrine for cross-axis reads.
    """
    from wormbase_core.column_classification_semantic_reader import (
        LedgerConfirmedSemanticTypeReader as l6_l8_l7,
    )

    # The L7 wire references the same symbol the L6 wire references.
    # If a future refactor split the adapter per-axis (anti-pattern),
    # this import would diverge.
    import wormbase_core.agent_gateway_construction as ag

    assert ag.LedgerConfirmedSemanticTypeReader is l6_l8_l7
