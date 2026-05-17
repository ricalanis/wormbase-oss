"""Reactivity triad: infrastructure trigger -> semantic trigger -> relevance gate.

Every external event flowing into the worm passes through this pipeline:

    raw_event_dict
        --> InfrastructureTrigger --> InfraEvent
        --> SemanticTrigger        --> SemanticInterpretation | None
        --> RelevanceGate          --> RelevanceDecision

Each stage emits a tagged ledger entry via the canonical PEVR write
primitive (we encode the stage as a memory_written entry with fixed tags
so downstream replays + the dashboard trace can reconstruct the pipeline).

Note on InfraEvent duplication: the channel-adapters package owns its
own structurally-compatible ``InfraEvent`` dataclass — see
``packages/channel-adapters/src/wormbase_channel_adapters/types.py:8-13``
for the rationale (channel adapters must be importable without pulling in
worm-core). Both copies must be kept in lockstep on field shape and on
the ``is_live`` derivation; the freshness window default + env override
match the channel-adapters copy.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# Mirror of channel-adapters: default freshness window for is_live (seconds).
_DEFAULT_FRESHNESS_WINDOW_S = 60.0


def _freshness_window_s() -> float:
    """Mirror of channel-adapters: resolve env-overridable freshness window."""
    raw = os.environ.get("WORMBASE_FRESHNESS_WINDOW_S")
    if not raw:
        return _DEFAULT_FRESHNESS_WINDOW_S
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_FRESHNESS_WINDOW_S

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import Quadrant


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class InfraEvent(BaseModel):
    """Normalized infrastructure-level event.

    Provenance fields mirror the channel-adapters InfraEvent dataclass —
    ``delivery_mode`` distinguishes live push from history_sync replay,
    ``platform_ts`` carries the platform's authoritative wall-clock,
    ``history_sync_id`` points back at the ``conversation_sync`` lineage
    entry. Defaults preserve back-compat for pre-provenance call sites.

    The ``is_live`` property derives the speak-path gate; LiveOnly
    Reactivity Condition reads the same fields off ledger entries to gate
    the chat-presence reactivities (F1/F2/F4). F3 stays observation-only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["channel_message", "file_drop", "dm", "cron", "webhook"]
    payload: dict[str, Any]
    channel_id: str | None = None
    person_id: str | None = None
    message_id: str | None = None
    ts: datetime
    company_id: UUID
    text: str = ""
    delivery_mode: Literal["push", "history_sync"] = "push"
    platform_ts: datetime | None = None
    history_sync_id: str | None = None

    @property
    def is_live(self) -> bool:
        """Derived speak-path gate (mirror of channel-adapters InfraEvent)."""
        if self.delivery_mode != "push":
            return False
        if self.platform_ts is None:
            return True
        return (self.ts - self.platform_ts).total_seconds() < _freshness_window_s()


class SemanticInterpretation(BaseModel):
    """Output of the semantic classifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concepts: list[str] = Field(default_factory=list)
    event_type: Literal[
        "question",
        "statement",
        "file_reference",
        "credential_offer",
        "data_mention",
        "other",
    ] = "other"
    confidence: float = 0.0
    raw_text: str | None = None


class RelevanceDecision(BaseModel):
    """Output of the relevance gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    should_react: bool
    reason: str
    suggested_flow: str | None = None


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class InfrastructureTrigger(Protocol):
    async def handle(self, raw_event: dict[str, Any]) -> InfraEvent: ...


class SemanticTrigger(Protocol):
    async def handle(self, infra: InfraEvent) -> SemanticInterpretation | None: ...


class RelevanceGate(Protocol):
    async def handle(
        self, infra: InfraEvent, interp: SemanticInterpretation
    ) -> RelevanceDecision: ...


# ---------------------------------------------------------------------------
# Default infra trigger
# ---------------------------------------------------------------------------


_OPENCLAW_TYPE_MAP: dict[str, str] = {
    "channel_message": "channel_message",
    "channel.message": "channel_message",
    "message": "channel_message",
    "file_drop": "file_drop",
    "file.share": "file_drop",
    "dm": "dm",
    "im": "dm",
    "cron": "cron",
    "webhook": "webhook",
}


