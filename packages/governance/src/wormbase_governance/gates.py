"""Four gates: PII, warmup, interjection, knowledge.

Each gate is a stateful object (constructed once per company) with an
async ``check`` / ``allow`` method returning a result. The dotted-path
forms ``pii_redaction_gate``, ``warmup_gate``, ``interjection_gate``,
``knowledge_gate`` are plain wrapper functions used by policy templates
that reference them as ``gate_impl`` strings.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Awaitable, Literal
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ontology_seed import Loader, PIIPattern

from wormbase_governance.types import PIIGateResult


# ---------------------------------------------------------------------------
# PII gate
# ---------------------------------------------------------------------------


def _luhn_ok(digits: str) -> bool:
    digits = "".join(c for c in digits if c.isdigit())
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    parity = (len(digits) - 2) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class PIIGate:
    """Compiles every ontology PIIPattern; redacts matches; tags classification."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        loader: Loader | None = None,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        loader = loader or Loader()
        self._patterns: list[tuple[PIIPattern, re.Pattern[str]]] = []
        for p in loader.load_pii_patterns():
            try:
                cre = re.compile(p.regex)
                self._patterns.append((p, cre))
            except re.error:
                continue  # already validated, but be defensive

    async def check(
        self, text: str, context: dict[str, Any] | None = None
    ) -> PIIGateResult:
        context = context or {}
        if not text:
            return PIIGateResult(
                redacted_text="",
                matches=[],
                classification_escalation=None,
                changed=False,
            )
        spans: list[tuple[int, int, PIIPattern]] = []
        for p, cre in self._patterns:
            for m in cre.finditer(text):
                # Luhn validation for credit-card pattern.
                if p.id == "credit_card" and not _luhn_ok(m.group(0)):
                    continue
                spans.append((m.start(), m.end(), p))
        if not spans:
            return PIIGateResult(
                redacted_text=text,
                matches=[],
                classification_escalation=None,
                changed=False,
            )

        # Sort by start asc, end desc so longer matches eat shorter ones.
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        # Greedy non-overlap.
        accepted: list[tuple[int, int, PIIPattern]] = []
        last_end = -1
        for start, end, p in spans:
            if start < last_end:
                continue
            accepted.append((start, end, p))
            last_end = end

        # Build redacted text + match metadata.
        result_chunks: list[str] = []
        cursor = 0
        matches: list[dict[str, Any]] = []
        escalation: Literal["pii", "regulated"] | None = None
        for start, end, p in accepted:
            result_chunks.append(text[cursor:start])
            result_chunks.append(f"[REDACTED:{p.id}]")
            cursor = end
            original_hash = hashlib.sha256(
                text[start:end].encode("utf-8")
            ).hexdigest()
            matches.append(
                {
                    "pattern_id": p.id,
                    "span": [start, end],
                    "original_hash": original_hash,
                }
            )
            # regulated > pii in escalation hierarchy.
            if p.classification == "regulated":
                escalation = "regulated"
            elif escalation is None:
                escalation = "pii"
        result_chunks.append(text[cursor:])
        redacted = "".join(result_chunks)
        await self._record_gate_fired(matches, context)
        return PIIGateResult(
            redacted_text=redacted,
            matches=matches,
            classification_escalation=escalation,
            changed=True,
        )

    async def _record_gate_fired(
        self, matches: list[dict[str, Any]], context: dict[str, Any]
    ) -> None:
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "gate_fired",
                "ref_id": str(uuid4()),
                "reason": "pii_match",
                "proposed_by": "pii_gate",
            },
            execute_fn=lambda: {
                "tool": "emit_gate_fired",
                "args": {
                    "gate": "pii",
                    "outcome": "warned",
                    "subject_ref": str(context.get("source", "unknown")),
                    "reason": f"matched {len(matches)} patterns",
                    "pattern_ids": [m["pattern_id"] for m in matches],
                    "match_count": len(matches),
                },
                "result_ref": "pii",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "pii_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "pii match recorded without raw text",
            },
            timestamp=datetime.now(UTC),
            quadrant="passive_deterministic",
        )


# ---------------------------------------------------------------------------
# Warmup gate
# ---------------------------------------------------------------------------


class _GateDecisionLite:
    __slots__ = ("allow", "reason", "metadata", "suggested_action")

    def __init__(
        self, allow: bool, reason: str,
        metadata: dict[str, Any] | None = None,
        suggested_action: str | None = None,
    ) -> None:
        self.allow = allow
        self.reason = reason
        self.metadata = metadata or {}
        self.suggested_action = suggested_action


