"""Relevance gate: decides whether the worm should react to a given event."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

# v1.1 Task 5 (Hole #7 — governance unification): defer the
# ``wormbase_core.reactivity`` import to typecheck-only. Importing
# ``wormbase_governance`` from any package that does NOT depend on
# ``wormbase_core`` (e.g. agent-gateway, which composes the four
# stateful gates into its MCP chain) previously crashed at
# ``__init__.py`` load time because top-level ``wormbase_governance``
# re-exports ``RulesBasedRelevanceGate`` from this module.
#
# These types are only needed at runtime by callers that already pull
# ``wormbase_core`` into their environment (chat-presence,
# worm-core.service). For those callers the lazy import in
# ``RulesBasedRelevanceGate.handle`` resolves at first call. The
# typecheck-only import keeps annotations intact for static analyzers.
if TYPE_CHECKING:
    from wormbase_core.reactivity import (
        InfraEvent,
        RelevanceDecision,
        SemanticInterpretation,
    )
from wormbase_ledger import InMemoryLedger, Ledger


Talkativeness = Literal["lurker", "responsive", "proactive"]


_REACT_EVENT_TYPES = {"question", "data_mention", "credential_offer", "file_reference"}


_THRESHOLDS: dict[Talkativeness, float | None] = {
    # `lurker` is special — never reacts based on confidence alone.
    "lurker": None,
    "responsive": 0.85,
    "proactive": 0.75,
}


# === Step 2 (proactivity hook) ===================================================
#
# Demo arc this enables: Bob says "we should pull from Stripe" in #data; the
# relevance gate sees the keyword in the bare text (no @-mention required),
# fires ``should_react=True`` with ``suggested_flow="mentioned_in_conversation"``,
# and the worm offers to wire it up. Confidence threshold for this rule is 0.6
# — strong enough to act, low enough that the worm can hedge in the reply text.
#
# Keep this list aligned with ``_REMOTE_ARCHETYPE_URIS`` in flows.py: the gate
# detects the keyword, the flow translates it into a one-shot ``source_proposed``.
# Both are intentionally lower-cased + substring-matched; we want recall over
# precision in the demo, the gate's own confidence dampener guards false fires.
_DATA_SOURCE_KEYWORDS: tuple[str, ...] = (
    # SaaS APIs (matches recognized_remote_archetypes in flows.py)
    "stripe",
    "salesforce",
    "hubspot",
    # Warehouses / databases
    "snowflake",
    "postgres",
    "postgresql",
    # Object stores
    "s3",
    # Productivity sources
    "google sheets",
    "airtable",
    # Product analytics
    "mixpanel",
    "amplitude",
    "segment",
    # ELT / transform
    "fivetran",
    "dbt",
)


def _detect_data_source_mention(text: str) -> str | None:
    """Return the first matched data-source keyword in ``text``, lower-cased."""
    if not text:
        return None
    lower = text.lower()
    for kw in _DATA_SOURCE_KEYWORDS:
        if kw in lower:
            return kw
    return None


# Confidence floor at which the proactive mention rule can override the
# talkativeness threshold. Specced at 0.6 — high enough to require a real
# hit, low enough to allow the response to hedge ("I noticed you mentioned
# Stripe — want me to wire it up?").
_PROACTIVE_MENTION_CONFIDENCE = 0.60


class RulesBasedRelevanceGate:
    """Channel-aware rules: DM=always; @mention=always; talkativeness governs the rest."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
        *,
        mention_handle: str = "@worm",
        talkativeness: dict[str, Talkativeness] | None = None,
        default_talkativeness: Talkativeness = "responsive",
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._mention_handle = mention_handle.lower()
        self._talkativeness = talkativeness or {}
        self._default = default_talkativeness

    def talkativeness_for(self, channel_id: str | None) -> Talkativeness:
        if channel_id is None:
            return self._default
        return self._talkativeness.get(channel_id, self._default)

    def is_mentioned(self, text: str | None) -> bool:
        """Whether ``text`` contains the worm's @-mention handle.

        E4 cleanup pass: callers (the speech-rules state machine in
        conversation.py) previously reached for ``_mention_handle``
        directly. This is the public predicate they should use.
        """
        if not text or not self._mention_handle:
            return False
        return self._mention_handle in text.lower()

    async def handle(
        self, infra: "InfraEvent", interp: "SemanticInterpretation"
    ) -> "RelevanceDecision":
        # Lazy runtime import — see module-level note. Callers reaching
        # this method already have ``wormbase_core`` on their PYTHONPATH
        # (chat-presence + worm-core.service); environments that import
        # ``wormbase_governance`` only for the four stateful gates never
        # reach this branch.
        from wormbase_core.reactivity import RelevanceDecision  # noqa: F401

        # DM: always react.
        if infra.source == "dm":
            decision = RelevanceDecision(
                should_react=True,
                reason="dm_always_respond",
                suggested_flow=self._suggest_flow(interp),
            )
            await self._record(infra, decision)
            return decision

        text_lower = (infra.text or "").lower()
        mention_present = self._mention_handle and self._mention_handle in text_lower

        # @mention in channel: always react.
        if mention_present:
            decision = RelevanceDecision(
                should_react=True,
                reason="mention",
                suggested_flow=self._suggest_flow(interp),
            )
            await self._record(infra, decision)
            return decision

        # File drops always trigger source-building (regardless of talkativeness).
        if infra.source == "file_drop":
            decision = RelevanceDecision(
                should_react=True,
                reason="file_drop_passive_ingest",
                suggested_flow="drop_and_profile",
            )
            await self._record(infra, decision)
            return decision

        # === Step 2 (proactivity hook) ===
        # Data-source mention rule: if the bare text references a known data
        # archetype keyword (stripe / salesforce / hubspot / snowflake / postgres
        # / s3 / google sheets / airtable / mixpanel / amplitude / segment /
        # fivetran / dbt) AND the semantic classifier agrees this is a
        # data_mention with confidence >= 0.6, fire proactively. This is the
        # core of the "we should pull from Stripe" demo beat — the worm reacts
        # without an @-mention. The lurker channel still suppresses (the gate
        # records the suppression reason for trace).
        kw = _detect_data_source_mention(infra.text or "")
        tk_check = self.talkativeness_for(infra.channel_id)
        if (
            kw is not None
            and tk_check != "lurker"
            and interp.event_type == "data_mention"
            and interp.confidence >= _PROACTIVE_MENTION_CONFIDENCE
        ):
            decision = RelevanceDecision(
                should_react=True,
                reason=(
                    f"data_source_mention:{kw};"
                    f"confidence:{interp.confidence:.2f}"
                ),
                suggested_flow="mentioned_in_conversation",
            )
            await self._record(infra, decision)
            return decision

        # Otherwise: talkativeness governs.
        tk = self.talkativeness_for(infra.channel_id)
        threshold = _THRESHOLDS[tk]
        if threshold is None:
            decision = RelevanceDecision(
                should_react=False,
                reason="lurker_suppress",
            )
        elif (
            interp.confidence >= threshold
            and interp.event_type in _REACT_EVENT_TYPES
        ):
            decision = RelevanceDecision(
                should_react=True,
                reason=f"talkativeness:{tk};confidence:{interp.confidence:.2f}",
                suggested_flow=self._suggest_flow(interp),
            )
        else:
            decision = RelevanceDecision(
                should_react=False,
                reason=(
                    f"talkativeness:{tk};below_threshold "
                    f"({interp.confidence:.2f}<{threshold})"
                    if threshold is not None
                    else f"talkativeness:{tk}"
                ),
            )
        await self._record(infra, decision)
        return decision

    def _suggest_flow(self, interp: SemanticInterpretation) -> str | None:
        if interp.event_type == "credential_offer":
            return "credential_offered_in_dm"
        if interp.event_type == "file_reference":
            return "drop_and_profile"
        if interp.event_type == "data_mention":
            return "mentioned_in_conversation"
        return None

    async def _record(self, infra: InfraEvent, decision: RelevanceDecision) -> None:
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "relevance_decision",
                "proposed_by": "relevance",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"relevance:{decision.should_react}",
                    "tags": [
                        "relevance_decision",
                        f"react:{decision.should_react}",
                        f"reason:{decision.reason}",
                    ],
                },
                "result_ref": "relevance_decision",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "relevance_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "relevance decision",
            },
            timestamp=infra.ts or datetime.now(UTC),
            quadrant="passive_deterministic",
        )


__all__ = [
    "RulesBasedRelevanceGate",
    "Talkativeness",
    "_DATA_SOURCE_KEYWORDS",
]
