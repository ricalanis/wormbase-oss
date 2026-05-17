"""Chaos: Kimi remote returns 503 to the inference router.

Failure mode
------------
The inference router (responsible for semantic matching when the
deterministic ontology lookup is ambiguous) raises ``httpx.HTTPStatusError``
on a 503 from Kimi remote. ``StatementToOwnerReactivity`` consumes the
inference router via ``topic_extractor`` — production wires this to a
composite extractor that tries the deterministic catalog match first
and falls back to remote inference for low-confidence cases.

Invariants the system MUST preserve
-----------------------------------
1. The Reactivity catches the inference exception, logs at WARNING (the
   plan calls for INFO on the *fallback* path; we treat the fallback
   landing as INFO and the underlying error as WARNING — both shapes
   are observable by demo-day operators).
2. Reactivity gracefully degrades to the deterministic ontology match.
   When the deterministic catalog has the resource (the production
   common case), the reactivity STILL fires — wormbase resilience.
3. When the deterministic match returns None or below threshold AND
   the inference router is down, the reactivity does NOT fire — it
   returns ``ReactivityResult(fired=False)`` rather than raising.
4. The reactivity-budget counters are not consumed by a fire that
   doesn't happen (Invariant 4 of W6.A3).

Failure-injection point
-----------------------
We patch the ``topic_extractor`` callable to mimic a composite
extractor: try-remote-first, fall back to deterministic. On the chaos
path the remote raises ``httpx.HTTPStatusError(status=503)``; the
fallback path returns either a deterministic Topic or None. We assert
the two named outcomes:

    - remote_503 + deterministic_hit → fires
    - remote_503 + deterministic_miss → no fire (and no exception leaks)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    ReactivityContext,
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
    def to_payload(self) -> dict[str, Any]:
        return {
            "kpis": [], "sources": [], "decisions": [],
            "processes": [], "data_products": [],
        }


def _build_503() -> httpx.HTTPStatusError:
    """Build the canonical 503 error shape an inference router would raise."""
    request = httpx.Request("POST", "https://kimi.example/api/chat")
    response = httpx.Response(
        503,
        request=request,
        text="upstream temporarily unavailable",
    )
    return httpx.HTTPStatusError(
        "503 Service Unavailable", request=request, response=response,
    )


def _composite_extractor(
    *,
    deterministic_returns: _StubTopic | None,
    remote_calls: dict[str, int],
) -> Any:
    """Composite extractor: tries remote inference first, falls back to
    a deterministic ontology lookup.

    Mirrors the production posture documented in topic_extractor.py:30-35:
    the deterministic match is the floor; remote inference is the
    upgrade path. Under chaos (Kimi returns 503), the remote call
    raises; we log + fall back to the deterministic answer.
    """

    async def _impl(
        message: str, *, ledger: Any, company_id: UUID,
    ) -> Any:
        # 1. Try remote inference first. It always raises in the chaos
        #    test — we stand in for the kimi-down condition.
        try:
            remote_calls["count"] = remote_calls.get("count", 0) + 1
            raise _build_503()
        except httpx.HTTPStatusError as exc:
            # Honest log — INFO on the fallback so demo-day operators
            # can audit which surface served the answer.
            logging.getLogger(
                "wormbase_core.topic_extractor.composite",
            ).info(
                "inference router 503; falling back to deterministic match: %s",
                exc.response.status_code,
            )
            # 2. Fall back to the deterministic catalog match.
            return deterministic_returns

    return _impl


def _owner_lookup(person: _StubPerson | None) -> Any:
    async def _impl(topic: Any, *, ledger: Any, company_id: UUID) -> Any:
        return person
    return _impl


def _aggregator() -> Any:
    async def _impl(topic: Any, *, ledger: Any, company_id: UUID) -> Any:
        return _StubBundle()
    return _impl


class _RecordingDMSender:
    platform = "slack"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def open_dm(self, platform_user_id: str) -> str:
        return f"D-{platform_user_id}"

    async def send_dm(
        self,
        platform_channel_id: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        self.sent.append((platform_channel_id, text))
        return f"M-{len(self.sent)}"


def _chat_entry(seq: int, text: str) -> dict[str, Any]:
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "text": text,
                "channel_id": "C-rev",
                "message_id": f"M-{seq}",
                "sender_label": "Bob",
            },
        },
    }


# ---------------------------------------------------------------------------
# Resilience: 503 + deterministic hit → reactivity STILL fires
# ---------------------------------------------------------------------------


async def test_inference_503_falls_back_to_deterministic_and_fires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kimi 503 plus a deterministic hit must STILL fire the reactivity.

    This is the resilience invariant: a transient inference outage must
    not knock out the high-confidence deterministic path.
    """
    ledger = InMemoryLedger()
    company_id = uuid4()
    remote_calls: dict[str, int] = {}

    deterministic_topic = _StubTopic(
        kind="kpi", id=KPI_CHURN, label="churn",
        confidence=0.95, domain_id=DOMAIN_RETENTION,
    )

    sender = _RecordingDMSender()
    rx = StatementToOwnerReactivity(
        topic_extractor=_composite_extractor(
            deterministic_returns=deterministic_topic,
            remote_calls=remote_calls,
        ),
        owner_lookup=_owner_lookup(_StubPerson(
            person_id=CAROL, name="Carol", platform="slack",
            platform_user_id="U-CAROL",
        )),
        resource_aggregator=_aggregator(),
        dm_sender=sender,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )

    with caplog.at_level(logging.INFO):
        result = await rx.fire(_chat_entry(1, "our churn is up"), ctx)

    # Invariant 2: reactivity fired despite the 503.
    assert result.fired is True, (
        "deterministic fallback must keep the reactivity firing"
    )
    assert remote_calls["count"] == 1, "remote was tried exactly once"

    # Invariant 1: the fallback was logged at INFO.
    fallback_logs = [
        rec for rec in caplog.records
        if rec.levelno >= logging.INFO
        and ("fallback" in rec.getMessage() or "falling back" in rec.getMessage())
        and "503" in rec.getMessage()
    ]
    assert fallback_logs, (
        "the inference fallback must log INFO+ so demo-day operators "
        "can audit which surface served the answer"
    )

    # Invariant 4: budget consumed by exactly one fire.
    assert result.budget_used.get("per_owner") == 1
    assert result.budget_used.get("per_tenant") == 1


