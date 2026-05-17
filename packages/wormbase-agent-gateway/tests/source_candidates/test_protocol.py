"""L1 Sub-wave B — protocol/dataclass/Reader-Protocol shape tests.

Pins:

  * :func:`make_candidate_id` re-export from :mod:`wormbase_ledger`.
  * :class:`ProposedSourceCandidate` is frozen + carries the documented
    8-field surface.
  * :class:`SourceCandidateStrategy` runtime-conformance on the 3
    strategies (KpiGap / ChannelMention / Complementarity).
  * The 3 lightweight Reader Protocols
    (:class:`ConnectedSourceReader`, :class:`KpiNodeReader`,
    :class:`SilverConversationReader`) are runtime_checkable and
    advertise their canonical methods.
  * Each Reader's companion Record dataclass is frozen + carries the
    documented field set.
  * Doctrine pin: L1 introduces 3 NEW lightweight Reader Protocols,
    but NO new cross-axis chain in the L4→L3 / L6→L5 / L8→L5 sense.
"""
from __future__ import annotations

import inspect
from uuid import UUID

import pytest

from wormbase_agent_gateway.source_candidates import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    ConnectedSourceReader,
    ConnectedSourceRecord,
    KpiGapAcquisitionStrategy,
    KpiNodeReader,
    KpiNodeRecord,
    ProposedSourceCandidate,
    SilverConversationReader,
    SilverConversationRecord,
    SourceCandidateStrategy,
    make_candidate_id,
)


# ---------------------------------------------------------------------------
# make_candidate_id — re-export integrity + determinism
# ---------------------------------------------------------------------------


def test_make_candidate_id_is_re_exported_from_ledger() -> None:
    """The L1 subpackage re-exports the canonical hash from wormbase_ledger.

    Pin: the L1 strategies + composite + ledger payload validator all
    consume the same function — re-export keeps the contract obvious.
    """
    from wormbase_ledger import make_candidate_id as ledger_helper
    assert make_candidate_id is ledger_helper


def test_make_candidate_id_is_deterministic() -> None:
    """Same args → same id across calls (replay-stable)."""
    a = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="kpi:q3_net_revenue",
        strategy="kpi_gap",
    )
    b = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="kpi:q3_net_revenue",
        strategy="kpi_gap",
    )
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_candidate_id_distinguishes_strategy() -> None:
    """Strategy IS in the hash (kept-separate-by-strategy; mirrors L6)."""
    a = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="kpi:revenue",
        strategy="kpi_gap",
    )
    b = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="kpi:revenue",
        strategy="channel_mention",
    )
    assert a != b


def test_make_candidate_id_distinguishes_kind_and_identifier() -> None:
    """Both kind and identifier participate in the hash."""
    base = make_candidate_id(
        proposed_kind="stripe", proposed_identifier="x", strategy="kpi_gap",
    )
    diff_kind = make_candidate_id(
        proposed_kind="postgres", proposed_identifier="x", strategy="kpi_gap",
    )
    diff_id = make_candidate_id(
        proposed_kind="stripe", proposed_identifier="y", strategy="kpi_gap",
    )
    assert base != diff_kind
    assert base != diff_id


# ---------------------------------------------------------------------------
# ProposedSourceCandidate — frozen dataclass + field surface
# ---------------------------------------------------------------------------


def test_proposed_source_candidate_is_frozen() -> None:
    """:class:`ProposedSourceCandidate` is a frozen dataclass."""
    p = ProposedSourceCandidate(
        candidate_id="abc",
        proposed_kind="stripe",
        proposed_identifier="kpi:revenue",
        domain_id_hint=None,
        confidence=0.75,
        strategy="kpi_gap",
        reasoning="test",
        evidence={},
    )
    try:
        p.candidate_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedSourceCandidate should be frozen")


