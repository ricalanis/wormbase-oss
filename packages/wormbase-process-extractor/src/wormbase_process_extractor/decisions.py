"""C.1 — single-entry decision-record synthesis.

Lifted from ``apps/worm-core/src/wormbase_core/process_extractor.py:526-619``.
The legacy code there operates on a *batch* of ``_ChatRow``; this module
reshapes that into a per-entry pure function:

    payload = await synthesize_decision(args, llm=llm)

The Reactivity wired by Block F.3 receives one ``execute`` ledger entry,
extracts its ``args`` dict, calls this function, and (if the returned
``confidence`` clears the threshold) emits the ``DecisionRecordedPayload``
through the canonical PEVR cycle. The "emit" step is no longer this
module's responsibility.

Decision-language detection re-uses ``_DECISION_PATTERNS`` from
``.predicates`` — single source of truth for the regex set. Optional LLM
escalation lives behind a small ``LLMClient`` Protocol (``affirm_decision``);
when supplied, an affirmation elevates confidence from heuristic-low
(0.55) to LLM-high (the value returned by the LLM, clamped to ``[0,1]``).

The module is import-cheap: no LLM, no httpx, no Kimi client created at
import time. The Reactivity injects an LLM at fire-time.

Equivalence vs the legacy path is asserted by
``tests/test_decisions.py::test_equivalence_with_legacy_extract_decisions``
on a 5-row fixture. The legacy code remains in place during C.1 (Block
G.2 deletes it) so the wave stays bisectable.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from wormbase_process_extractor.predicates import _DECISION_PATTERNS

logger = logging.getLogger("wormbase_process_extractor.decisions")

# Lifted constant from process_extractor.py:551 (the legacy heuristic-only
# confidence). Bound here so the test that checks "heuristic-only stays
# low" doesn't have to reach into the legacy module.
_HEURISTIC_CONFIDENCE: float = 0.55

# Mention pattern — captures @<token>; the token is added to deciders only
# when it parses as a UUID. Person-by-name resolution is a Reactivity-layer
# concern, not a synthesis concern.
_MENTION_PATTERN = re.compile(r"@([\w-]+)")

# Window the matched-clause extractor uses around the regex hit, so the
# resulting ``decision_text`` is a usable search phrase rather than the
# full chat blob (which the legacy heuristic emitted unchanged).
_CLAUSE_PADDING_CHARS = 24


@runtime_checkable
class LLMClient(Protocol):
    """Optional LLM escalation hook for decision affirmation.

    Implementations return a confidence in ``[0.0, 1.0]`` if the proposed
    decision is real, or ``None`` if it should be treated as a false-positive
    of the heuristic. ``None`` does not drop the payload — the Reactivity
    decides whether to emit based on the threshold check.
    """

    async def affirm_decision(
        self,
        *,
        text: str,
        evidence_message_ids: list[str],
    ) -> float | None: ...


class DecisionPayload(BaseModel):
    """Single decision-record payload, structurally compatible with
    ``wormbase_ledger.entries.DecisionRecordedPayload``.

    The Reactivity (Block F.3) takes ``payload.model_dump(mode='json')``
    and hands it straight to the ledger writer. The roundtrip is asserted
    in ``test_decisions.py::test_decision_payload_round_trips_via_ledger_payload``.
    """

    decision_id: UUID
    decision_text: str
    decision_at: datetime
    channel_id: str
    decided_by_persons: list[UUID]
    evidence_message_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("decision_at")
    @classmethod
    def _tz_aware_decision_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def synthesize_decision(
    args: dict[str, Any],
    *,
    llm: LLMClient | None = None,
) -> DecisionPayload | None:
    """Detect a decision in a single ``chat_received`` entry's args dict.

    Returns a populated :class:`DecisionPayload` when the heuristic regex
    set fires; returns ``None`` for chat with no decision-language signal.

    When ``llm`` is supplied and ``affirm_decision`` returns a non-None
    confidence, that value replaces the heuristic-low default.

    Args:
        args: The ``args`` sub-dict of a ``chat_received`` execute payload.
              Reads ``text``, ``sender_person``, ``channel_id``, ``message_id``,
              and (optionally) ``ts``.
        llm:  Optional :class:`LLMClient`; when omitted, only the heuristic
              regex-match runs and the payload carries
              ``confidence == _HEURISTIC_CONFIDENCE``.

    Returns:
        A :class:`DecisionPayload` ready to round-trip through
        ``DecisionRecordedPayload.model_validate(...)``, or ``None`` if no
        regex in ``_DECISION_PATTERNS`` matched.
    """
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return None

    matched_clause = _matched_clause(text)
    if matched_clause is None:
        return None

    sender = _parse_uuid(args.get("sender_person"))
    deciders = _extract_deciders(sender=sender, text=text)
    channel_id = str(args.get("channel_id") or "")
    message_id = str(args.get("message_id") or "")
    decision_at = _parse_ts(args.get("ts"))

    confidence = _HEURISTIC_CONFIDENCE
    if llm is not None:
        try:
            elevated = await llm.affirm_decision(
                text=matched_clause,
                evidence_message_ids=[message_id] if message_id else [],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM affirm_decision failed: %s", exc)
            elevated = None
        if elevated is not None:
            confidence = max(0.0, min(1.0, float(elevated)))

    return DecisionPayload(
        decision_id=uuid4(),
        decision_text=matched_clause[:512],
        decision_at=decision_at,
        channel_id=channel_id,
        decided_by_persons=deciders,
        evidence_message_ids=[message_id] if message_id else [],
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matched_clause(text: str) -> str | None:
    """Return a tightly-windowed clause around the first regex hit.

    Falls back to the full text only when the regex match exceeds the
    chosen window — keeps ``decision_text`` a useful search phrase rather
    than a long chat blob (the legacy heuristic emitted ``r.text.strip()``
    unchanged; the lifted shape narrows for downstream search hits).
    """
    for pattern in _DECISION_PATTERNS:
        m = pattern.search(text)
        if m is None:
            continue
        start = max(0, m.start() - _CLAUSE_PADDING_CHARS)
        end = min(len(text), m.end() + _CLAUSE_PADDING_CHARS)
        clause = text[start:end].strip()
        # Trim leading/trailing punctuation/whitespace from the window
        # for cleanliness; keep at least the regex match.
        clause = clause.strip(" \t\n.,;:—-")
        return clause or text.strip()
    return None


def _parse_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _extract_deciders(*, sender: UUID | None, text: str) -> list[UUID]:
    """Sender (when UUID-shaped) plus any UUID-shaped @mention tokens.

    Non-UUID handles (``@bob``, ``@finance-team``) are silently dropped —
    Person resolution lives in the Reactivity, not here. The output list
    is deduped while preserving insertion order (sender first).
    """
    out: list[UUID] = []
    seen: set[UUID] = set()
    if sender is not None and sender not in seen:
        out.append(sender)
        seen.add(sender)
    for m in _MENTION_PATTERN.finditer(text):
        token = m.group(1)
        as_uuid = _parse_uuid(token)
        if as_uuid is not None and as_uuid not in seen:
            out.append(as_uuid)
            seen.add(as_uuid)
    return out


__all__ = [
    "DecisionPayload",
    "LLMClient",
    "synthesize_decision",
]
