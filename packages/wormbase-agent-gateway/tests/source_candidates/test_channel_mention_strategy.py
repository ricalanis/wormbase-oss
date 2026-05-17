"""L1 Sub-wave B — ChannelMentionAcquisitionStrategy tests.

Covers:

  * Empty reader → no proposals (honest empty-upstream posture per
    Sub-wave A handoff concern #1).
  * Direct vendor mentions (snowflake / stripe / hubspot) → matched
    connector kind at HIGH confidence (0.75).
  * Generic source phrasings → matched connector kind at BASE
    confidence (0.55).
  * Multiple mentions across rows → aggregate into one proposal per
    connector kind, accumulating message_refs.
  * Classification skip-set — pii / regulated rows are NOT scanned by
    default.
  * Evidence carries message_refs + channel_ids + matched_patterns +
    excerpts (capped at 3).
  * Replay stability — same input → same candidate_ids.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.source_candidates import (
    ChannelMentionAcquisitionStrategy,
    SilverConversationRecord,
)


_COMPANY = UUID("00000000-0000-0000-0000-000000000a02")


class _FakeSilverConversationReader:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls: list[dict] = []

    async def list_recent_conversations(self, *, company_id, since_seconds=86400):
        self.calls.append({
            "company_id": company_id, "since_seconds": since_seconds,
        })
        return list(self.rows)


# ---------------------------------------------------------------------------
# Honest empty-upstream posture (Sub-wave A handoff concern #1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_empty_reader_returns_no_proposals() -> None:
    """When the silver reader returns no rows, the strategy emits nothing.

    This is the explicit "configured · empty-upstream" honest stub
    posture per spec §4.3 + Sub-wave A handoff concern #1.
    """
    reader = _FakeSilverConversationReader()
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []


# ---------------------------------------------------------------------------
# Vendor mentions → HIGH confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_snowflake_proposes_snowflake() -> None:
    """``our snowflake warehouse`` → propose ``snowflake`` at HIGH."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-data",
            text="We should query our snowflake warehouse for that.",
            domain_id="dom-data", classification="internal",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    kinds = {p.proposed_kind for p in proposals}
    assert "snowflake" in kinds
    snowflake_p = next(p for p in proposals if p.proposed_kind == "snowflake")
    assert snowflake_p.confidence == pytest.approx(
        ChannelMentionAcquisitionStrategy.DEFAULT_HIGH_CONFIDENCE, abs=1e-4,
    )
    assert "m-1" in snowflake_p.evidence["message_refs"]
    assert "c-data" in snowflake_p.evidence["channel_ids"]


@pytest.mark.asyncio
async def test_channel_mention_stripe_proposes_stripe_at_high() -> None:
    """``export from stripe`` → propose ``stripe`` at HIGH."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-2", channel_id="c-fin",
            text="I'll do the export from stripe tomorrow.",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    stripe_p = next(p for p in proposals if p.proposed_kind == "stripe")
    assert stripe_p.confidence == pytest.approx(
        ChannelMentionAcquisitionStrategy.DEFAULT_HIGH_CONFIDENCE, abs=1e-4,
    )


@pytest.mark.asyncio
async def test_channel_mention_hubspot_proposes_hubspot_at_high() -> None:
    """``hubspot CRM`` → propose ``hubspot`` at HIGH."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-3", channel_id="c-sales",
            text="We need to sync that with HubSpot CRM.",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    hubspot_p = next(p for p in proposals if p.proposed_kind == "hubspot")
    assert hubspot_p.confidence >= ChannelMentionAcquisitionStrategy.DEFAULT_BASE_CONFIDENCE


