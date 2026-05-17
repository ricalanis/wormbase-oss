"""L6 Sub-wave B — strategies tests.

Pins per-strategy behaviour for the three column-classification
strategies:

  * :class:`SemanticTypeClassificationStrategy` — cross-axis to L5 via
    :class:`ConfirmedSemanticTypeReader`. Maps L5 semantic types to L6
    classification levels per spec §4.3.
  * :class:`NamingPatternClassificationStrategy` — productive today via
    regex over column names. Independent of L5.
  * :class:`DomainDefaultClassificationStrategy` — reads domain-pack
    defaults via :class:`DomainDefaultReader`.

Each strategy's productivity profile (productive-today /
empty-upstream / configured-only) is asserted explicitly.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.column_classification import (
    ConfirmedSemanticTypeRecord,
    DomainDefaultClassificationStrategy,
    NamingPatternClassificationStrategy,
    ProposedColumnClassification,
    SemanticTypeClassificationStrategy,
    make_classification_id,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0060")


# ---------------------------------------------------------------------------
# Fake readers
# ---------------------------------------------------------------------------


class _FakeSemanticTypeReader:
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


class _FakeDomainDefaultReader:
    def __init__(
        self,
        defaults: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        # table_id → (level, domain_id)
        self.defaults = defaults or {}
        self.calls: list[tuple[str, UUID]] = []

    async def get_classification_default_for_table(
        self, *, table_id, company_id,
    ):
        self.calls.append((table_id, company_id))
        return self.defaults.get(table_id)


# ---------------------------------------------------------------------------
# SemanticTypeClassificationStrategy — cross-axis mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_type_strategy_no_records_returns_empty() -> None:
    """No L5 confirmed types → no proposals (empty-upstream path)."""
    reader = _FakeSemanticTypeReader(types={})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t1", column="email", company_id=_COMPANY_ID,
    )
    assert out == []
    # Reader was consulted (cross-axis read fired)
    assert len(reader.calls) == 1


@pytest.mark.asyncio
async def test_semantic_type_strategy_pii_ssn_maps_to_regulated() -> None:
    """pii_ssn → regulated at 0.95 (HIPAA/SOC-2 scope)."""
    record = ConfirmedSemanticTypeRecord(
        type_id="upstream-ssn",
        semantic_type="pii_ssn",
        confidence=0.95,
        strategy="column_name",
    )
    reader = _FakeSemanticTypeReader(types={("t1", "ssn"): [record]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t1", column="ssn", company_id=_COMPANY_ID,
    )
    assert len(out) == 1
    p = out[0]
    assert p.classification_level == "regulated"
    assert p.confidence == pytest.approx(0.95)
    assert p.upstream_semantic_type_id == "upstream-ssn"
    assert p.strategy == "semantic_type"
    assert "pii_ssn" in p.reasoning


@pytest.mark.asyncio
async def test_semantic_type_strategy_pii_credit_card_maps_to_regulated() -> None:
    """pii_credit_card → regulated at 0.95 (PCI scope)."""
    record = ConfirmedSemanticTypeRecord(
        type_id="upstream-cc",
        semantic_type="pii_credit_card",
        confidence=0.95,
        strategy="value_pattern",
    )
    reader = _FakeSemanticTypeReader(types={("t1", "card_number"): [record]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t1", column="card_number", company_id=_COMPANY_ID,
    )
    assert len(out) == 1
    assert out[0].classification_level == "regulated"
    assert out[0].confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_semantic_type_strategy_email_maps_to_pii() -> None:
    """email → pii at 0.90."""
    record = ConfirmedSemanticTypeRecord(
        type_id="upstream-email",
        semantic_type="email",
        confidence=0.90,
        strategy="value_pattern",
    )
    reader = _FakeSemanticTypeReader(types={("t1", "email"): [record]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t1", column="email", company_id=_COMPANY_ID,
    )
    assert len(out) == 1
    assert out[0].classification_level == "pii"
    assert out[0].confidence == pytest.approx(0.90)
    assert out[0].upstream_semantic_type_id == "upstream-email"


@pytest.mark.asyncio
async def test_semantic_type_strategy_pii_name_address_map_to_pii() -> None:
    """pii_name / pii_address → pii at 0.95."""
    for st in ("pii_name", "pii_address"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"upstream-{st}", semantic_type=st,
            confidence=0.9, strategy="column_name",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "pii"
        assert out[0].confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_semantic_type_strategy_phones_map_to_pii() -> None:
    """phone_e164 / phone_us → pii at 0.90."""
    for st in ("phone_e164", "phone_us"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"id-{st}", semantic_type=st,
            confidence=0.85, strategy="value_pattern",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "pii"
        assert out[0].confidence == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_semantic_type_strategy_metrics_map_to_internal_070() -> None:
    """metric_* → internal at 0.70."""
    for st in ("metric_count", "metric_amount", "metric_rate"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"id-{st}", semantic_type=st,
            confidence=0.8, strategy="distribution",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "internal"
        assert out[0].confidence == pytest.approx(0.70)


@pytest.mark.asyncio
async def test_semantic_type_strategy_uuids_and_business_id_map_to_internal_060() -> None:
    """uuid_* / business_id → internal at 0.60."""
    for st in ("uuid_v4", "uuid_v7", "business_id"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"id-{st}", semantic_type=st,
            confidence=0.75, strategy="value_pattern",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "internal"
        assert out[0].confidence == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_semantic_type_strategy_geo_locale_map_to_public_085() -> None:
    """country_iso / language_iso / currency_iso → public at 0.85."""
    for st in ("country_iso", "language_iso", "currency_iso"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"id-{st}", semantic_type=st,
            confidence=0.85, strategy="value_pattern",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "public"
        assert out[0].confidence == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_semantic_type_strategy_temporal_map_to_internal_050() -> None:
    """iso_date / iso_datetime / unix_timestamp → internal at 0.50."""
    for st in ("iso_date", "iso_datetime", "unix_timestamp"):
        record = ConfirmedSemanticTypeRecord(
            type_id=f"id-{st}", semantic_type=st,
            confidence=0.85, strategy="column_name",
        )
        reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
        strategy = SemanticTypeClassificationStrategy(
            semantic_type_reader=reader,
        )
        out = await strategy.propose(
            table_id="t", column="c", company_id=_COMPANY_ID,
        )
        assert len(out) == 1
        assert out[0].classification_level == "internal"
        assert out[0].confidence == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_semantic_type_strategy_other_yields_no_proposal() -> None:
    """``other`` semantic type → no L6 proposal (unmapped)."""
    record = ConfirmedSemanticTypeRecord(
        type_id="id-other", semantic_type="other",
        confidence=0.5, strategy="distribution",
    )
    reader = _FakeSemanticTypeReader(types={("t", "c"): [record]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t", column="c", company_id=_COMPANY_ID,
    )
    assert out == []


@pytest.mark.asyncio
async def test_semantic_type_strategy_multiple_records_same_level_pick_max_confidence() -> None:
    """Two L5 records mapping to the SAME level → one proposal whose
    upstream_semantic_type_id is the highest-confidence contributor."""
    low = ConfirmedSemanticTypeRecord(
        type_id="upstream-lo", semantic_type="phone_us",
        confidence=0.70, strategy="value_pattern",
    )
    high = ConfirmedSemanticTypeRecord(
        type_id="upstream-hi", semantic_type="phone_e164",
        confidence=0.95, strategy="column_name",
    )
    reader = _FakeSemanticTypeReader(types={("t", "c"): [low, high]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t", column="c", company_id=_COMPANY_ID,
    )
    # Both map to pii; merged into one with upstream=highest-confidence.
    assert len(out) == 1
    assert out[0].classification_level == "pii"
    assert out[0].upstream_semantic_type_id == "upstream-hi"


@pytest.mark.asyncio
async def test_semantic_type_strategy_multiple_records_distinct_levels_emit_distinct() -> None:
    """Two L5 records mapping to DIFFERENT levels → two distinct proposals."""
    pii_record = ConfirmedSemanticTypeRecord(
        type_id="upstream-email", semantic_type="email",
        confidence=0.95, strategy="value_pattern",
    )
    public_record = ConfirmedSemanticTypeRecord(
        type_id="upstream-country", semantic_type="country_iso",
        confidence=0.85, strategy="value_pattern",
    )
    reader = _FakeSemanticTypeReader(
        types={("t", "c"): [pii_record, public_record]},
    )
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t", column="c", company_id=_COMPANY_ID,
    )
    levels = {p.classification_level for p in out}
    assert levels == {"pii", "public"}


@pytest.mark.asyncio
async def test_semantic_type_strategy_classification_id_is_canonical() -> None:
    """Proposal's classification_id matches :func:`make_classification_id`."""
    record = ConfirmedSemanticTypeRecord(
        type_id="upstream", semantic_type="pii_ssn",
        confidence=0.95, strategy="column_name",
    )
    reader = _FakeSemanticTypeReader(types={("t", "ssn"): [record]})
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    out = await strategy.propose(
        table_id="t", column="ssn", company_id=_COMPANY_ID,
    )
    expected = make_classification_id(
        table_id="t", column="ssn",
        classification_level="regulated", strategy="semantic_type",
    )
    assert out[0].classification_id == expected