def test_proposed_source_candidate_field_surface() -> None:
    """:class:`ProposedSourceCandidate` carries exactly the 8 documented fields."""
    p = ProposedSourceCandidate(
        candidate_id="cid",
        proposed_kind="stripe",
        proposed_identifier="acct_x",
        domain_id_hint="dom-1",
        confidence=0.7,
        strategy="kpi_gap",
        reasoning="test",
        evidence={"k": "v"},
    )
    expected = {
        "candidate_id",
        "proposed_kind",
        "proposed_identifier",
        "domain_id_hint",
        "confidence",
        "strategy",
        "reasoning",
        "evidence",
    }
    actual = set(p.__dataclass_fields__)
    assert actual == expected, (
        f"ProposedSourceCandidate field surface drift: "
        f"extra={actual - expected}, missing={expected - actual}"
    )


# ---------------------------------------------------------------------------
# SourceCandidateStrategy Protocol — runtime conformance
# ---------------------------------------------------------------------------


class _FakeKpiNodeReader:
    async def list_kpi_nodes_without_source(self, *, company_id):
        return []


class _FakeSilverConversationReader:
    async def list_recent_conversations(self, *, company_id, since_seconds=86400):
        return []


class _FakeConnectedSourceReader:
    async def list_connected_sources(self, *, company_id):
        return []


def test_strategies_satisfy_source_candidate_strategy_protocol() -> None:
    """All 3 strategies are instances of :class:`SourceCandidateStrategy`."""
    kg = KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader())
    cm = ChannelMentionAcquisitionStrategy(
        silver_conversation_reader=_FakeSilverConversationReader(),
    )
    co = ComplementaritySourceStrategy(
        connected_source_reader=_FakeConnectedSourceReader(),
    )
    for service in (kg, cm, co):
        assert isinstance(service, SourceCandidateStrategy), (
            f"{type(service).__name__} does not satisfy SourceCandidateStrategy"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert KpiGapAcquisitionStrategy.name == "kpi_gap"
    assert ChannelMentionAcquisitionStrategy.name == "channel_mention"
    assert ComplementaritySourceStrategy.name == "complementarity"


@pytest.mark.asyncio
async def test_source_candidate_strategy_propose_signature_is_company_scoped() -> None:
    """``propose(*, company_id)`` is the canonical signature.

    Pin: L1 strategies are company-scoped (NOT pair- / table- / snapshot-
    scoped like L3-L8). The composite invokes them once per Compounding
    cycle, not once per cross-source pair.
    """
    kg = KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader())
    sig = inspect.signature(kg.propose)
    assert set(sig.parameters) == {"company_id"}


# ---------------------------------------------------------------------------
# ConnectedSourceReader Protocol + ConnectedSourceRecord
# ---------------------------------------------------------------------------


def test_connected_source_reader_is_runtime_checkable() -> None:
    """:class:`ConnectedSourceReader` is a ``@runtime_checkable`` Protocol."""
    fake = _FakeConnectedSourceReader()
    assert isinstance(fake, ConnectedSourceReader)


def test_connected_source_reader_advertises_method() -> None:
    """Pin: ``list_connected_sources(*, company_id)`` is the canonical method."""
    sig = inspect.signature(ConnectedSourceReader.list_connected_sources)
    assert set(sig.parameters) == {"self", "company_id"}


def test_connected_source_record_is_frozen() -> None:
    """:class:`ConnectedSourceRecord` is a frozen dataclass."""
    r = ConnectedSourceRecord(
        source_id="src-1", kind="stripe", domain_id="dom-1", classification="internal",
    )
    try:
        r.source_id = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ConnectedSourceRecord should be frozen")


def test_connected_source_record_field_surface() -> None:
    """Pin: 4 fields — source_id / kind / domain_id / classification."""
    r = ConnectedSourceRecord(
        source_id="s", kind="k", domain_id=None, classification=None,
    )
    expected = {"source_id", "kind", "domain_id", "classification"}
    actual = set(r.__dataclass_fields__)
    assert actual == expected


# ---------------------------------------------------------------------------
# KpiNodeReader Protocol + KpiNodeRecord
# ---------------------------------------------------------------------------


def test_kpi_node_reader_is_runtime_checkable() -> None:
    """:class:`KpiNodeReader` is a ``@runtime_checkable`` Protocol."""
    fake = _FakeKpiNodeReader()
    assert isinstance(fake, KpiNodeReader)


