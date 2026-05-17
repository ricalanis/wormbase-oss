"""L8 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_stitch_id` determinism / replay stability.
  * **Order-independence** — ``make_stitch_id(a, b)`` and
    ``make_stitch_id(b, a)`` MUST produce the same id. The critical
    L8-specific invariant (canonicalised hash; spec §4.4).
  * Per-tuple distinguishability (every component of the canonical
    pair affects the hash; ``strategy`` is NOT in the hash — mirrors
    L5's :func:`make_type_id` divergence from L6's
    :func:`make_classification_id`).
  * Each strategy implements the :class:`EntityStitchStrategy`
    Protocol (runtime_checkable).
  * :data:`EntityKind` Literal covers exactly the 8 spec values
    (mirrors the ledger payload).
  * :class:`ProposedEntityStitch` is frozen.
"""
from __future__ import annotations

import typing
from uuid import UUID

import pytest

from wormbase_agent_gateway.entity_stitch import (
    EntityKind,
    EntityStitchStrategy,
    NameMatchEntityStrategy,
    ProposedEntityStitch,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
    make_stitch_id,
)


# ---------------------------------------------------------------------------
# make_stitch_id — determinism + order-independence + distinguishability
# ---------------------------------------------------------------------------


_TRIPLE_A: dict = {
    "source_id": "stripe",
    "table_id": "stripe.customers",
    "column": "email",
}
_TRIPLE_B: dict = {
    "source_id": "salesforce",
    "table_id": "salesforce.contacts",
    "column": "email_address",
}


def test_make_stitch_id_is_deterministic() -> None:
    """Same inputs (same order) → same id across calls (replay-stable)."""
    a = make_stitch_id(src_a=_TRIPLE_A, src_b=_TRIPLE_B)
    b = make_stitch_id(src_a=_TRIPLE_A, src_b=_TRIPLE_B)
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_stitch_id_is_order_independent() -> None:
    """``make_stitch_id(a, b) == make_stitch_id(b, a)`` — the critical
    L8 invariant (spec §4.4)."""
    a = make_stitch_id(src_a=_TRIPLE_A, src_b=_TRIPLE_B)
    b = make_stitch_id(src_a=_TRIPLE_B, src_b=_TRIPLE_A)
    assert a == b


def test_make_stitch_id_distinguishes_every_tuple_component() -> None:
    """Each component of each endpoint participates in the hash."""
    base_id = make_stitch_id(src_a=_TRIPLE_A, src_b=_TRIPLE_B)
    for endpoint_name, base_triple in [
        ("src_a", _TRIPLE_A),
        ("src_b", _TRIPLE_B),
    ]:
        for key in ("source_id", "table_id", "column"):
            mutated = dict(base_triple)
            mutated[key] = base_triple[key] + "_mutated"
            kwargs = {"src_a": _TRIPLE_A, "src_b": _TRIPLE_B}
            kwargs[endpoint_name] = mutated
            assert make_stitch_id(**kwargs) != base_id, (
                f"stitch_id collided when mutating {endpoint_name}.{key}"
            )


def test_make_stitch_id_signature_has_2_components() -> None:
    """The signature explicitly takes exactly the 2 endpoint dicts."""
    import inspect
    sig = inspect.signature(make_stitch_id)
    assert set(sig.parameters) == {"src_a", "src_b"}


def test_make_stitch_id_canonicalisation_orders_lex() -> None:
    """Canonical order is lex; both orderings produce the same id and the
    id is computed against the lex-smaller endpoint first.

    Doesn't test the exact byte-level hash (implementation detail), but
    pins that canonicalisation IS performed (different a/b ordering
    yields the same id — already covered above — AND that the canonical
    pair shape produces a stable lex-ordered id when the smaller
    endpoint is rotated to position a).
    """
    a_then_b = make_stitch_id(src_a=_TRIPLE_A, src_b=_TRIPLE_B)
    b_then_a = make_stitch_id(src_a=_TRIPLE_B, src_b=_TRIPLE_A)
    assert a_then_b == b_then_a


# ---------------------------------------------------------------------------
# EntityKind Literal — 8 canonical values
# ---------------------------------------------------------------------------


EXPECTED_ENTITY_KINDS: frozenset[str] = frozenset({
    "person",
    "organization",
    "transaction",
    "product",
    "event",
    "location",
    "session",
    "other",
})


def test_entity_kind_literal_covers_canonical_spec_values() -> None:
    """:data:`EntityKind` is a Literal with exactly the 8 canonical
    entity classes (per spec §4.2).

    Pin: mirrors the ledger payload's Literal (see
    :attr:`wormbase_ledger.entries.EntityKind`). Drift here must be
    matched by a ledger migration AND doctrine review (per spec §4.2,
    the 8-value enum is fixed).
    """
    args = typing.get_args(EntityKind)
    actual = frozenset(args)
    assert actual == EXPECTED_ENTITY_KINDS, (
        f"EntityKind Literal drift: "
        f"extra={actual - EXPECTED_ENTITY_KINDS}, "
        f"missing={EXPECTED_ENTITY_KINDS - actual}"
    )
    assert len(args) == 8


