"""Process-worm Reactivities.

This module hosts the Reactivity classes that compose W5a primitives
(``EntryKind`` predicate, ``DailyBudget``/``NotRecentlyFired`` conditions,
etc.) over the ledger projection to drive process-worm behaviors:
recurring-question detection, decision extraction, system-map updates,
and topic-cluster synthesis.

Reactivities shipped:

* ``TopicSynthesisReactivity`` — Phase 2 Task 2B real implementation.
  Folds raw chat into per-tenant text-similarity clusters (using the
  ``topics.py`` machinery, which mirrors the ``recurring.py``
  primitives) and emits a ``topic_proposed`` PEVR cycle when a
  cluster crosses the topic-promotion threshold. Optional inference
  router via ``ReactivityContext.extras["topic_labeler"]`` produces a
  human-readable label (``call_type="summarize"``); a heuristic
  fallback keeps the Reactivity productive when the router is
  unwired.
* ``RecurringQuestionReactivity`` — alias to P10's existing
  ``RecurringQuestionProcessMapperReactivity`` (spike §8 C3).
* ``DecisionRecordReactivity`` — fires on ``chat_received`` matching
  ``MatchesDecisionPattern`` and emits a ``decision_recorded`` PEVR
  cycle. Lifted from worm-core's polling
  ``ProcessExtractor._extract_decisions`` / ``_emit_decision``.
* ``SystemMapNodeReactivity`` — chat → org system-map node updates,
  one node per fire in priority order.

Note: RecurringQuestionReactivity is the existing P10
``RecurringQuestionProcessMapperReactivity`` from
``wormbase_reactivities.process_mapper``. It already covers the
(asker, askee, topic) triplet → process_map signal. Process-worm's
factory registers it; no wrapper class is added here. See spike §8 C3.

The text-similarity clustering helper at ``recurring.py`` and the
parallel topic clustering at ``topics.py`` are complementary:
``recurring.py`` filters for questions and produces
``RecurringQuestionPayload``; ``topics.py`` runs the same primitives
on any chat text and produces ``TopicProposedPayload``. The two
modules share clustering primitives (Jaccard token overlap +
Levenshtein) for byte-equivalent similarity behaviour on shared
inputs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from wormbase_reactivities.conditions import (
    DailyBudget,
    DomainEnabled,
    NotRecentlyFired,
)
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.process_mapper import (
    RecurringQuestionProcessMapperReactivity as RecurringQuestionReactivity,
)
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityContext,
    ReactivityResult,
    ReactivityScope,
)

from wormbase_process_extractor.decisions import synthesize_decision
from wormbase_process_extractor.predicates import MatchesDecisionPattern
from wormbase_process_extractor.system_map import (
    flush_one_node,
    get_tenant_accumulator,
    update_from_chat_entry,
)
from wormbase_process_extractor.topics import (
    get_tenant_topic_store,
    update_topic_store_from_chat,
)


def _AVAILABLE(symbol: str) -> bool:
    """True iff ``symbol`` is exposed by ``wormbase_reactivities.conditions``.

    The plan spec for F.1 references an ``AlwaysTrue`` condition that
    *may* be added later; this guarded import lets the stub upgrade
    transparently the day it lands without a code change here. Until
    then the fallback is a ``DailyBudget`` whose caps are effectively
    infinite (10**9 fires/day/tenant).

    Kept as a private helper — not exported — so future authors don't
    treat it as a stable extension point.
    """
    try:
        import wormbase_reactivities.conditions as _conditions
    except Exception:
        return False
    return hasattr(_conditions, symbol)


# Late-bound to keep the import surface small when AlwaysTrue is absent.
if _AVAILABLE("AlwaysTrue"):  # pragma: no cover — exercised only when symbol exists
    from wormbase_reactivities.conditions import AlwaysTrue  # noqa: F401  type: ignore[attr-defined]  Forward-compatibility import; binds AlwaysTrue at module scope the day the symbol lands so downstream callers see it without a code change.


# ---------------------------------------------------------------------------
# Phase 2 Task 2B — TopicSynthesisReactivity real implementation
# ---------------------------------------------------------------------------
#
# Promotes the F.1 stub. Fire writes a ``topic_proposed`` PEVR cycle when
# a chat-text cluster crosses the topic-promotion threshold. Cluster
# membership comes from ``topics.py``; cluster labeling comes from the
# inference router (``call_type="summarize"``, default Gemma) when the
# router is wired, or a heuristic fallback when it isn't.
#
# Per spec acceptance: predicate stays ``EntryKind("chat_received")`` —
# the predicate slot is forever (Rule 1 of the schema-evolution
# doctrine) — and the id slot stays ``"topic_synthesis"``.

# Conventional context.extras key for an injected topic-labeler adapter.
# The factory (Block G.1) populates this when wormbase-llm /
# wormbase-inference-router is available; tests inject a stub directly.
# Mirrors the ``_LLM_EXTRAS_KEY`` shape used by DecisionRecordReactivity.
_TOPIC_LABELER_EXTRAS_KEY = "topic_labeler"

# Heuristic-only confidence — surfaced when no labeler is wired or the
# adapter returns ``None``. The dashboard renders a "needs review"
# badge below this threshold; the floor here matches the
# ``TopicProposedPayload.confidence`` default for symmetry.
_TOPIC_HEURISTIC_CONFIDENCE: float = 0.5


@runtime_checkable
class TopicLabeler(Protocol):
    """Optional inference-router adapter for topic-cluster labeling.

    Implementations consult an inference router with a summarize-shape
    prompt and return a ``(label, confidence, served_by)`` triple, or
    ``None`` when the router is unreachable or the response is
    unparseable. ``None`` triggers the Reactivity's heuristic fallback;
    the Reactivity still emits — the substrate's promise is that
    cluster-cross signals reach the ledger, blessed-by-router or not.

    The adapter is wired into ``ReactivityContext.extras`` under the
    ``topic_labeler`` key by the factory; tests inject a stub directly.
    """

    async def label_topic(
        self,
        *,
        cluster_signature: str,
        sample_messages: list[str],
        member_message_ids: list[str],
    ) -> tuple[str, float, str] | None: ...


def _resolve_topic_labeler(context: ReactivityContext) -> TopicLabeler | None:
    """Lazy-resolve an optional topic labeler from the Reactivity context.

    Returns ``None`` when no adapter is wired — the heuristic fallback
    still produces a valid (lower-confidence) ``TopicProposedPayload``.

    Mirrors the ``_resolve_llm_client`` shape used by
    DecisionRecordReactivity — the lazy pattern keeps this module's
    static import surface free of ``wormbase_inference_router``.
    """
    return context.extras.get(_TOPIC_LABELER_EXTRAS_KEY)


def _heuristic_topic_label(cluster_signature: str) -> str:
    """Fallback label when no router is wired or the call fails.

    Truncates the canonical signature to a usable length; the
    dashboard surfaces a "needs review" badge below the heuristic
    confidence threshold. Keeping this deterministic preserves
    replay-stability of the projection table when the substrate
    operates without a router.
    """
    label = cluster_signature.strip()
    if len(label) > 80:
        label = label[:77].rstrip() + "..."
    return label or "(empty cluster)"


@dataclass
class TopicSynthesisReactivity:
    """Reactivity: chat_received → text-similarity cluster → maybe emit
    one ``topic_proposed`` PEVR cycle.

    Predicate fires on every chat_received entry; the synthesis layer
    (``topics.update_topic_store_from_chat``) decides whether the
    update crosses the topic-promotion threshold. Below threshold the
    Reactivity returns ``fired=False`` and writes nothing to the
    ledger.

    Above threshold the Reactivity calls the optional injected
    ``TopicLabeler`` to label the cluster; on success the payload's
    ``label`` / ``confidence`` / ``served_by`` carry the router-blessed
    values, on failure the heuristic fallback fills them. Either way
    the PEVR cycle lands.

    Per-cluster idempotency comes from the ``topics.py`` store — it
    de-duplicates re-ingested ``message_id``s so deterministic ledger
    replay converges to the same projection state as the live fold.
    """

    id: str = "topic_synthesis"
    name: str = "Topic Synthesis"
    description: str = (
        "Folds raw chat into text-similarity clusters and emits a "
        "topic_proposed entry when a cluster crosses the promotion "
        "threshold; uses the inference router to label the cluster."
    )
    scope: ReactivityScope = "company"

    per_tenant_budget: int = 50

    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        # No NotRecentlyFired — the topics store's distinct-message_id
        # set already provides natural dedup. DomainEnabled keeps the
        # Reactivity off for tenants whose domain pack has the
        # process-worm disabled.
        self.condition = (
            DailyBudget(per_tenant=self.per_tenant_budget)
            & DomainEnabled()
        )

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}

        store = get_tenant_topic_store(context.company_id)
        emit_dict = update_topic_store_from_chat(args, store=store)
        if emit_dict is None:
            return ReactivityResult(fired=False)

        # Cluster crossed (or advanced past) the threshold — label and emit.
        labeler = _resolve_topic_labeler(context)
        label = _heuristic_topic_label(emit_dict["cluster_signature"])
        confidence = _TOPIC_HEURISTIC_CONFIDENCE
        served_by = "heuristic"

        if labeler is not None:
            # Sample-message heuristic: pull the first 3 chats from the
            # cluster's member set as evidence for the labeler. The
            # cluster only carries message_ids, not text; we pass the
            # incoming text plus the canonical signature, which is
            # sufficient for a summarize-shape prompt.
            sample = [args.get("text", "")] if args.get("text") else []
            try:
                result = await labeler.label_topic(
                    cluster_signature=emit_dict["cluster_signature"],
                    sample_messages=sample,
                    member_message_ids=emit_dict["member_message_ids"],
                )
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "topic-labeler call failed (%s); falling back to heuristic",
                    exc,
                )
                result = None
            if result is not None:
                router_label, router_conf, router_served = result
                # Defensive clamps — adapter could return out-of-range
                # values from a noisy upstream model. The payload's
                # validators would reject those anyway; clamping here
                # surfaces a usable label even on edge cases.
                if router_label and router_label.strip():
                    label = router_label.strip()[:256]
                confidence = max(0.0, min(1.0, float(router_conf)))
                # served_by is a Literal in the payload; only override
                # when the router returned a known value.
                if router_served in ("kimi", "gemma", "claude", "cache"):
                    served_by = router_served

        topic_id = emit_dict["topic_id"]
        # Build the args body matching ``TopicProposedPayload`` exactly
        # — the ledger validates on write so any drift surfaces here
        # rather than in the projection layer.
        args_for_entry: dict[str, Any] = {
            "topic_id": str(topic_id),
            "label": label,
            "cluster_signature": emit_dict["cluster_signature"],
            "cluster_size": emit_dict["cluster_size"],
            "member_message_ids": list(emit_dict["member_message_ids"]),
            "first_seen_at": emit_dict["first_seen_at"].isoformat(),
            "last_seen_at": emit_dict["last_seen_at"].isoformat(),
            "confidence": confidence,
            "served_by": served_by,
        }

        await _emit_pevr(
            context=context,
            target_kind="topic_proposed",
            ref_id=str(topic_id),
            reason=(
                f"topic_synthesis: cluster_size={emit_dict['cluster_size']}; "
                f"served_by={served_by}; "
                f"signature_len={len(emit_dict['cluster_signature'])}"
            ),
            args_for_entry=args_for_entry,
        )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="topic_proposed")],
            novelty_key=f"topic:{topic_id}",
            budget_used={"per_tenant": 1},
        )


# ---------------------------------------------------------------------------
# F.3 — DecisionRecordReactivity
# ---------------------------------------------------------------------------
#
# Lifted from apps/worm-core/src/wormbase_core/process_extractor.py:526-619
# (the batch-iter `_extract_decisions` method) plus :579-619 (`_emit_decision`).
# The legacy code polls a chat-row batch and emits multiple decisions per
# cycle; this Reactivity reshapes that to a single-entry trigger: predicate
# matches one chat_received entry → fire calls synthesize_decision() →
# (maybe) emit one PEVR cycle.
#
# Spike §3 "Reactivity-shape fit" table marks this lift as a clean shape
# match. The PEVR-emit pattern mirrors lake-maintainer's `_emit_signal`
# (packages/lake-maintainer/.../reactivities.py:61-100); the lazy LLM
# resolution mirrors phenomenon_gaps.py:431 (lazy import keeps the module
# import cheap so `import wormbase_process_extractor.reactivities` does
# not pull in `wormbase_llm`).


# Conventional context.extras key for an injected LLM client. The factory
# (Block G.1) populates this when wormbase-llm is available; tests inject
# a stub directly. Held here so the key is not duplicated across reactivities.
_LLM_EXTRAS_KEY = "decision_llm_client"


def _resolve_llm_client(context: ReactivityContext) -> Any:
    """Lazy-resolve an optional LLM client from the Reactivity context.

    Returns ``None`` when no client is wired — heuristic-only synthesis
    still produces a valid (low-confidence) ``DecisionPayload`` and the
    Reactivity emits with the admin-confirmation flow.

    Per spike §4 caveat (Kimi optional) and dispatch brief D3 — the lazy
    pattern mirrors ``phenomenon_gaps.py:431`` so this module's static
    import surface does not pull ``wormbase_llm``. Only ``context.extras``
    is consulted at call time.
    """
    return context.extras.get(_LLM_EXTRAS_KEY)


async def _emit_pevr(
    *,
    context: ReactivityContext,
    target_kind: str,
    ref_id: str,
    reason: str,
    args_for_entry: dict[str, Any],
    proposed_by: str = "process_extractor",
) -> None:
    """Emit one PEVR cycle for a process-worm Reactivity.

    Mirrors the canonical helper shape from
    ``packages/lake-maintainer/.../reactivities.py:_emit_signal`` so the
    process-worm and lake-maintainer wires are byte-equivalent on the
    ledger entries they produce. ``verify_fn`` always passes and
    ``resolve_fn`` always keeps — the synthesis itself is the
    discriminator; the Reactivity already short-circuited if the payload
    was unproduced. Same quadrant tag the legacy
    ``ProcessExtractor._write_payload`` used (``passive_probabilistic``)
    so /trace continues to bucket decision-record entries identically
    pre- and post-extraction.
    """
    tool = f"emit_{target_kind}"
    await context.ledger.write(
        company_id=context.company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": ref_id,
            "reason": reason,
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args_for_entry,
            "result_ref": ref_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"{tool} persisted",
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


@dataclass
class DecisionRecordReactivity:
    """Reactivity: chat_received with decision-language → decision_recorded.

    Predicate fires per chat that matches MatchesDecisionPattern.
    Condition gates per-tenant DailyBudget + 1h NotRecentlyFired
    (per-message-id novelty key). fire() calls
    ``synthesize_decision()`` and writes the PEVR cycle.

    Lifted from worm-core's process_extractor.py:526-619 +
    _emit_decision:579-619. Reshaped from batch-iter to single-entry
    Reactivity. Spike §3 'Reactivity-shape fit' table marks this as
    a clean shape match.
    """

    id: str = "decision_record"
    name: str = "Decision Record"
    description: str = (
        "Detects decision-language chat utterances and emits a "
        "decision_recorded entry; admin confirms via /decisions."
    )
    scope: ReactivityScope = "company"

    per_tenant_budget: int = 20
    novelty_hours: float = 1.0

    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = EntryKind("chat_received") & MatchesDecisionPattern()
        self.condition = (
            DailyBudget(per_tenant=self.per_tenant_budget)
            & NotRecentlyFired(novelty_key="decision", hours=self.novelty_hours)
            & DomainEnabled()
        )

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}

        # Lazy LLM resolution — keeps package import cheap. Per spike §4
        # caveat (Kimi optional) and dispatch brief D3; mirrors
        # phenomenon_gaps.py:431.
        llm = _resolve_llm_client(context)  # may return None

        decision_payload = await synthesize_decision(args, llm=llm)
        if decision_payload is None:
            return ReactivityResult(fired=False)

        # Heuristic-only paths return low confidence; emit anyway with
        # admin-confirmation flow. The ledger entry carries the confidence
        # so /decisions can render a "needs review" badge.
        message_id = str(args.get("message_id") or args.get("ts") or "")
        decision_id_str = str(decision_payload.decision_id)
        await _emit_pevr(
            context=context,
            target_kind="decision_recorded",
            ref_id=decision_id_str,
            reason=(
                f"decision_record: matched_pattern; "
                f"confidence={decision_payload.confidence:.2f}; "
                f"message_id={message_id}"
            ),
            args_for_entry=decision_payload.model_dump(mode="json"),
        )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="decision_recorded")],
            novelty_key=f"decision:{message_id}" if message_id else "decision",
            budget_used={"per_tenant": 1},
        )


# ---------------------------------------------------------------------------
# F.4 — SystemMapNodeReactivity
# ---------------------------------------------------------------------------
#
# Lifted from apps/worm-core/src/wormbase_core/process_extractor.py:712-774
# (the polling _update_system_map / _flush_system_map methods) plus
# _SystemMapAccumulator:198-340 (now SystemMapAccumulator at system_map.py).
#
# Spike §4 caveat 5: the polling implementation flushed all dirty nodes per
# batch; this Reactivity flushes one node per fire in priority order
# (highest cumulative edge weight first; ties broken by node-id sort).
# The behavioural-drift regression test in tests/test_reactivities.py
# (test_system_map_flush_one_per_fire_drift) is the canonical guard.


@dataclass
class SystemMapNodeReactivity:
    """Reactivity: chat_received → update accumulator → maybe emit one
    system_map_node.

    Per spike §4 caveat 5: the polling implementation flushed all
    dirty nodes per batch; this Reactivity flushes one node per fire,
    in priority order (highest cumulative edge weight first; ties
    broken by node-id sort).

    The DailyBudget(per_tenant=N) condition controls flush cadence
    indirectly: with budget=N, at most N nodes emit per tenant per
    day. Default 50 — generous enough that for early tenants the
    accumulator drains within a day, but rate-limited enough that a
    noisy tenant doesn't flood the ledger.

    Lifted from worm-core's process_extractor.py:712-774 +
    _SystemMapAccumulator:198-340 (now SystemMapAccumulator at
    ``system_map.py``).
    """

    id: str = "system_map_node"
    name: str = "System Map Node"
    description: str = (
        "Updates the per-tenant org system map from chat traffic; "
        "emits one node per fire in priority order."
    )
    scope: ReactivityScope = "company"

    per_tenant_budget: int = 50
    novelty_hours: float = 24.0

    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = (
            DailyBudget(per_tenant=self.per_tenant_budget)
            & DomainEnabled()
        )
        # Note: NotRecentlyFired is intentionally absent. The
        # accumulator's own dirty-set is the dedup gate; once a node
        # is flushed it goes clean and won't re-emit until traffic
        # touches it again.

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}

        accumulator = get_tenant_accumulator(context.company_id)
        update_from_chat_entry(args, accumulator=accumulator)

        node_payload = flush_one_node(accumulator)
        if node_payload is None:
            return ReactivityResult(fired=False)

        await _emit_pevr(
            context=context,
            target_kind="system_map_node",
            ref_id=node_payload.node_id,
            reason=(
                f"system_map_node: kind={node_payload.node_kind} "
                f"node_id={node_payload.node_id}"
            ),
            args_for_entry=node_payload.model_dump(mode="json"),
        )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="system_map_node")],
            novelty_key=f"system_map_node:{node_payload.node_id}",
            budget_used={"per_tenant": 1},
        )


__all__ = [
    "DecisionRecordReactivity",
    "RecurringQuestionReactivity",
    "SystemMapNodeReactivity",
    "TopicSynthesisReactivity",
]