@pytest.mark.asyncio
async def test_semantic_type_strategy_empty_table_or_column_no_op() -> None:
    """Empty table_id or column → no reader call, no proposals."""
    reader = _FakeSemanticTypeReader()
    strategy = SemanticTypeClassificationStrategy(semantic_type_reader=reader)
    assert await strategy.propose(
        table_id="", column="c", company_id=_COMPANY_ID,
    ) == []
    assert await strategy.propose(
        table_id="t", column="", company_id=_COMPANY_ID,
    ) == []
    assert reader.calls == []


# ---------------------------------------------------------------------------
# NamingPatternClassificationStrategy — independent of L5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_naming_pattern_strategy_secret_columns_confidential() -> None:
    """``*_secret``, ``*_password``, ``*_api_key``, ``*_token`` →
    confidential at 0.95."""
    strategy = NamingPatternClassificationStrategy()
    for col in ("api_secret", "user_password", "stripe_api_key", "auth_token"):
        out = await strategy.propose(
            table_id="t", column=col, company_id=_COMPANY_ID,
        )
        assert any(
            p.classification_level == "confidential" and
            p.confidence == pytest.approx(0.95)
            for p in out
        ), f"missing confidential proposal for {col!r}: {out}"
        # No upstream link for naming_pattern strategy
        assert all(p.upstream_semantic_type_id is None for p in out)


