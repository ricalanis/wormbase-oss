"""L6 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_classification_id` determinism / replay stability.
  * Per-tuple distinguishability (every component of the canonical
    tuple affects the hash; ``strategy`` IS in the hash unlike L5's
    :func:`make_type_id`).
  * Each strategy implements the :class:`ColumnClassificationStrategy`
    Protocol (runtime_checkable).
  * :class:`ConfirmedSemanticTypeReader` is a runtime_checkable Protocol
    (the new cross-axis read Protocol; second instance after L4's
    :class:`LineageEdgeReader`).
  * :data:`ClassificationLevel` Literal covers exactly the 5 spec
    values (mirrors the ledger payload).
  * :class:`ProposedColumnClassification` is frozen.
  * :class:`ConfirmedSemanticTypeRecord` is frozen.
"""
from __future__ import annotations

import typing
from uuid import UUID, uuid4

import pytest

from wormbase_agent_gateway.column_classification import (
    ClassificationLevel,
    ColumnClassificationStrategy,
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
    DomainDefaultClassificationStrategy,
    DomainDefaultReader,
    NamingPatternClassificationStrategy,
    ProposedColumnClassification,
    SemanticTypeClassificationStrategy,
    make_classification_id,
)


# ---------------------------------------------------------------------------
# make_classification_id — determinism + distinguishability
# ---------------------------------------------------------------------------


def test_make_classification_id_is_deterministic() -> None:
    """Same inputs → same id across calls (replay-stable)."""
    a = make_classification_id(
        table_id="src-001.public.users",
        column="ssn",
        classification_level="regulated",
        strategy="naming_pattern",
    )
    b = make_classification_id(
        table_id="src-001.public.users",
        column="ssn",
        classification_level="regulated",
        strategy="naming_pattern",
    )
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_classification_id_distinguishes_every_tuple_component() -> None:
    """Each of the 4 inputs participates in the hash distinctly."""
    base = dict(
        table_id="src-001.public.users",
        column="ssn",
        classification_level="regulated",
        strategy="naming_pattern",
    )
    base_id = make_classification_id(**base)
    for key, mutated in [
        ("table_id", "src-001.public.other"),
        ("column", "email"),
        ("classification_level", "pii"),
        ("strategy", "semantic_type"),
    ]:
        kwargs = dict(base)
        kwargs[key] = mutated
        assert make_classification_id(**kwargs) != base_id, (
            f"classification_id collided when mutating {key}"
        )


def test_make_classification_id_strategy_in_hash_diverges_from_l5() -> None:
    """Same (table, column, level) but different strategy → different id.

    Critical divergence from L5's :func:`make_type_id` which OMITS
    strategy. L6 wants each strategy's per-column-per-level proposal
    to be its own projection row (per spec §4.4) so the admin queue
    compares strategies side-by-side.
    """
    a = make_classification_id(
        table_id="t", column="c", classification_level="pii",
        strategy="semantic_type",
    )
    b = make_classification_id(
        table_id="t", column="c", classification_level="pii",
        strategy="naming_pattern",
    )
    assert a != b


def test_make_classification_id_distinct_levels_yield_distinct_ids() -> None:
    """Same (table, column, strategy) but different level → different id."""
    a = make_classification_id(
        table_id="t", column="c", classification_level="pii",
        strategy="naming_pattern",
    )
    b = make_classification_id(
        table_id="t", column="c", classification_level="regulated",
        strategy="naming_pattern",
    )
    assert a != b


def test_make_classification_id_signature_has_4_components() -> None:
    """The signature explicitly takes exactly the 4 hash components."""
    import inspect
    sig = inspect.signature(make_classification_id)
    assert set(sig.parameters) == {
        "table_id", "column", "classification_level", "strategy",
    }


# ---------------------------------------------------------------------------
# ClassificationLevel Literal — 5 canonical values
# ---------------------------------------------------------------------------


EXPECTED_CLASSIFICATION_LEVELS: frozenset[str] = frozenset({
    "public",
    "internal",
    "confidential",
    "pii",
    "regulated",
})


def test_classification_level_literal_covers_canonical_spec_values() -> None:
    """:data:`ClassificationLevel` is a Literal with exactly the 5 canonical
    governance levels (per CLAUDE.md §"Ledger-native governance").

    Pin: mirrors the ledger payload's Literal (see
    :attr:`wormbase_ledger.entries.ColumnClassificationProposedPayload.classification_level`).
    Drift here must be matched by a ledger migration AND doctrine review
    (per spec §4.2, the 5-value enum is fixed).
    """
    args = typing.get_args(ClassificationLevel)
    actual = frozenset(args)
    assert actual == EXPECTED_CLASSIFICATION_LEVELS, (
        f"ClassificationLevel Literal drift: "
        f"extra={actual - EXPECTED_CLASSIFICATION_LEVELS}, "
        f"missing={EXPECTED_CLASSIFICATION_LEVELS - actual}"
    )
    assert len(args) == 5