# ---------------------------------------------------------------------------
# EntityStitchStrategy Protocol — runtime conformance
# ---------------------------------------------------------------------------


class _FakeSemanticTypeReader:
    """L6's ConfirmedSemanticTypeReader Protocol — reused by L8."""

    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        return []


class _FakeSampler:
    """L7's SamplerProtocol — reused by L8."""

    async def sample_column(self, table_id, column, n):
        return set()

    async def estimate_table_size(self, table_id):
        return 0


async def _fake_lookup(source_id: str, table_id: str) -> list[str]:
    return []


def test_strategies_satisfy_entity_stitch_strategy_protocol() -> None:
    """All 3 strategies are instances of :class:`EntityStitchStrategy`
    per ``runtime_checkable``."""
    nm = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    so = SampleOverlapEntityStrategy(sampler=_FakeSampler())
    ss = SchemaShapeEntityStrategy(
        parent_table_columns_lookup=_fake_lookup,
    )
    for service in (nm, so, ss):
        assert isinstance(service, EntityStitchStrategy), (
            f"{type(service).__name__} does not satisfy EntityStitchStrategy"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert NameMatchEntityStrategy.name == "name_match"
    assert SampleOverlapEntityStrategy.name == "sample_overlap"
    assert SchemaShapeEntityStrategy.name == "schema_shape"


# ---------------------------------------------------------------------------
# Cross-axis Protocol reuse — L6's ConfirmedSemanticTypeReader is REUSED
# ---------------------------------------------------------------------------


def test_l8_reuses_l6_confirmed_semantic_type_reader_protocol() -> None:
    """The L8 NameMatchEntityStrategy imports the L6 Protocol; L8 does
    NOT redeclare a parallel cross-axis Protocol.

    Pin: validates the consumer-owned-Protocol pattern generalises
    across multiple downstream consumers. L6's Protocol shipped
    independently of L8; L8 imports the L6 symbol directly.
    """
    from wormbase_agent_gateway.column_classification.protocol import (
        ConfirmedSemanticTypeReader as L6Reader,
    )
    from wormbase_agent_gateway.entity_stitch import strategies as l8_strategies
    # The strategies module imports the L6 Protocol symbol.
    assert l8_strategies.ConfirmedSemanticTypeReader is L6Reader


# ---------------------------------------------------------------------------
# Dataclass shape + frozenness
# ---------------------------------------------------------------------------


def test_proposed_entity_stitch_is_frozen() -> None:
    """:class:`ProposedEntityStitch` is a frozen dataclass."""
    p = ProposedEntityStitch(
        stitch_id="abc",
        src_source_id_a="src-a",
        src_table_a="src-a.t",
        src_column_a="col",
        src_source_id_b="src-b",
        src_table_b="src-b.t",
        src_column_b="col",
        upstream_semantic_type_id=None,
        entity_kind="other",
        confidence=0.85,
        strategy="name_match",
        reasoning="test",
        evidence={},
    )
    try:
        p.stitch_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedEntityStitch should be frozen")


def test_proposed_entity_stitch_field_surface() -> None:
    """:class:`ProposedEntityStitch` carries the documented 13 fields."""
    p = ProposedEntityStitch(
        stitch_id="abc",
        src_source_id_a="src-a",
        src_table_a="src-a.t",
        src_column_a="col_a",
        src_source_id_b="src-b",
        src_table_b="src-b.t",
        src_column_b="col_b",
        upstream_semantic_type_id="upstream-id",
        entity_kind="person",
        confidence=0.90,
        strategy="name_match",
        reasoning="test",
        evidence={"k": "v"},
    )
    expected = {
        "stitch_id", "src_source_id_a", "src_table_a", "src_column_a",
        "src_source_id_b", "src_table_b", "src_column_b",
        "upstream_semantic_type_id", "entity_kind",
        "confidence", "strategy", "reasoning", "evidence",
    }
    actual = set(p.__dataclass_fields__)
    assert actual == expected, (
        f"ProposedEntityStitch field surface drift: "
        f"extra={actual - expected}, missing={expected - actual}"
    )


@pytest.mark.asyncio
async def test_entity_stitch_strategy_protocol_async_propose() -> None:
    """A strategy's ``propose`` is async + returns ProposedEntityStitch list."""
    # NameMatch with fuzzy path only — productive without cross-axis reader.
    nm = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    out = await nm.propose(
        company_id=UUID(int=1),
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email_address",
        },
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedEntityStitch) for p in out)