def test_kpi_node_reader_advertises_method() -> None:
    """Pin: ``list_kpi_nodes_without_source(*, company_id)`` is canonical."""
    sig = inspect.signature(KpiNodeReader.list_kpi_nodes_without_source)
    assert set(sig.parameters) == {"self", "company_id"}


def test_kpi_node_record_is_frozen() -> None:
    """:class:`KpiNodeRecord` is a frozen dataclass."""
    r = KpiNodeRecord(kpi_node_id="k1", name="q3_revenue", domain_id="dom-1")
    try:
        r.kpi_node_id = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("KpiNodeRecord should be frozen")


def test_kpi_node_record_field_surface() -> None:
    """Pin: 3 fields — kpi_node_id / name / domain_id."""
    r = KpiNodeRecord(kpi_node_id="k", name="n", domain_id=None)
    expected = {"kpi_node_id", "name", "domain_id"}
    actual = set(r.__dataclass_fields__)
    assert actual == expected


# ---------------------------------------------------------------------------
# SilverConversationReader Protocol + SilverConversationRecord
# ---------------------------------------------------------------------------


def test_silver_conversation_reader_is_runtime_checkable() -> None:
    """:class:`SilverConversationReader` is a ``@runtime_checkable`` Protocol."""
    fake = _FakeSilverConversationReader()
    assert isinstance(fake, SilverConversationReader)


def test_silver_conversation_reader_advertises_method() -> None:
    """Pin: ``list_recent_conversations(*, company_id, since_seconds=86400)``."""
    sig = inspect.signature(SilverConversationReader.list_recent_conversations)
    assert set(sig.parameters) == {"self", "company_id", "since_seconds"}
    # since_seconds carries a sensible default
    assert sig.parameters["since_seconds"].default == 86400


def test_silver_conversation_record_is_frozen() -> None:
    """:class:`SilverConversationRecord` is a frozen dataclass."""
    r = SilverConversationRecord(
        message_id="m1", channel_id="c1", text="hello",
        domain_id=None, classification=None,
    )
    try:
        r.text = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("SilverConversationRecord should be frozen")


def test_silver_conversation_record_field_surface() -> None:
    """Pin: 5 fields — message_id / channel_id / text / domain_id / classification."""
    r = SilverConversationRecord(
        message_id="m", channel_id="c", text="t",
        domain_id=None, classification=None,
    )
    expected = {"message_id", "channel_id", "text", "domain_id", "classification"}
    actual = set(r.__dataclass_fields__)
    assert actual == expected


# ---------------------------------------------------------------------------
# Doctrine pin — NO new cross-axis chain (3 platform-Reader Protocols only)
# ---------------------------------------------------------------------------


def test_l1_introduces_three_lightweight_reader_protocols() -> None:
    """L1 ships 3 new lightweight Reader Protocols — NOT cross-axis chains.

    Per spec §4.6: L4→L3, L6→L5, L8→L5 chains read peer lake-axis
    projections. L1's Readers consume first-class platform projections
    (sources / KPI tree / silver conversations) whose producers are
    substrate, not Compounding loops. Cross-axis chain count stays at 3.
    """
    from wormbase_agent_gateway.source_candidates import protocol as proto
    assert hasattr(proto, "ConnectedSourceReader")
    assert hasattr(proto, "KpiNodeReader")
    assert hasattr(proto, "SilverConversationReader")
    # And the 3 Record dataclasses
    assert hasattr(proto, "ConnectedSourceRecord")
    assert hasattr(proto, "KpiNodeRecord")
    assert hasattr(proto, "SilverConversationRecord")


@pytest.mark.asyncio
async def test_propose_returns_list_of_proposed_source_candidate() -> None:
    """A strategy's ``propose`` returns a list of ProposedSourceCandidate."""
    kg = KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader())
    out = await kg.propose(company_id=UUID(int=1))
    assert isinstance(out, list)
    # Empty reader → empty proposals; type check still passes vacuously
    assert all(isinstance(p, ProposedSourceCandidate) for p in out)