class DefaultInfrastructureTrigger:
    """Maps OpenClaw / Slack-shaped event dicts into `InfraEvent`."""

    def __init__(self, ledger: Ledger | InMemoryLedger, company_id: UUID) -> None:
        self._ledger = ledger
        self._company_id = company_id

    async def handle(self, raw_event: dict[str, Any]) -> InfraEvent:
        try:
            raw_type = raw_event["type"]
            ts_raw = raw_event["ts"]
        except KeyError as exc:
            raise ValueError(f"raw_event missing required key: {exc}") from exc

        if raw_type not in _OPENCLAW_TYPE_MAP:
            raise ValueError(f"unsupported event type {raw_type!r}")

        # Accept both ISO strings and ints (slack epoch seconds with .ms).
        if isinstance(ts_raw, datetime):
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
        elif isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(float(ts_raw), tz=UTC)
        elif isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.fromtimestamp(float(ts_raw), tz=UTC)
        else:
            raise ValueError(f"unsupported ts type: {type(ts_raw).__name__}")

        company_id = raw_event.get("company_id", self._company_id)
        if isinstance(company_id, str):
            company_id = UUID(company_id)

        infra = InfraEvent(
            source=_OPENCLAW_TYPE_MAP[raw_type],  # type: ignore[arg-type]
            payload=raw_event.get("payload", {}),
            channel_id=raw_event.get("channel_id") or raw_event.get("channel"),
            person_id=raw_event.get("user_id") or raw_event.get("user"),
            message_id=raw_event.get("message_id") or raw_event.get("client_msg_id"),
            ts=ts,
            company_id=company_id,
            text=raw_event.get("text", "") or "",
        )
        await _stage_log(
            self._ledger,
            company_id,
            stage="infrastructure_trigger",
            data={
                "source": infra.source,
                "channel_id": infra.channel_id,
                "person_id": infra.person_id,
                "message_id": infra.message_id,
                "text_len": len(infra.text),
            },
            ts=infra.ts,
        )
        return infra


# ---------------------------------------------------------------------------
# Default semantic trigger (wraps a classifier)
# ---------------------------------------------------------------------------


class _ClassifierLike(Protocol):
    async def classify(
        self, text: str, event_context: dict[str, Any]
    ) -> SemanticInterpretation: ...


class DefaultSemanticTrigger:
    """Calls the classifier, suppresses below confidence floor."""

    def __init__(
        self,
        classifier: _ClassifierLike,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        confidence_floor: float = 0.30,
    ) -> None:
        self._classifier = classifier
        self._ledger = ledger
        self._company_id = company_id
        self._floor = confidence_floor

    async def handle(self, infra: InfraEvent) -> SemanticInterpretation | None:
        interp = await self._classifier.classify(
            infra.text,
            {
                "source": infra.source,
                "channel_id": infra.channel_id,
                "person_id": infra.person_id,
            },
        )
        await _stage_log(
            self._ledger,
            self._company_id,
            stage="semantic_trigger",
            data={
                "concepts": list(interp.concepts),
                "event_type": interp.event_type,
                "confidence": interp.confidence,
                "below_floor": interp.confidence < self._floor,
            },
            ts=infra.ts,
        )
        if interp.confidence < self._floor:
            return None
        return interp


# ---------------------------------------------------------------------------
# Pipeline glue
# ---------------------------------------------------------------------------


class ReactivityPipeline:
    """Wires the three stages together with ledger logging at each step."""

    def __init__(
        self,
        infra: InfrastructureTrigger,
        semantic: SemanticTrigger,
        gate: RelevanceGate,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
    ) -> None:
        self._infra = infra
        self._semantic = semantic
        self._gate = gate
        self._ledger = ledger
        self._company_id = company_id

    async def process(self, raw_event: dict[str, Any]) -> RelevanceDecision | None:
        infra_event = await self._infra.handle(raw_event)
        interp = await self._semantic.handle(infra_event)
        if interp is None:
            return None
        decision = await self._gate.handle(infra_event, interp)
        await _stage_log(
            self._ledger,
            self._company_id,
            stage="relevance_decision",
            data={
                "should_react": decision.should_react,
                "reason": decision.reason,
                "suggested_flow": decision.suggested_flow,
            },
            ts=infra_event.ts,
        )
        return decision


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _stage_log(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    stage: str,
    data: dict[str, Any],
    ts: datetime | None = None,
    quadrant: Quadrant = "passive_deterministic",
) -> None:
    """Write a memory_written entry tagged 'reactivity_stage'.

    We use memory_written rather than a bespoke entry kind so the existing
    ledger schema (no migrations needed) carries reactivity traces. The tag
    `reactivity_stage:<stage>` lets the dashboard's trace stream filter.
    """
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(uuid4()),
            "reason": f"reactivity stage {stage}",
            "proposed_by": "reactivity",
        },
        execute_fn=lambda: {
            "tool": "emit_memory_written",
            "args": {
                "memory_id": str(uuid4()),
                "content": f"reactivity_stage:{stage}",
                "tags": ["reactivity_stage", stage, *[f"k:{k}" for k in data]],
            },
            "result_ref": stage,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "stage_logged", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"reactivity {stage}",
        },
        timestamp=ts or datetime.now(UTC),
        quadrant=quadrant,
    )


__all__ = [
    "DefaultInfrastructureTrigger",
    "DefaultSemanticTrigger",
    "InfraEvent",
    "InfrastructureTrigger",
    "ReactivityPipeline",
    "RelevanceDecision",
    "RelevanceGate",
    "SemanticInterpretation",
    "SemanticTrigger",
]