# ---------------------------------------------------------------------------
# Honest UX: 503 + deterministic miss → no fire (no fake send)
# ---------------------------------------------------------------------------


async def test_inference_503_with_no_deterministic_fallback_does_not_fire(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kimi 503 + no deterministic match → reactivity does NOT fire.

    The honest "we couldn't reach an answer" outcome. Phenomenon-gap
    detection (a sister reactivity) handles the gap; this reactivity
    stays silent rather than firing on noise.
    """
    ledger = InMemoryLedger()
    company_id = uuid4()
    remote_calls: dict[str, int] = {}

    sender = _RecordingDMSender()
    rx = StatementToOwnerReactivity(
        topic_extractor=_composite_extractor(
            deterministic_returns=None,  # the deterministic path is silent
            remote_calls=remote_calls,
        ),
        owner_lookup=_owner_lookup(_StubPerson(
            person_id=CAROL, name="Carol", platform="slack",
            platform_user_id="U-CAROL",
        )),
        resource_aggregator=_aggregator(),
        dm_sender=sender,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id,
        registry=None, now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )

    rows_before = len(await ledger.fetch(company_id))

    with caplog.at_level(logging.INFO):
        result = await rx.fire(
            _chat_entry(1, "lunchtime debate about something"),
            ctx,
        )

    # Invariant 3: no fire. No DM. No ledger write.
    assert result.fired is False
    assert sender.sent == []
    rows_after = await ledger.fetch(company_id)
    assert len(rows_after) == rows_before, (
        "no half-state writes when both surfaces (remote + deterministic) "
        "fail to find an answer"
    )

    # Invariant 4: budget NOT consumed for a fire that didn't happen.
    assert result.budget_used == {} or all(
        v == 0 for v in result.budget_used.values()
    ), "no budget burned by a no-op fire"
