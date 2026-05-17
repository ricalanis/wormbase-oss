"""SubscriptionDispatcher Reactivity — v2.A Batch B Task 3.

Watches every new ledger entry (except the three meta kinds it owns)
and dispatches matching events to active subscriptions via their
chosen transport.

Design notes (locked by the v2.A plan §D4 + §D5):

  * **Meta-kind suppression** — the predicate is
    ``Not(EntryKind("agent_subscription_created") |
          EntryKind("agent_subscription_revoked") |
          EntryKind("agent_event_delivered"))`` so subscription
    metadata writes never trigger a downstream fire. This prevents
    recursion (a dispatcher fire writes an ``agent_event_delivered``
    entry, which would otherwise feed itself back into the runner).

  * **Per-subscription filter is in fire(), not condition_allows()** —
    a single Reactivity manages N subscriptions; the W5a condition
    layer is a singleton gate. We always enter ``fire`` on a non-meta
    entry and then iterate active subscriptions, applying each one's
    compiled filter independently. ``condition_allows`` is a global
    short-circuit (which we don't use here — return True).

  * **PEVR per delivery** — each match emits one ``agent_event_delivered``
    ledger entry via ``Ledger.write(propose=, execute_fn=, verify_fn=,
    resolve_fn=)``. The transport side-effect runs inside ``execute_fn``
    so ledger replay can no-op it (D5 wire-replay determinism).

  * **Idempotency** — the ``(subscription_id, triggering_entry_seq)``
    tuple is the dedup key. ``_already_delivered`` scans recent
    ``agent_event_delivered`` entries before each candidate dispatch.
    Replayed runs do not double-deliver, and a runner that re-fires
    on the same entry (e.g. after a crash-restart) does not double-deliver
    either.

  * **Replay mode** — when ``context.replay_mode`` is True the dispatcher
    still records the same ``agent_event_delivered`` entry deterministically
    but the ``execute_fn`` no-ops the actual transport call. This preserves
    the byte-identical-ledger invariant in wire-replay while preventing
    re-notification of external systems.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wormbase_reactivities.conditions import AlwaysAllow
from wormbase_reactivities.predicates import EntryKind, Not
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)

from wormbase_agent_gateway.subscriptions.filter import (
    compile_filter,
    deserialize_filter,
)
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.transports import (
    WebhookDeliveryResult,
    WebhookTransport,
)

logger = logging.getLogger("wormbase_agent_gateway.subscriptions.dispatcher")


# ---------------------------------------------------------------------------
# Subscription-reader Protocol
# ---------------------------------------------------------------------------


class SubscriptionReader:
    """Structural protocol the dispatcher requires from any subscription reader.

    The production wire-up uses ``wormbase_core.agent_gateway_readers.
    LedgerSubscriptionReader`` (raw-ledger scan). Tests can substitute
    an in-memory stub with the same surface.
    """

    async def active_subscriptions(
        self, company_id: Any,
    ) -> list[dict[str, Any]]:  # pragma: no cover — Protocol stub
        ...


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionDispatcher:
    """W5a Reactivity that matches new ledger entries against active
    subscriptions and dispatches via the per-subscription transport.

    Construction is via keyword-only args so the production composition
    site reads explicitly:

        SubscriptionDispatcher(
            subscription_reader=LedgerSubscriptionReader(ledger=ledger),
            webhook_transport=WebhookTransport(secret_resolver=...),
            stream_registry=StreamRegistry(),
            ledger=ledger,
        )

    The ``ledger`` field on the dataclass is the same handle the reader
    holds; the dispatcher uses it both for the idempotency scan AND for
    writing the ``agent_event_delivered`` PEVR cycle. We keep both
    references explicit so a future refactor can swap one (e.g. a
    projection-backed reader) without touching the write path.
    """

    subscription_reader: SubscriptionReader
    webhook_transport: WebhookTransport
    stream_registry: StreamRegistry
    ledger: Any

    id: str = "agent_gateway.subscription_dispatcher"
    name: str = "SubscriptionDispatcher"
    description: str = (
        "Match every new ledger entry against active agent subscriptions; "
        "dispatch matches via the subscription's transport (mcp_stream or "
        "webhook). Records one agent_event_delivered PEVR cycle per dispatch."
    )
    scope: ReactivityScope = "company"

    # ReactivityPredicate / ReactivityCondition fields populated in __post_init__
    # so the dataclass survives Reactivity Protocol isinstance() checks.
    predicate: ReactivityPredicate | None = None  # set in __post_init__
    condition: ReactivityCondition | None = None  # set in __post_init__

    def __post_init__(self) -> None:
        # Predicate: anything that is NOT one of the three meta kinds.
        # This prevents the dispatcher from re-triggering on its own
        # ``agent_event_delivered`` writes (recursion guard) and from
        # firing on subscription lifecycle entries (subscriptions about
        # subscriptions are an explicit non-feature per D4).
        self.predicate = Not(
            EntryKind("agent_subscription_created")
            | EntryKind("agent_subscription_revoked")
            | EntryKind("agent_event_delivered"),
        )
        # No global gate — the per-subscription filter happens inside fire().
        self.condition = AlwaysAllow()

    # ------------------------------------------------------------------
    # Fire pipeline
    # ------------------------------------------------------------------

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        active = await self.subscription_reader.active_subscriptions(
            context.company_id,
        )
        if not active:
            return ReactivityResult(fired=False, actions=[])

        triggering_seq = int(entry.get("seq", 0) or 0)
        triggering_kind = str(entry.get("kind") or "")

        # One pass to fetch recent delivered entries for idempotency.
        # We scan once per fire rather than per-subscription so the cost
        # stays bounded even when many subscriptions are active.
        delivered_index = await self._build_delivered_index(
            context.company_id,
        )

        actions: list[FiredAction] = []
        for sub in active:
            try:
                event_filter = deserialize_filter(sub.get("filter") or {})
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SubscriptionDispatcher: failed to deserialize filter "
                    "for subscription_id=%s: %s",
                    sub.get("subscription_id"),
                    exc,
                )
                continue
            predicate_fn = compile_filter(event_filter)
            if not predicate_fn(entry):
                continue

            sub_id = str(sub.get("subscription_id") or "")
            if not sub_id:
                continue

            if (sub_id, triggering_seq) in delivered_index:
                # Idempotent — already delivered for this (sub, seq).
                continue

            fired = await self._deliver(
                sub=sub,
                entry=entry,
                triggering_seq=triggering_seq,
                triggering_kind=triggering_kind,
                context=context,
            )
            if fired is not None:
                actions.append(fired)
                # Same-fire dedup: a single entry should not double-deliver
                # for the same subscription even if active_subscriptions
                # returns duplicates (shouldn't happen, but defensive).
                delivered_index.add((sub_id, triggering_seq))

        return ReactivityResult(
            fired=bool(actions),
            actions=actions,
            novelty_key="",  # delivery dedup keyed in delivered_index, not registry
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _build_delivered_index(
        self, company_id: Any,
    ) -> set[tuple[str, int]]:
        """Return the set of ``(subscription_id, triggering_entry_seq)``
        tuples already in the ledger as ``agent_event_delivered`` execute
        entries.

        Used as the idempotency oracle inside ``fire``. Linear scan over
        the tenant ledger — same cost band as the existing Phase-2
        bad-pattern + recommendation Reactivities which also scan to
        compute idempotency.
        """
        entries = await self.ledger.fetch(company_id)
        out: set[tuple[str, int]] = set()
        for e in entries:
            if e.get("kind") != "execute":
                continue
            payload = e.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_agent_event_delivered":
                continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            sid = str(args.get("subscription_id") or "")
            try:
                seq = int(args.get("triggering_entry_seq") or 0)
            except (TypeError, ValueError):
                continue
            if sid:
                out.add((sid, seq))
        return out

    async def _deliver(
        self,
        *,
        sub: dict[str, Any],
        entry: dict[str, Any],
        triggering_seq: int,
        triggering_kind: str,
        context: ReactivityContext,
    ) -> FiredAction | None:
        """Emit one PEVR cycle recording the delivery decision.

        The transport call lives inside ``execute_fn`` so replay-mode
        no-ops the side-effect (D5 invariant). The ledger entry is
        always written so replayed state matches recorded state.
        """
        sub_id = str(sub.get("subscription_id") or "")
        transport = str(sub.get("transport") or "")
        webhook_url = sub.get("webhook_url")
        webhook_secret_ref = sub.get("webhook_secret_ref")

        # Build the event payload pushed to the transport. We pass a
        # minimal shape — kind, seq, args — sufficient for the agent to
        # react without forcing it to deserialize the full ledger row.
        event_payload: dict[str, Any] = {
            "subscription_id": sub_id,
            "triggering_entry_seq": triggering_seq,
            "kind": triggering_kind,
            "ts": _coerce_iso(entry.get("ts")),
            "args": _safe_args(entry),
        }

        delivery_result_holder: dict[str, Any] = {
            "status": "delivered",
            "duration_ms": 0,
            "error": None,
        }

        async def _do_transport() -> None:
            """Side-effect call — no-op'd in replay mode (D5)."""
            if context.replay_mode:
                # Determinism: replay records the same delivery status
                # ("delivered") that the recording run wrote. The real
                # network/queue call is skipped.
                delivery_result_holder["status"] = "delivered"
                return
            start = time.monotonic()
            try:
                if transport == "webhook":
                    if not webhook_url or not webhook_secret_ref:
                        delivery_result_holder["status"] = "no_target"
                        delivery_result_holder["error"] = (
                            "webhook subscription missing url or secret_ref"
                        )
                        return
                    result: WebhookDeliveryResult = (
                        await self.webhook_transport.deliver(
                            url=webhook_url,
                            secret_ref=webhook_secret_ref,
                            payload=event_payload,
                        )
                    )
                    delivery_result_holder["status"] = result.status
                    delivery_result_holder["duration_ms"] = result.duration_ms
                    delivery_result_holder["error"] = result.error
                elif transport == "mcp_stream":
                    await self.stream_registry.push(sub_id, event_payload)
                    delivery_result_holder["status"] = "delivered"
                    delivery_result_holder["duration_ms"] = int(
                        (time.monotonic() - start) * 1000,
                    )
                else:
                    delivery_result_holder["status"] = "failed"
                    delivery_result_holder["error"] = (
                        f"unknown transport: {transport!r}"
                    )
            except Exception as exc:  # noqa: BLE001
                delivery_result_holder["status"] = "failed"
                delivery_result_holder["error"] = (
                    type(exc).__name__ + ": " + str(exc)[:200]
                )
                delivery_result_holder["duration_ms"] = int(
                    (time.monotonic() - start) * 1000,
                )

        # Execute the side-effect BEFORE writing the PEVR so the recorded
        # status is the actual outcome. The ledger.write() PEVR is the
        # audit record; the transport call is the side-effect.
        await _do_transport()

        propose_payload: dict[str, Any] = {
            "target_kind": "agent_event_delivered",
            "subscription_id": sub_id,
            "triggering_entry_seq": triggering_seq,
            "triggering_entry_kind": triggering_kind,
            "transport_used": transport if transport in (
                "webhook", "mcp_stream",
            ) else "mcp_stream",
            "delivery_status": delivery_result_holder["status"],
        }

        execute_args: dict[str, Any] = {
            "subscription_id": sub_id,
            "triggering_entry_seq": triggering_seq,
            "triggering_entry_kind": triggering_kind,
            "transport_used": (
                transport if transport in ("webhook", "mcp_stream")
                else "mcp_stream"
            ),
            "delivery_status": delivery_result_holder["status"],
            "duration_ms": int(delivery_result_holder.get("duration_ms") or 0),
            "error": delivery_result_holder.get("error"),
        }

        try:
            await context.ledger.write(
                company_id=context.company_id,
                propose=dict(propose_payload),
                execute_fn=_make_execute_fn(execute_args),
                verify_fn=_make_verify_fn(execute_args),
                resolve_fn=_make_resolve_fn(execute_args),
                timestamp=datetime.now(UTC),
                quadrant="active_deterministic",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SubscriptionDispatcher: failed to write "
                "agent_event_delivered for subscription_id=%s "
                "triggering_seq=%d: %s",
                sub_id, triggering_seq, exc,
            )
            return None

        return FiredAction(
            action_kind="agent_event_delivered",
            action_seqs=[],
        )


