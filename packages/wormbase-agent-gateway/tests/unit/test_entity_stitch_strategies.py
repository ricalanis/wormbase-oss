"""L8 Sub-wave B — per-strategy tests.

Pins each of the 3 strategies' behaviour in isolation:

  * :class:`NameMatchEntityStrategy` — cross-axis chain (semantic-type
    anchor via reused L6 Protocol) + fuzzy-name fallback.
  * :class:`SampleOverlapEntityStrategy` — Jaccard via reused L7
    SamplerProtocol; honest stub on empty samples.
  * :class:`SchemaShapeEntityStrategy` — parent-table structural
    similarity on bare catalog metadata.

Each strategy is independently constructable + testable; the composite
is pinned separately in ``test_entity_stitch_composite.py``.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.column_classification import (
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.entity_stitch import (
    NameMatchEntityStrategy,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
    make_stitch_id,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0081")


# ---------------------------------------------------------------------------
# Fakes — reuse L6's ConfirmedSemanticTypeReader + L7's SamplerProtocol
# ---------------------------------------------------------------------------


class _FakeSemanticTypeReader:
    """L6's ConfirmedSemanticTypeReader Protocol — fake for L8 tests."""

    def __init__(
        self,
        types: dict[
            tuple[str, str], list[ConfirmedSemanticTypeRecord],
        ] | None = None,
    ) -> None:
        self.types = types or {}
        self.calls: list[tuple[str, str, UUID]] = []

    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        self.calls.append((table_id, column, company_id))
        return self.types.get((table_id, column), [])


class _FakeSampler:
    """L7's SamplerProtocol — fake for L8 tests."""

    def __init__(
        self,
        samples: dict[tuple[str, str], set[str]] | None = None,
    ) -> None:
        self.samples = samples or {}

    async def sample_column(self, table_id, column, n):
        return self.samples.get((table_id, column), set())

    async def estimate_table_size(self, table_id):
        return 0


class _NoopSampler:
    """The production NoopSampler shape — always returns empty."""

    async def sample_column(self, table_id, column, n):
        return set()

    async def estimate_table_size(self, table_id):
        return 0


# ---------------------------------------------------------------------------
# NameMatchEntityStrategy — semantic-type anchor path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_match_anchors_on_shared_l5_semantic_type_to_person() -> None:
    """Both endpoints L5-confirmed as ``email`` → propose at 0.90;
    entity_kind=person."""
    reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-stripe-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("salesforce.contacts", "email_address"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-sf-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=reader,
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email_address",
        },
    )
    anchor_proposals = [p for p in out if p.upstream_semantic_type_id is not None]
    assert len(anchor_proposals) == 1
    p = anchor_proposals[0]
    assert p.entity_kind == "person"
    assert p.confidence == 0.90
    assert p.strategy == "name_match"
    assert p.upstream_semantic_type_id == "t-stripe-email"


@pytest.mark.asyncio
async def test_name_match_anchors_business_id_to_organization() -> None:
    """Shared ``business_id`` → entity_kind=organization."""
    reader = _FakeSemanticTypeReader(types={
        ("stripe.subs", "customer_id"): [
            ConfirmedSemanticTypeRecord(
                type_id="t1", semantic_type="business_id",
                confidence=0.85, strategy="column_name",
            ),
        ],
        ("salesforce.accounts", "external_id"): [
            ConfirmedSemanticTypeRecord(
                type_id="t2", semantic_type="business_id",
                confidence=0.85, strategy="column_name",
            ),
        ],
    })
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=reader,
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.subs",
            "column": "customer_id",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.accounts",
            "column": "external_id",
        },
    )
    anchor = [p for p in out if p.upstream_semantic_type_id is not None]
    assert len(anchor) == 1
    assert anchor[0].entity_kind == "organization"


@pytest.mark.asyncio
async def test_name_match_no_shared_type_no_anchor_proposal() -> None:
    """Different L5 types on each endpoint → no anchor proposal."""
    reader = _FakeSemanticTypeReader(types={
        ("a.t1", "c1"): [
            ConfirmedSemanticTypeRecord(
                type_id="t1", semantic_type="email",
                confidence=0.9, strategy="column_name",
            ),
        ],
        ("b.t2", "c2"): [
            ConfirmedSemanticTypeRecord(
                type_id="t2", semantic_type="phone_e164",
                confidence=0.9, strategy="column_name",
            ),
        ],
    })
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=reader,
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t1", "column": "c1"},
        column_b={"source_id": "b", "table_id": "b.t2", "column": "c2"},
    )
    assert all(p.upstream_semantic_type_id is None for p in out)