class WarmupGate:
    """Blocks active actions until ramp.schema axis crosses threshold."""

    def __init__(
        self,
        ramp_reader: Callable[[UUID], Awaitable[Any]],
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        threshold_schema: float = 50.0,
    ) -> None:
        self._ramp_reader = ramp_reader
        self._ledger = ledger
        self._company_id = company_id
        self._threshold = threshold_schema

    async def check(
        self,
        action_type: Literal["passive", "active"],
        company_id: UUID | None = None,
    ) -> _GateDecisionLite:
        if action_type == "passive":
            return _GateDecisionLite(True, "passive_always_allowed")
        cid = company_id or self._company_id
        ramp = await self._ramp_reader(cid)
        # Accept either ``schema_axis`` (new RampState attribute) or
        # ``schema`` (legacy / dict form) so this works against the live
        # Pydantic model and against any read-side projection that emits
        # the dict form. See apps/worm-core/src/wormbase_core/types.py.
        schema = float(
            getattr(ramp, "schema_axis", None)
            if getattr(ramp, "schema_axis", None) is not None
            else getattr(ramp, "schema", 0.0)
        )
        if schema >= self._threshold:
            return _GateDecisionLite(
                True, f"warmup_ok:schema={schema}",
                metadata={"schema": schema, "threshold": self._threshold},
            )
        await self._record(False, schema)
        return _GateDecisionLite(
            False, f"warmup_schema_under_{int(self._threshold)}",
            metadata={"schema": schema, "threshold": self._threshold},
        )

    async def _record(self, allow: bool, schema: float) -> None:
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "gate_fired",
                "ref_id": str(uuid4()),
                "reason": "warmup_blocked",
                "proposed_by": "warmup_gate",
            },
            execute_fn=lambda: {
                "tool": "emit_gate_fired",
                "args": {
                    "gate": "warmup",
                    "outcome": "blocked" if not allow else "allowed",
                    "subject_ref": "active_action",
                    "reason": f"schema={schema} threshold={self._threshold}",
                    "schema": schema,
                    "threshold": self._threshold,
                },
                "result_ref": "warmup",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "warmup_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep", "rationale": "warmup decision recorded",
            },
            timestamp=datetime.now(UTC),
            quadrant="passive_deterministic",
        )


# ---------------------------------------------------------------------------
# Interjection gate (≤3 clarifying questions / channel / UTC day)
# ---------------------------------------------------------------------------


class InterjectionGate:
    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        clock: Any = None,
        limit: int = 3,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._clock = clock
        self._limit = limit

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock.now()
        return datetime.now(UTC)

    async def allow(
        self, channel_id: str, question_type: Literal["clarification", "statement"]
    ) -> bool:
        if question_type != "clarification":
            return True
        now = self._now()
        window_start = now.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = await self._ledger.fetch(self._company_id)
        count = 0
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"]["args"]
            if (
                args.get("content") == f"clarify_asked:{channel_id}"
                and r["ts"] >= window_start
            ):
                count += 1
        if count < self._limit:
            await self._ledger.write(
                company_id=self._company_id,
                propose={
                    "target_kind": "memory_written",
                    "ref_id": str(uuid4()),
                    "reason": "clarify_asked",
                    "proposed_by": "interjection_gate",
                },
                execute_fn=lambda: {
                    "tool": "emit_memory_written",
                    "args": {
                        "memory_id": str(uuid4()),
                        "content": f"clarify_asked:{channel_id}",
                        "tags": [
                            "clarify_asked", f"channel:{channel_id}",
                        ],
                    },
                    "result_ref": "clarify_asked",
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "clarify_logged", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep", "rationale": "clarify counted",
                },
                timestamp=now,
                quadrant="active_deterministic",
            )
            return True
        # Over budget.
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "gate_fired",
                "ref_id": str(uuid4()),
                "reason": "interjection_over_budget",
                "proposed_by": "interjection_gate",
            },
            execute_fn=lambda: {
                "tool": "emit_gate_fired",
                "args": {
                    "gate": "interjection",
                    "outcome": "blocked",
                    "subject_ref": channel_id,
                    "reason": f"budget {self._limit} exhausted",
                    "channel_id": channel_id,
                    "current_count": count,
                    "limit": self._limit,
                    "window_start": window_start.isoformat(),
                },
                "result_ref": "interjection",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "interjection_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep", "rationale": "interjection blocked",
            },
            timestamp=now,
            quadrant="passive_deterministic",
        )
        return False