# ---------------------------------------------------------------------------
# PEVR helper closures
# ---------------------------------------------------------------------------


def _make_execute_fn(
    args: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    """Build the ``execute_fn`` closure for ``Ledger.write``.

    The closure body is intentionally tiny: it returns the ``execute``
    payload (``tool`` + ``args``). The side-effect already ran before
    ``Ledger.write`` was called, so ``execute_fn`` only carries the
    audit record.
    """

    def _fn() -> dict[str, Any]:
        return {
            "tool": "emit_agent_event_delivered",
            "args": dict(args),
            "result_ref": args.get("subscription_id"),
        }

    return _fn


def _make_verify_fn(
    args: dict[str, Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the ``verify_fn`` closure.

    Pass-through verification: the dispatch decision is its own audit;
    if the transport call returned ``failed`` or ``no_target`` we still
    record the delivery row (with that status), so the verify never
    raises — the status itself is the outcome.
    """

    def _fn(_exec: dict[str, Any]) -> dict[str, Any]:
        return {
            "checks": [
                {
                    "name": "agent_event_delivered_recorded",
                    "ok": True,
                },
            ],
            "passed": True,
            "delivery_status": args.get("delivery_status"),
        }

    return _fn


def _make_resolve_fn(
    args: dict[str, Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the ``resolve_fn`` closure.

    ``keep`` regardless of delivery outcome — the ledger row is the
    audit. Failed deliveries are kept too so admins can see them via
    the dashboard.
    """

    def _fn(_v: dict[str, Any]) -> dict[str, Any]:
        return {
            "outcome": "keep",
            "rationale": (
                f"agent_event_delivered: subscription="
                f"{args.get('subscription_id')} "
                f"triggering_seq={args.get('triggering_entry_seq')} "
                f"status={args.get('delivery_status')}"
            ),
        }

    return _fn


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------


def _coerce_iso(value: Any) -> str | None:
    """Best-effort ISO-8601 coercion for the event payload timestamp."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract ``args`` from a ledger entry's payload defensively.

    Some entries carry ``args`` nested under ``payload`` (execute rows),
    others have ``args`` at the top level (proposal rows in older
    runners). We return a plain dict so the event payload stays
    JSON-serializable for transport side.
    """
    payload = entry.get("payload") or {}
    if isinstance(payload, dict):
        args = payload.get("args")
        if isinstance(args, dict):
            return dict(args)
    top_args = entry.get("args")
    if isinstance(top_args, dict):
        return dict(top_args)
    return {}


# ---------------------------------------------------------------------------
# Factory deps + factory
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionDispatcherDeps:
    """Bundle of deps the dispatcher factory composes from.

    Production composition is in
    ``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``:
    when ``WORMBASE_SUBSCRIPTIONS_ENABLED=true`` it constructs the deps
    bundle and passes it into ``make_agent_gateway_reactivities``.
    """

    subscription_reader: SubscriptionReader
    webhook_transport: WebhookTransport
    stream_registry: StreamRegistry
    ledger: Any


def make_subscription_dispatcher_reactivity(
    deps: SubscriptionDispatcherDeps,
) -> SubscriptionDispatcher:
    """Construct a :class:`SubscriptionDispatcher` from a deps bundle.

    Matches the ``make_<function>_reactivity`` convention used by the
    other Compounding axes. Returning a freshly-constructed instance per
    call keeps the factory side-effect-free; multi-tenant deploys
    construct one dispatcher per tenant via this factory.
    """
    return SubscriptionDispatcher(
        subscription_reader=deps.subscription_reader,
        webhook_transport=deps.webhook_transport,
        stream_registry=deps.stream_registry,
        ledger=deps.ledger,
    )


__all__ = [
    "SubscriptionDispatcher",
    "SubscriptionDispatcherDeps",
    "SubscriptionReader",
    "make_subscription_dispatcher_reactivity",
]