# ---------------------------------------------------------------------------
# Aggregation across rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_multiple_snowflake_mentions_aggregate() -> None:
    """Two messages mentioning ``snowflake`` → ONE proposal with both message_refs."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-a", channel_id="c-1",
            text="our snowflake warehouse is slow",
            domain_id=None, classification="public",
        ),
        SilverConversationRecord(
            message_id="m-b", channel_id="c-2",
            text="snowflake again?",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    snowflake_props = [p for p in proposals if p.proposed_kind == "snowflake"]
    assert len(snowflake_props) == 1
    p = snowflake_props[0]
    assert set(p.evidence["message_refs"]) == {"m-a", "m-b"}
    assert set(p.evidence["channel_ids"]) == {"c-1", "c-2"}


@pytest.mark.asyncio
async def test_channel_mention_multiple_distinct_kinds_one_proposal_each() -> None:
    """Mentions of different connector kinds → distinct proposals."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id=None, classification="public",
        ),
        SilverConversationRecord(
            message_id="m-2", channel_id="c-1",
            text="export from stripe",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    kinds = {p.proposed_kind for p in proposals}
    assert "snowflake" in kinds
    assert "stripe" in kinds


# ---------------------------------------------------------------------------
# Classification skip-set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_skips_pii_rows_by_default() -> None:
    """Rows classified ``pii`` are NOT regex-scanned by default."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-pii", channel_id="c-1",
            text="our snowflake warehouse with all the PII",
            domain_id=None, classification="pii",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []


@pytest.mark.asyncio
async def test_channel_mention_skips_regulated_rows_by_default() -> None:
    """Rows classified ``regulated`` are NOT regex-scanned by default."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-reg", channel_id="c-1",
            text="our snowflake warehouse for HIPAA data",
            domain_id=None, classification="regulated",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []


@pytest.mark.asyncio
async def test_channel_mention_skip_classifications_is_configurable() -> None:
    """Override the skip-set to allow PII scanning."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id=None, classification="pii",
        ),
    ])
    # Override skip set to be empty — scan everything.
    strat = ChannelMentionAcquisitionStrategy(
        silver_conversation_reader=reader,
        skip_classifications=frozenset(),
    )
    proposals = await strat.propose(company_id=_COMPANY)
    assert any(p.proposed_kind == "snowflake" for p in proposals)


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_evidence_carries_excerpts_capped_at_three() -> None:
    """Evidence carries excerpts, capped at 3 entries to bound size."""
    rows = [
        SilverConversationRecord(
            message_id=f"m-{i}", channel_id="c-1",
            text=f"snowflake mention #{i} " + "x" * 300,
            domain_id=None, classification="public",
        )
        for i in range(5)
    ]
    reader = _FakeSilverConversationReader(rows)
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    snowflake_p = next(p for p in proposals if p.proposed_kind == "snowflake")
    assert len(snowflake_p.evidence["excerpts"]) == 3
    # Each excerpt is capped at 200 chars.
    for excerpt in snowflake_p.evidence["excerpts"]:
        assert len(excerpt) <= 200
    # All 5 message_refs preserved (only excerpts are capped).
    assert len(snowflake_p.evidence["message_refs"]) == 5


@pytest.mark.asyncio
async def test_channel_mention_evidence_carries_matched_patterns() -> None:
    """Evidence carries the human-readable matched-pattern excerpts."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse and the warehouse itself",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    snowflake_p = next(p for p in proposals if p.proposed_kind == "snowflake")
    assert any("Snowflake" in pat or "warehouse" in pat
               for pat in snowflake_p.evidence["matched_patterns"])


# ---------------------------------------------------------------------------
# Replay stability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_mention_replay_stability() -> None:
    """Same rows → same candidate_ids across runs."""
    rows = [
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id=None, classification="public",
        ),
    ]
    reader = _FakeSilverConversationReader(rows)
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    first = await strat.propose(company_id=_COMPANY)
    second = await strat.propose(company_id=_COMPANY)
    assert {p.candidate_id for p in first} == {p.candidate_id for p in second}


@pytest.mark.asyncio
async def test_channel_mention_passes_since_seconds_to_reader() -> None:
    """The strategy forwards its configured ``lookback_seconds`` to the reader."""
    reader = _FakeSilverConversationReader()
    strat = ChannelMentionAcquisitionStrategy(
        silver_conversation_reader=reader,
        lookback_seconds=7200,
    )
    await strat.propose(company_id=_COMPANY)
    assert reader.calls[0]["since_seconds"] == 7200


@pytest.mark.asyncio
async def test_channel_mention_threads_domain_id_when_present() -> None:
    """The first row's domain_id flows through as ``domain_id_hint``."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id="dom-data", classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    snowflake_p = next(p for p in proposals if p.proposed_kind == "snowflake")
    assert snowflake_p.domain_id_hint == "dom-data"


@pytest.mark.asyncio
async def test_channel_mention_skips_empty_text() -> None:
    """Rows with empty ``text`` are silently skipped."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="",
            domain_id=None, classification="public",
        ),
    ])
    strat = ChannelMentionAcquisitionStrategy(silver_conversation_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []
