"""Shared governance result types and Protocol surfaces.

Promoted in Wave D from scattered locations:
  - wormbase_core.types.GateDecision           -> here
  - wormbase_core.types.PIIGateResult          -> here
  - wormbase_chat_presence.chat_flows._shared._PIIGateProto       -> PIIGateProtocol
  - wormbase_chat_presence.chat_flows._shared._InterjectionGateProto -> InterjectionGateProtocol

PolicyGate is a NEW typing-only Protocol that documents the structural
shape every concrete gate in this package satisfies. It is not used as
a registry or a runtime dispatch type — gate_impl resolution remains
the dotted-path mechanism in policy_templates.yaml.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class GateDecision(BaseModel):
    """Generic gate result returned by Warmup, Knowledge, and Relevance gates."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    allow: bool
    reason: str
    suggested_action: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PIIGateResult(BaseModel):
    """Output of PIIGate.check.

    `redacted_text` is safe to log and to send out; `matches` carries
    metadata WITHOUT the raw matched substring (only a SHA-256 hash).
    `classification_escalation` lifts the classification of the bearing
    artifact when any match is found.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    redacted_text: str
    matches: list[dict[str, Any]]
    classification_escalation: Literal["pii", "regulated"] | None = None
    changed: bool = False


@runtime_checkable
class PolicyGate(Protocol):
    """Structural shape every concrete governance gate satisfies.

    Concrete gates may have heterogeneous `check` signatures (PII takes
    text+context, Knowledge takes a list of concepts, MaskedColumn takes
    a MaskedColumnQuery). The Protocol documents the minimum: an async
    `check` returning some decision-like object. Use the more specific
    Protocols (PIIGateProtocol, InterjectionGateProtocol) for narrow
    typing in flow code.
    """
    async def check(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class PIIGateProtocol(Protocol):
    """Narrow shape for callers that only need PII redaction.

    Promoted from chat_flows/_shared._PIIGateProto. The canonical
    implementation returns PIIGateResult; `Any` widens the return type
    so test stubs (StubPIIGate) satisfy the Protocol.
    """
    async def check(self, text: str, context: dict[str, Any]) -> Any: ...


@runtime_checkable
class InterjectionGateProtocol(Protocol):
    """Narrow shape for the daily-clarification budget gate.

    Promoted from chat_flows/_shared._InterjectionGateProto. Returns
    True when the interjection is allowed, False when over-budget.
    """
    async def allow(self, channel_id: str, question_type: str) -> bool: ...


__all__ = [
    "GateDecision",
    "InterjectionGateProtocol",
    "PIIGateProtocol",
    "PIIGateResult",
    "PolicyGate",
]