@pytest.mark.asyncio
async def test_naming_pattern_strategy_ssn_tax_id_regulated() -> None:
    """``*_ssn``, ``*_tax_id`` → regulated at 0.95."""
    strategy = NamingPatternClassificationStrategy()
    for col in ("user_ssn", "ssn", "user_tax_id", "tax_id"):
        out = await strategy.propose(
            table_id="t", column=col, company_id=_COMPANY_ID,
        )
        assert any(
            p.classification_level == "regulated" and
            p.confidence == pytest.approx(0.95)
            for p in out
        ), f"missing regulated proposal for {col!r}: {out}"


@pytest.mark.asyncio
async def test_naming_pattern_strategy_internal_naming_convention() -> None:
    """``*_internal_*`` → internal at 0.80."""
    strategy = NamingPatternClassificationStrategy()
    out = await strategy.propose(
        table_id="t", column="company_internal_score",
        company_id=_COMPANY_ID,
    )
    assert any(
        p.classification_level == "internal" and
        p.confidence == pytest.approx(0.80)
        for p in out
    )


@pytest.mark.asyncio
async def test_naming_pattern_strategy_public_naming_convention() -> None:
    """``*_public_*`` → public at 0.85."""
    strategy = NamingPatternClassificationStrategy()
    out = await strategy.propose(
        table_id="t", column="user_public_bio", company_id=_COMPANY_ID,
    )
    assert any(
        p.classification_level == "public" and
        p.confidence == pytest.approx(0.85)
        for p in out
    )


@pytest.mark.asyncio
async def test_naming_pattern_strategy_no_match_returns_empty() -> None:
    """Column name with no pattern match → empty proposal list."""
    strategy = NamingPatternClassificationStrategy()
    out = await strategy.propose(
        table_id="t", column="some_random_thing", company_id=_COMPANY_ID,
    )
    assert out == []


@pytest.mark.asyncio
async def test_naming_pattern_strategy_classification_id_is_canonical() -> None:
    """Proposal's classification_id matches :func:`make_classification_id`."""
    strategy = NamingPatternClassificationStrategy()
    out = await strategy.propose(
        table_id="t", column="user_ssn", company_id=_COMPANY_ID,
    )
    p = out[0]
    expected = make_classification_id(
        table_id="t", column="user_ssn",
        classification_level=p.classification_level, strategy="naming_pattern",
    )
    assert p.classification_id == expected