# ---------------------------------------------------------------------------
# NameMatchEntityStrategy — fuzzy-name fallback (independent of L5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_match_fuzzy_path_fires_on_similar_names() -> None:
    """Similar column names (Levenshtein ≥ 0.7) → fuzzy proposal at 0.60-0.75."""
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "customer_email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "customer_emai",  # typo
        },
    )
    fuzzy = [p for p in out if p.upstream_semantic_type_id is None]
    assert len(fuzzy) >= 1
    assert fuzzy[0].entity_kind == "other"
    assert 0.60 <= fuzzy[0].confidence <= 0.75


@pytest.mark.asyncio
async def test_name_match_fuzzy_skips_dissimilar_names() -> None:
    """Very different column names → no fuzzy proposal."""
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "totally_xyz"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "completely_abc"},
    )
    fuzzy = [p for p in out if p.upstream_semantic_type_id is None]
    assert fuzzy == []


@pytest.mark.asyncio
async def test_name_match_fuzzy_works_when_anchor_disabled() -> None:
    """``use_semantic_type_anchor=False`` → fuzzy path still fires.

    Validates the strategy is constructable + productive without any
    L5 cross-axis reader.
    """
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=None,
        use_semantic_type_anchor=False,
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert len(out) >= 1
    assert out[0].upstream_semantic_type_id is None


@pytest.mark.asyncio
async def test_name_match_skips_empty_column_names() -> None:
    """Empty column → no proposal."""
    strategy = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": ""},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert out == []


# ---------------------------------------------------------------------------
# SampleOverlapEntityStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_overlap_fires_on_full_overlap_at_max_confidence() -> None:
    """Identical sample sets → Jaccard 1.0 → MAX_CONFIDENCE=0.85."""
    samples = {"a@x.com", "b@x.com", "c@x.com"}
    sampler = _FakeSampler(samples={
        ("stripe.customers", "email"): samples,
        ("salesforce.contacts", "email_address"): samples,
    })
    strategy = SampleOverlapEntityStrategy(sampler=sampler)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email_address",
        },
    )
    assert len(out) == 1
    assert out[0].confidence == 0.85
    assert out[0].strategy == "sample_overlap"


@pytest.mark.asyncio
async def test_sample_overlap_threshold_floor_at_min_confidence() -> None:
    """Jaccard exactly at threshold (0.5) → MIN_CONFIDENCE=0.50."""
    sampler = _FakeSampler(samples={
        ("a.t", "c"): {"x", "y", "z", "p"},
        # Jaccard = 2 / 6 = 0.33 (below threshold) — no proposal
        ("b.t", "c"): {"x", "y", "q", "r"},
    })
    strategy = SampleOverlapEntityStrategy(sampler=sampler)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "c"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "c"},
    )
    assert out == []


@pytest.mark.asyncio
async def test_sample_overlap_honest_stub_on_empty_samples() -> None:
    """NoopSampler → empty sets → no proposals (honest stub posture)."""
    strategy = SampleOverlapEntityStrategy(sampler=_NoopSampler())
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert out == []


@pytest.mark.asyncio
async def test_sample_overlap_default_entity_kind_is_other() -> None:
    """Sample overlap alone does not disambiguate entity_kind."""
    samples = {"x@y.com"}
    sampler = _FakeSampler(samples={
        ("a.t", "c"): samples,
        ("b.t", "c"): samples,
    })
    strategy = SampleOverlapEntityStrategy(sampler=sampler)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "c"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "c"},
    )
    assert len(out) == 1
    assert out[0].entity_kind == "other"


# ---------------------------------------------------------------------------
# SchemaShapeEntityStrategy
# ---------------------------------------------------------------------------


def _make_dict_lookup(columns_by_table: dict[tuple[str, str], list[str]]):
    async def _lookup(source_id: str, table_id: str) -> list[str]:
        return columns_by_table.get((source_id, table_id), [])
    return _lookup


