"""F3 (Sub-wave A) — make_flow_dispatcher stub-predicate route.

Pins the legacy ``make_flow_dispatcher``'s mentioned_in_conversation
branch added 2026-05-30. The production path runs through
``chat_bundle.dispatcher`` (chat-presence package); this test exercises
the parallel hook in worm-core's legacy SlackLurker dispatcher so the
audit-comment gap at ``service.py:283`` is closed.

The semantic-interpretation predicate is a stub: matches ``"data:"``
prefix in the event text. Full predicate is Phase 2 carry-forward.
Env knob ``WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED`` defaults OFF.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.reactivity import RelevanceDecision
from wormbase_core.service import (
    _stub_mention_data_prefix,
    is_mentioned_in_conversation_enabled,
    make_flow_dispatcher,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")


class _CountingFlow:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def on_file_drop(self, infra: Any) -> Any:
        self.calls.append(("file_drop", infra))
        return None

    async def on_dm(self, infra: Any) -> Any:
        self.calls.append(("dm", infra))
        return None

    async def on_proactive_mention(self, infra: Any) -> Any:
        self.calls.append(("mention", infra))
        return None


def _event(*, text: str = "", etype: str = "channel_message") -> dict:
    return {
        "type": etype,
        "ts": datetime.now(UTC),
        "channel_id": "C1",
        "user_id": str(uuid4()),
        "text": text,
        "message_id": "m1",
        "company_id": str(_COMPANY_ID),
        "payload": {},
    }


def _decision(flow: str) -> RelevanceDecision:
    return RelevanceDecision(
        should_react=True, reason="t", suggested_flow=flow,
    )


# --------------------------------------------------------------------- env knob


def test_is_mentioned_in_conversation_enabled_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", raising=False)
    assert is_mentioned_in_conversation_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes"])
def test_is_mentioned_in_conversation_enabled_truthy(
    value: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", value)
    assert is_mentioned_in_conversation_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_is_mentioned_in_conversation_enabled_falsy(
    value: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", value)
    assert is_mentioned_in_conversation_enabled() is False


# --------------------------------------------------------------------- predicate


def test_stub_predicate_matches_data_prefix() -> None:
    assert _stub_mention_data_prefix({"text": "data: stripe sales pipeline"}) is True


def test_stub_predicate_case_insensitive_and_whitespace_tolerant() -> None:
    assert _stub_mention_data_prefix({"text": "  Data: salesforce"}) is True
    assert _stub_mention_data_prefix({"text": "DATA:hubspot"}) is True


def test_stub_predicate_rejects_inline_match() -> None:
    # "data:" must be the prefix — not buried mid-sentence.
    assert (
        _stub_mention_data_prefix({"text": "looking at data: stripe"})
        is False
    )


def test_stub_predicate_handles_missing_text() -> None:
    assert _stub_mention_data_prefix({}) is False
    assert _stub_mention_data_prefix({"text": None}) is False


# --------------------------------------------------------------------- dispatcher


@pytest.mark.asyncio
async def test_dispatcher_default_off_does_not_route_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default behaviour: env unset → no mention dispatch even on match."""
    monkeypatch.delenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", raising=False)
    flow = _CountingFlow()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=flow,
        credential_in_dm=flow,
        company_id=_COMPANY_ID,
        mentioned_in_conversation=flow,
    )
    await dispatcher(
        _event(text="data: stripe pipeline"),
        _decision("mentioned_in_conversation"),
    )
    assert ("mention", ...) not in [(k, ...) for k, _ in flow.calls]


@pytest.mark.asyncio
async def test_dispatcher_env_on_and_matching_text_routes_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When env=true AND text matches stub predicate AND flow kwarg is
    passed, the dispatcher invokes on_proactive_mention."""
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "true")
    flow = _CountingFlow()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=flow,
        credential_in_dm=flow,
        company_id=_COMPANY_ID,
        mentioned_in_conversation=flow,
    )
    await dispatcher(
        _event(text="data: stripe pipeline"),
        _decision("mentioned_in_conversation"),
    )
    mention_calls = [c for c in flow.calls if c[0] == "mention"]
    assert len(mention_calls) == 1


@pytest.mark.asyncio
async def test_dispatcher_env_on_but_text_no_match_no_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with env=true, a non-matching text does not fire the flow."""
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "true")
    flow = _CountingFlow()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=flow,
        credential_in_dm=flow,
        company_id=_COMPANY_ID,
        mentioned_in_conversation=flow,
    )
    await dispatcher(
        _event(text="general chat with no data prefix"),
        _decision("mentioned_in_conversation"),
    )
    assert not any(c[0] == "mention" for c in flow.calls)


@pytest.mark.asyncio
async def test_dispatcher_no_flow_kwarg_no_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller that doesn't pass the kwarg keeps byte-identical behaviour."""
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "true")
    other_flow = _CountingFlow()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=other_flow,
        credential_in_dm=other_flow,
        company_id=_COMPANY_ID,
        # NB: no mentioned_in_conversation= kwarg.
    )
    await dispatcher(
        _event(text="data: stripe pipeline"),
        _decision("mentioned_in_conversation"),
    )
    # No mention call recorded; the other flow's surface remains empty.
    assert not any(c[0] == "mention" for c in other_flow.calls)


@pytest.mark.asyncio
async def test_dispatcher_swallows_mention_flow_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising mention flow must not propagate to the dispatcher's caller."""
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "true")

    class _Boom:
        async def on_file_drop(self, infra: Any) -> Any:
            return None

        async def on_dm(self, infra: Any) -> Any:
            return None

        async def on_proactive_mention(self, infra: Any) -> Any:
            raise RuntimeError("simulated downstream failure")

    boom = _Boom()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=boom,
        credential_in_dm=boom,
        company_id=_COMPANY_ID,
        mentioned_in_conversation=boom,
    )
    # Must not raise.
    await dispatcher(
        _event(text="data: stripe pipeline"),
        _decision("mentioned_in_conversation"),
    )


@pytest.mark.asyncio
async def test_dispatcher_still_routes_other_flows_with_mention_kwarg_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding the mentioned_in_conversation kwarg must NOT regress the
    drop_and_profile / credential_offered_in_dm routes."""
    monkeypatch.setenv("WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "true")
    flow = _CountingFlow()
    dispatcher = make_flow_dispatcher(
        drop_and_profile=flow,
        credential_in_dm=flow,
        company_id=_COMPANY_ID,
        mentioned_in_conversation=flow,
    )
    await dispatcher(
        _event(etype="file_drop"),
        _decision("drop_and_profile"),
    )
    await dispatcher(
        _event(etype="dm"),
        _decision("credential_offered_in_dm"),
    )
    assert any(c[0] == "file_drop" for c in flow.calls)
    assert any(c[0] == "dm" for c in flow.calls)