@pytest.mark.asyncio
async def test_naming_pattern_strategy_empty_inputs_no_op() -> None:
    """Empty table or column → no proposals."""
    strategy = NamingPatternClassificationStrategy()
    assert await strategy.propose(
        table_id="", column="c", company_id=_COMPANY_ID,
    ) == []
    assert await strategy.propose(
        table_id="t", column="", company_id=_COMPANY_ID,
    ) == []


@pytest.mark.asyncio
async def test_naming_pattern_strategy_company_id_unused() -> None:
    """The naming_pattern strategy ignores company_id (no cross-axis)."""
    strategy = NamingPatternClassificationStrategy()
    a = await strategy.propose(
        table_id="t", column="user_ssn", company_id=UUID(int=1),
    )
    b = await strategy.propose(
        table_id="t", column="user_ssn", company_id=UUID(int=2),
    )
    # Different company_id → same proposal contents (besides any
    # per-instance ordering quirks).
    assert {p.classification_level for p in a} == {
        p.classification_level for p in b
    }


# ---------------------------------------------------------------------------
# DomainDefaultClassificationStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_default_strategy_no_pack_returns_empty() -> None:
    """No domain pack → reader returns None → no proposals (empty-upstream)."""
    reader = _FakeDomainDefaultReader(defaults={})
    strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=reader,
    )
    out = await strategy.propose(
        table_id="t1", column="c", company_id=_COMPANY_ID,
    )
    assert out == []


@pytest.mark.asyncio
async def test_domain_default_strategy_pack_present_emits_at_060() -> None:
    """Domain pack with default → one proposal at 0.60 (low confidence)."""
    reader = _FakeDomainDefaultReader(
        defaults={"t1": ("regulated", "fintech")},
    )
    strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=reader,
    )
    out = await strategy.propose(
        table_id="t1", column="any_col", company_id=_COMPANY_ID,
    )
    assert len(out) == 1
    p = out[0]
    assert p.classification_level == "regulated"
    assert p.confidence == pytest.approx(0.60)
    assert p.strategy == "domain_default"
    assert p.upstream_semantic_type_id is None
    assert p.evidence.get("domain_id") == "fintech"
    assert "fintech" in p.reasoning


@pytest.mark.asyncio
async def test_domain_default_strategy_custom_confidence() -> None:
    """Caller-provided ``confidence`` override is honored."""
    reader = _FakeDomainDefaultReader(
        defaults={"t1": ("pii", "marketing")},
    )
    strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=reader, confidence=0.75,
    )
    out = await strategy.propose(
        table_id="t1", column="c", company_id=_COMPANY_ID,
    )
    assert out[0].confidence == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_domain_default_strategy_classification_id_is_canonical() -> None:
    """Proposal's classification_id matches :func:`make_classification_id`."""
    reader = _FakeDomainDefaultReader(
        defaults={"t1": ("confidential", "security")},
    )
    strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=reader,
    )
    out = await strategy.propose(
        table_id="t1", column="some_col", company_id=_COMPANY_ID,
    )
    expected = make_classification_id(
        table_id="t1", column="some_col",
        classification_level="confidential", strategy="domain_default",
    )
    assert out[0].classification_id == expected


@pytest.mark.asyncio
async def test_domain_default_strategy_empty_inputs_no_op() -> None:
    """Empty table or column → no reader call, no proposals."""
    reader = _FakeDomainDefaultReader()
    strategy = DomainDefaultClassificationStrategy(
        domain_default_reader=reader,
    )
    assert await strategy.propose(
        table_id="", column="c", company_id=_COMPANY_ID,
    ) == []
    assert await strategy.propose(
        table_id="t", column="", company_id=_COMPANY_ID,
    ) == []
    assert reader.calls == []


@pytest.mark.asyncio
async def test_strategies_are_all_async() -> None:
    """All three strategies expose async ``propose`` methods (Protocol)."""
    import inspect
    for cls in (
        NamingPatternClassificationStrategy,
        SemanticTypeClassificationStrategy,
        DomainDefaultClassificationStrategy,
    ):
        assert inspect.iscoroutinefunction(cls.propose), (
            f"{cls.__name__}.propose must be async"
        )


@pytest.mark.asyncio
async def test_proposals_are_instances_of_proposed_column_classification() -> None:
    """Strategy output is a list of :class:`ProposedColumnClassification`."""
    strategy = NamingPatternClassificationStrategy()
    out = await strategy.propose(
        table_id="t", column="user_password", company_id=_COMPANY_ID,
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedColumnClassification) for p in out)