@pytest.mark.asyncio
async def test_schema_shape_fires_when_tables_align_and_pair_matches() -> None:
    """Parent tables have same columns + input column appears on both →
    propose at scaled confidence."""
    lookup = _make_dict_lookup({
        ("stripe", "stripe.customers"): ["id", "email", "name", "created_at"],
        ("salesforce", "salesforce.contacts"): [
            "id", "email", "name", "created_at",
        ],
    })
    strategy = SchemaShapeEntityStrategy(parent_table_columns_lookup=lookup)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email",
        },
    )
    assert len(out) == 1
    assert out[0].strategy == "schema_shape"
    # 4/4 name overlap → confidence ~ 0.75 (MAX)
    assert 0.50 <= out[0].confidence <= 0.75
    assert out[0].entity_kind == "other"


@pytest.mark.asyncio
async def test_schema_shape_skips_when_column_names_differ_at_input_pair() -> None:
    """Even if parent tables align, mismatched input column names → no proposal
    (the pair is a bystander; matching-name pairs get their own propose calls).
    """
    lookup = _make_dict_lookup({
        ("a", "a.t"): ["id", "email", "name"],
        ("b", "b.t"): ["id", "email", "name"],
    })
    strategy = SchemaShapeEntityStrategy(parent_table_columns_lookup=lookup)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "name"},
    )
    assert out == []


@pytest.mark.asyncio
async def test_schema_shape_skips_on_dissimilar_tables() -> None:
    """Wildly different column shapes → no proposal."""
    lookup = _make_dict_lookup({
        ("a", "a.t"): ["x", "y", "z"],
        ("b", "b.t"): ["foo", "bar", "baz", "qux", "quux"],  # delta=2 ok
    })
    strategy = SchemaShapeEntityStrategy(parent_table_columns_lookup=lookup)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "x"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "x"},
    )
    # name overlap = 0/8 = 0.0 → below threshold
    assert out == []


@pytest.mark.asyncio
async def test_schema_shape_skips_when_count_delta_exceeds_max() -> None:
    """Column-count delta > 2 → no proposal even if name set looks fine."""
    lookup = _make_dict_lookup({
        ("a", "a.t"): ["id", "email", "name"],
        ("b", "b.t"): [
            "id", "email", "name", "x1", "x2", "x3", "x4",
        ],
    })
    strategy = SchemaShapeEntityStrategy(parent_table_columns_lookup=lookup)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert out == []


@pytest.mark.asyncio
async def test_schema_shape_no_op_without_lookup() -> None:
    """No lookup callback → strategy is a no-op."""
    strategy = SchemaShapeEntityStrategy(parent_table_columns_lookup=None)
    out = await strategy.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert out == []


# ---------------------------------------------------------------------------
# Stitch-id stability across strategies (composite-relevant)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategies_produce_same_stitch_id_for_same_pair() -> None:
    """Two different strategies' proposals on the same pair share stitch_id —
    the composite can merge them. Same logical pair (in either argument
    order) → same id."""
    samples = {"a@x.com", "b@x.com"}
    sampler = _FakeSampler(samples={
        ("stripe.customers", "email"): samples,
        ("salesforce.contacts", "email"): samples,
    })
    so = SampleOverlapEntityStrategy(sampler=sampler)
    nm = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(types={
            ("stripe.customers", "email"): [
                ConfirmedSemanticTypeRecord(
                    type_id="t1", semantic_type="email",
                    confidence=0.95, strategy="column_name",
                ),
            ],
            ("salesforce.contacts", "email"): [
                ConfirmedSemanticTypeRecord(
                    type_id="t2", semantic_type="email",
                    confidence=0.95, strategy="column_name",
                ),
            ],
        }),
    )

    col_a = {
        "source_id": "stripe", "table_id": "stripe.customers",
        "column": "email",
    }
    col_b = {
        "source_id": "salesforce", "table_id": "salesforce.contacts",
        "column": "email",
    }

    out_so = await so.propose(
        company_id=_COMPANY_ID, column_a=col_a, column_b=col_b,
    )
    out_nm = await nm.propose(
        company_id=_COMPANY_ID, column_a=col_a, column_b=col_b,
    )
    # Reversed order — same stitch_id (canonicalised internally)
    out_so_rev = await so.propose(
        company_id=_COMPANY_ID, column_a=col_b, column_b=col_a,
    )

    expected = make_stitch_id(src_a=col_a, src_b=col_b)
    assert out_so[0].stitch_id == expected
    assert out_nm[0].stitch_id == expected
    assert out_so_rev[0].stitch_id == expected