# ---------------------------------------------------------------------------
# Knowledge gate
# ---------------------------------------------------------------------------


class KnowledgeGate:
    def __init__(
        self,
        ontology_concepts: Iterable[str],
        confirmed_concepts: Iterable[str],
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
    ) -> None:
        self._ontology = set(ontology_concepts)
        self._confirmed = set(confirmed_concepts)
        self._ledger = ledger
        self._company_id = company_id

    async def check(self, query_concepts: list[str]) -> _GateDecisionLite:
        if not query_concepts:
            return _GateDecisionLite(True, "no_concepts_referenced")
        unknown = [c for c in query_concepts if c not in self._ontology]
        undefined = [c for c in query_concepts if c not in self._confirmed]
        missing = sorted(set(unknown) | set(undefined))
        if not missing:
            return _GateDecisionLite(True, "all_concepts_known_and_defined")
        await self._record_block(missing)
        first = missing[0]
        return _GateDecisionLite(
            False,
            f"missing_knowledge:{missing}",
            metadata={"missing": missing, "unknown": unknown, "undefined": undefined},
            suggested_action=f"clarify:what do we mean by {first}?",
        )

    async def _record_block(self, missing: list[str]) -> None:
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "gate_fired",
                "ref_id": str(uuid4()),
                "reason": "knowledge_gap",
                "proposed_by": "knowledge_gate",
            },
            execute_fn=lambda: {
                "tool": "emit_gate_fired",
                "args": {
                    "gate": "knowledge",
                    "outcome": "blocked",
                    "subject_ref": "answer",
                    "reason": f"missing {missing}",
                    "missing": missing,
                },
                "result_ref": "knowledge",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "knowledge_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep", "rationale": "knowledge gap recorded",
            },
            timestamp=datetime.now(UTC),
            quadrant="passive_deterministic",
        )


# ---------------------------------------------------------------------------
# Dotted-path wrappers (for policy_templates.gate_impl strings)
# ---------------------------------------------------------------------------


def pii_redaction_gate(*args, **kwargs) -> PIIGate:  # type: ignore[no-untyped-def]
    """Factory used by policy_template gate_impl resolution."""
    return PIIGate(*args, **kwargs)


def warmup_gate(*args, **kwargs) -> WarmupGate:  # type: ignore[no-untyped-def]
    return WarmupGate(*args, **kwargs)


def interjection_gate(*args, **kwargs) -> InterjectionGate:  # type: ignore[no-untyped-def]
    return InterjectionGate(*args, **kwargs)


def knowledge_gate(*args, **kwargs) -> KnowledgeGate:  # type: ignore[no-untyped-def]
    return KnowledgeGate(*args, **kwargs)


# ---------------------------------------------------------------------------
# Channel talkativeness default (warmup template only)
# ---------------------------------------------------------------------------
#
# `policy:channel_talkativeness` ships per-channel posture defaults:
#   talkativeness ∈ {lurker, responsive, proactive}; defaults to responsive.
#   daily_interjection_budget defaults to 3 (per the first-week envelope).
#
# At warmup time PolicyLoader records the template as a `policy_applied`
# ledger entry; per-channel overrides are admin actions on /channels POST.
# The chat-worm Reactivities (Block F of the chat-worm extraction plan)
# read these defaults via ChatStore. There is no runtime-fired gate yet —
# this factory exists so the template's `gate_impl` dotted path resolves
# (PolicyTemplate validates `gate_impl` is importable and the governance
# test suite imports every applied template's gate_impl).
CHANNEL_TALKATIVENESS_DEFAULT = {
    "talkativeness": "responsive",
    "daily_interjection_budget": 3,
}


def channel_talkativeness_default(*args, **kwargs) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Return the default per-channel posture dict."""
    return dict(CHANNEL_TALKATIVENESS_DEFAULT)


__all__ = [
    "CHANNEL_TALKATIVENESS_DEFAULT",
    "InterjectionGate",
    "KnowledgeGate",
    "PIIGate",
    "PIIGateResult",
    "WarmupGate",
    "channel_talkativeness_default",
    "interjection_gate",
    "knowledge_gate",
    "pii_redaction_gate",
    "warmup_gate",
]
