"""W5.A2 — StatementToOwnerReactivity unit tests.

Verifies the predicate / condition / fire path with stubbed
topic_extractor / owner_lookup / resource_aggregator / dm_sender. The
true end-to-end test (drives a real chat_received entry through the full
pipeline) lives in apps/worm-core/tests/test_statement_to_owner_e2e.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from wormbase_reactivities import (
    ReactivityContext,
    ReactivityRegistry,
    StatementToOwnerReactivity,
)


CAROL = UUID("eeeeeeee-0000-0000-0000-0000000000c1")
DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubTopic:
    kind: str
    id: UUID
    label: str
    confidence: float
    domain_id: UUID | None


@dataclass
class _StubPerson:
    person_id: UUID
    name: str
    email: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class _StubBundle:
    kpis: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    processes: list = field(default_factory=list)
    data_products: list = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kpis": [], "sources": [], "decisions": [],
            "processes": [], "data_products": [],
        }


class _MockDMSender:
    """Records open_dm + send_dm calls for assertion."""
    platform = "slack"

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.sent: list[tuple[str, str]] = []

    async def open_dm(self, platform_user_id: str) -> str:
        self.opened.append(platform_user_id)
        return f"D-{platform_user_id}"

    async def send_dm(self, channel_id: str, text: str,
                      *, blocks: list[dict[str, Any]] | None = None) -> str:
        self.sent.append((channel_id, text))
        return f"M-{len(self.sent)}"


def _stub_topic(confidence: float = 0.9, domain: UUID | None = None) -> Any:
    async def _impl(message, *, ledger, company_id):
        if "churn" in message.lower():
            return _StubTopic(
                kind="kpi", id=KPI_CHURN, label="churn",
                confidence=confidence,
                domain_id=domain or DOMAIN_RETENTION,
            )
        return None
    return _impl


def _stub_owner_returns(person: _StubPerson | None) -> Any:
    async def _impl(topic, *, ledger, company_id):
        return person
    return _impl


def _stub_aggregator() -> Any:
    async def _impl(topic, *, ledger, company_id):
        return _StubBundle()
    return _impl


def _chat_entry(seq: int, text: str, sender_person: UUID | None = None,
                channel_id: str = "C-rev",
                message_id: str = "M-1") -> dict[str, Any]:
    args: dict[str, Any] = {
        "text": text,
        "channel_id": channel_id,
        "message_id": message_id,
        "sender_label": "Bob",
    }
    if sender_person is not None:
        args["sender_person"] = str(sender_person)
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


# ---------------------------------------------------------------------------
# Predicate: matches chat_received envelopes only
# ---------------------------------------------------------------------------


async def test_predicate_matches_chat_received(ledger, company_id):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(None),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    assert await rx.predicate.match(_chat_entry(1, "hi"), ctx) is True


async def test_predicate_does_not_match_other_envelopes(
    ledger, company_id,
):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(None),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    other = {
        "kind": "execute", "seq": 1,
        "payload": {"tool": "emit_person_proposed", "args": {}},
    }
    assert await rx.predicate.match(other, ctx) is False


# ---------------------------------------------------------------------------
# Fire — happy path: writes resource_conversation_proposed
# ---------------------------------------------------------------------------


async def test_fire_writes_resource_conversation_proposed(
    ledger, company_id,
):
    sender = _MockDMSender()
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform="slack",
            platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
        dm_sender=sender,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(_chat_entry(1, "our churn is up"), ctx)
    assert result.fired is True
    assert sender.opened == ["U-CAROL"]
    assert len(sender.sent) == 1

    rows = await ledger.fetch(company_id)
    tools = [r["payload"].get("tool") for r in rows
             if r["kind"] == "execute"]
    assert "emit_resource_conversation_proposed" in tools


# ---------------------------------------------------------------------------
# Fire — short-circuits on missing pieces
# ---------------------------------------------------------------------------


async def test_fire_skips_when_no_topic(ledger, company_id):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(
        _chat_entry(1, "lunch was great today"), ctx,
    )
    assert result.fired is False


async def test_fire_skips_below_confidence(ledger, company_id):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(confidence=0.4),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
        confidence_threshold=0.6,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(_chat_entry(1, "our churn is up"), ctx)
    assert result.fired is False


async def test_fire_skips_when_no_owner(ledger, company_id):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(None),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(_chat_entry(1, "our churn is up"), ctx)
    assert result.fired is False


async def test_fire_skips_when_speaker_is_owner(ledger, company_id):
    """Self-statement → no DM."""
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(
        _chat_entry(1, "our churn is up", sender_person=CAROL), ctx,
    )
    assert result.fired is False


async def test_fire_skips_on_empty_text(ledger, company_id):
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    result = await rx.fire(_chat_entry(1, ""), ctx)
    assert result.fired is False


# ---------------------------------------------------------------------------
# Budget enforcement (registry-driven)
# ---------------------------------------------------------------------------


async def test_budget_per_owner_blocks_after_n_fires(ledger, company_id):
    """Per-owner cap is 3 — the fourth fire must NOT land."""
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
    )
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
    )
    reg.register(rx)
    # Pre-load owner-axis budget to 3 (the cap). ``payload.args.owner_id``
    # must be present in the entry for the registry's per-owner counter
    # to apply; we set ``owner_id`` directly on the candidate fire entry.
    for i in range(3):
        await reg._inc_budget(
            reactivity_id=rx.id, axis="owner", key=str(CAROL),
            day="2026-04-28", by=1,
        )
    entry = _chat_entry(10, "our churn is up")
    # Inject owner_id into args so DailyBudget.allows() finds it.
    entry["payload"]["args"]["owner_id"] = str(CAROL)
    fired = await reg.dispatch(entry)
    assert fired == []  # over-budget — no fire


# ---------------------------------------------------------------------------
# Topic-novelty cooldown
# ---------------------------------------------------------------------------


async def test_topic_novelty_cooldown_within_4h(ledger, company_id):
    """Same (topic, owner) within 4h should not re-fire."""
    rx = StatementToOwnerReactivity(
        topic_extractor=_stub_topic(),
        owner_lookup=_stub_owner_returns(_StubPerson(
            person_id=CAROL, name="Carol", platform_user_id="U-CAROL",
        )),
        resource_aggregator=_stub_aggregator(),
    )
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: state["now"],
    )
    reg.register(rx)
    fired1 = await reg.dispatch(_chat_entry(1, "our churn is up"))
    assert fired1 == [rx.id]

    # 30 minutes later — within cooldown
    from datetime import timedelta
    state["now"] = state["now"] + timedelta(minutes=30)
    fired2 = await reg.dispatch(_chat_entry(2, "our churn is up still"))
    assert fired2 == []  # cooldown blocks re-fire