# ---------------------------------------------------------------------------
# ColumnClassificationStrategy Protocol — runtime conformance
# ---------------------------------------------------------------------------


class _FakeSemanticTypeReader:
    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        return []


class _FakeDomainDefaultReader:
    async def get_classification_default_for_table(
        self, *, table_id, company_id,
    ):
        return None


def test_strategies_satisfy_column_classification_strategy_protocol() -> None:
    """All 3 strategies are instances of :class:`ColumnClassificationStrategy`
    per ``runtime_checkable``."""
    np_strategy = NamingPatternClassificationStrategy()
    st_strategy = SemanticTypeClassificationStrategy(
        semantic_type_reader=_FakeSemanticTypeReader(),
    )
    dd_strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=_FakeDomainDefaultReader(),
    )

    for service in (np_strategy, st_strategy, dd_strategy):
        assert isinstance(service, ColumnClassificationStrategy), (
            f"{type(service).__name__} does not satisfy "
            f"ColumnClassificationStrategy"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert NamingPatternClassificationStrategy.name == "naming_pattern"
    assert SemanticTypeClassificationStrategy.name == "semantic_type"
    assert DomainDefaultClassificationStrategy.name == "domain_default"


# ---------------------------------------------------------------------------
# ConfirmedSemanticTypeReader — runtime_checkable Protocol (new cross-axis)
# ---------------------------------------------------------------------------


def test_confirmed_semantic_type_reader_is_runtime_checkable() -> None:
    """The new cross-axis Protocol is runtime_checkable so adapters can
    be verified at boot time (mirrors L4's :class:`LineageEdgeReader`).

    Second instance of the cross-axis-read pattern (after L4→L3). The
    canonical shape is: consuming axis owns the Protocol, minimum
    query surface, minimum-field record dataclass on the consumer side.
    """
    reader = _FakeSemanticTypeReader()
    assert isinstance(reader, ConfirmedSemanticTypeReader)


def test_domain_default_reader_is_runtime_checkable() -> None:
    """DomainDefaultReader is also runtime_checkable (used by domain_default
    strategy; consumer-owned Protocol for minimum coupling)."""
    reader = _FakeDomainDefaultReader()
    assert isinstance(reader, DomainDefaultReader)


# ---------------------------------------------------------------------------
# Dataclass shape + frozenness
# ---------------------------------------------------------------------------


def test_proposed_column_classification_is_frozen() -> None:
    """:class:`ProposedColumnClassification` is a frozen dataclass."""
    p = ProposedColumnClassification(
        classification_id="abc",
        table_id="t1",
        column="c1",
        classification_level="pii",
        upstream_semantic_type_id=None,
        confidence=0.85,
        strategy="naming_pattern",
        reasoning="test",
        evidence={},
    )
    try:
        p.classification_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedColumnClassification should be frozen")


def test_proposed_column_classification_field_surface() -> None:
    """:class:`ProposedColumnClassification` carries the documented 9 fields."""
    p = ProposedColumnClassification(
        classification_id="abc",
        table_id="t1",
        column="c1",
        classification_level="pii",
        upstream_semantic_type_id="upstream-id",
        confidence=0.85,
        strategy="semantic_type",
        reasoning="test",
        evidence={"k": "v"},
    )
    expected = {
        "classification_id", "table_id", "column", "classification_level",
        "upstream_semantic_type_id", "confidence", "strategy",
        "reasoning", "evidence",
    }
    actual = set(p.__dataclass_fields__)
    assert actual == expected, (
        f"ProposedColumnClassification field surface drift: "
        f"extra={actual - expected}, missing={expected - actual}"
    )


def test_confirmed_semantic_type_record_is_frozen_and_minimum_coupling() -> None:
    """:class:`ConfirmedSemanticTypeRecord` is a frozen dataclass with
    exactly the 4 minimum-coupling fields L6 needs from L5's full payload.

    Pin: minimum-coupling principle (mirrors L4's :class:`LineageEdgeRecord`).
    Adding a field to L5's full payload must NOT force a change here.
    """
    r = ConfirmedSemanticTypeRecord(
        type_id="abc",
        semantic_type="pii_ssn",
        confidence=0.95,
        strategy="column_name",
    )
    try:
        r.type_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ConfirmedSemanticTypeRecord should be frozen")
    expected = {"type_id", "semantic_type", "confidence", "strategy"}
    actual = set(r.__dataclass_fields__)
    assert actual == expected


@pytest.mark.asyncio
async def test_column_classification_strategy_protocol_async_propose() -> None:
    """A column-classification strategy's ``propose`` is async + returns
    proposals."""
    np_strategy = NamingPatternClassificationStrategy()
    out = await np_strategy.propose(
        table_id="src-001.public.users", column="user_ssn",
        company_id=UUID(int=1),
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedColumnClassification) for p in out)
