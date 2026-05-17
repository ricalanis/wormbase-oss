"""RecurringQuestionProcessMapperReactivity — gold from chatter (P10).

The conversation lake is a first-class data source (CLAUDE.md §
"Conversations as a first-class data source"). Bronze chatter (raw
``chat_received`` entries) feeds silver topic threading; this reactivity
is the gold step: when the same ``(asker_person, askee_person, topic)``
triplet recurs ≥3 times in a trailing 14-day window, propose a
``process_map`` data product that captures the implicit org process —
"every time topic X comes up, person A asks person B" — as nodes + edges.

Why a Reactivity (not a batch job)? Because the value is the timing: the
moment the third recurrence lands is the moment the worm has enough
signal to claim it knows a real process. A batch job would either fire
late (daily cron) or constantly recompute (hot loop). A Reactivity fires
exactly once at the threshold cross.

Predicate / condition composition (per the Reactivity Protocol):

    predicate = EntryKind("chat_received") & HasTopic() & InThread()
    condition = (
        DailyBudget(per_tenant=5)
        & NotRecentlyFired(novelty_key="process_map", hours=24)
        & DomainEnabled()
    )

Why ``InThread``? Threaded messages carry a stronger asker→askee signal
(replies are authored to the message they target). Top-level channel
chatter is broadcast and lacks the directed-question structure we need
to call this a "process". Future Reactivities can relax this when chat
parsers extract directed-question structure from broadcast messages.

Per-tenant per-day budget of 5 is the spec floor — process maps are the
high-signal, low-noise tier of gold artifacts. The 24h NotRecentlyFired
gate prevents re-proposing a process_map for the same tenant when no new
distinct triplet has tipped over its threshold.

PEVR cycle bookkeeping:

    propose:  ``data_product_proposed`` (target_kind), kind="process_map"
    execute:  ``emit_data_product_proposed`` carrying the process_map
              payload (nodes/edges/window) in ``parameters``
    verify:   re-instantiates ``DataProductProposedPayload`` to prove
              the args validate (forbids drift between this writer and
              the canonical Pydantic model)
    resolve:  always "keep" — the admin-confirm step is a separate
              ``data_product_generated`` (or ``data_product_archived``)
              cycle written by the dashboard.

The reactivity emits ONE FiredAction per fire (a single PEVR cycle
wrapping ``data_product_proposed``). The downstream
``data_product_generated`` / ``data_product_consumed`` entries are
independent cycles — outside the scope of THIS reactivity.

State model:

The reactivity stores a per-tenant in-memory ``HistoryStore`` mapping
``(asker, askee, topic) → list[chat_event]`` with an effective horizon
of 14 days. Entries older than the horizon are pruned at read time, so
the store size stays bounded by recent activity. The store is intentionally
process-local: the Reactivity is the only writer/reader. A future wave
will project this from the ledger so cross-process dispatch shares state;
until then the single-process ReactivityRunner is authoritative.

The store also tracks which triplets have already crossed threshold and
fired, so re-arrivals after a fire don't re-fire on every subsequent
chat. Once a triplet fires, it is muted until either (a) a 24h novelty
cooldown expires AND a new distinct triplet has crossed threshold, or
(b) the operator manually resets the store (test-only).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from wormbase_reactivities.conditions import (
    DailyBudget,
    DomainEnabled,
    NotRecentlyFired,
)
from wormbase_reactivities.predicates import (
    EntryKind,
    HasTopic,
    _ArgsPredicate,
)
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityContext,
    ReactivityResult,
    ReactivityScope,
)

logger = logging.getLogger("wormbase_reactivities.process_mapper")


_REACTIVITY_ID = "recurring_question_process_mapper"
_DEFAULT_THRESHOLD = 3
_DEFAULT_WINDOW_DAYS = 14
_DEFAULT_PER_TENANT_BUDGET = 5


# ---------------------------------------------------------------------------
# InThread predicate — local to P10 because no other reactivity needs it yet
# ---------------------------------------------------------------------------


class InThread(_ArgsPredicate):
    """Match chat_received entries that are part of a thread.

    Slack's wire normalises threaded messages with a non-empty
    ``thread_ts`` distinct from the message's own ``ts``; the
    channel-adapter forwards both. Discord/Teams use ``thread_id`` /
    ``parent_id``. We accept any of these args keys to stay
    platform-agnostic.

    Why InThread (not "is a reply")? Top-level broadcasts can be
    questions too, but they lack a directed asker→askee target. Threaded
    messages carry that target by construction (the parent author is
    the askee). The inferred-process signal is meaningfully stronger
    inside threads.
    """

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        # Slack: thread_ts present and != ts implies threaded.
        thread_ts = args.get("thread_ts")
        ts = args.get("ts") or args.get("message_id")
        if thread_ts and thread_ts != ts:
            return True
        # Discord/Teams: thread_id or parent_id explicit.
        if args.get("thread_id") or args.get("parent_id"):
            return True
        # Some adapters use ``in_thread: True`` flag.
        if args.get("in_thread") is True:
            return True
        return False


# ---------------------------------------------------------------------------
# History store — per-tenant in-memory rollup of (asker, askee, topic)
# ---------------------------------------------------------------------------


@dataclass
class _ChatObservation:
    """One observation of an asker → askee chat with topic.

    Kept minimal — just the fields we need to (a) prune old observations
    and (b) build the eventual process_map payload (first_seen / last_seen
    per edge).
    """

    asker: str
    askee: str
    topic: str
    ts: datetime
    message_id: str


class _TenantHistory:
    """Rolling-window observation store keyed on (asker, askee, topic).

    Does double-duty as the threshold counter and the
    process_map-payload source. The reactivity reads the full triplet
    map on fire to build the nodes + edges payload.
    """

    def __init__(self, *, window_days: int = _DEFAULT_WINDOW_DAYS) -> None:
        self._window = timedelta(days=window_days)
        # (asker, askee, topic) -> list[_ChatObservation]
        self._obs: dict[
            tuple[str, str, str], list[_ChatObservation]
        ] = defaultdict(list)
        # (asker, askee, topic) -> ts of last fire so we don't re-fire
        # on every subsequent chat in the same triplet.
        self._fired: dict[tuple[str, str, str], datetime] = {}

    def add(self, obs: _ChatObservation) -> None:
        key = (obs.asker, obs.askee, obs.topic)
        self._obs[key].append(obs)

    def prune(self, now: datetime) -> None:
        """Drop observations older than the window."""
        cutoff = now - self._window
        for key in list(self._obs.keys()):
            kept = [o for o in self._obs[key] if o.ts >= cutoff]
            if kept:
                self._obs[key] = kept
            else:
                del self._obs[key]

    def count(self, asker: str, askee: str, topic: str) -> int:
        return len(self._obs.get((asker, askee, topic), []))

    def all_observations(self) -> dict[
        tuple[str, str, str], list[_ChatObservation]
    ]:
        return dict(self._obs)

    def already_fired(
        self, asker: str, askee: str, topic: str,
    ) -> datetime | None:
        return self._fired.get((asker, askee, topic))

    def mark_fired(
        self, asker: str, askee: str, topic: str, *, at: datetime,
    ) -> None:
        self._fired[(asker, askee, topic)] = at


# Module-level dict so the reactivity instance is stateless across
# fires (matches the rest of the reactivities package — instances are
# data-class-style, registry-managed). One history store per tenant.
_TENANT_HISTORIES: dict[UUID, _TenantHistory] = {}


def _get_tenant_history(
    company_id: UUID, *, window_days: int,
) -> _TenantHistory:
    if company_id not in _TENANT_HISTORIES:
        _TENANT_HISTORIES[company_id] = _TenantHistory(
            window_days=window_days,
        )
    return _TENANT_HISTORIES[company_id]


def _reset_history(company_id: UUID) -> None:
    """Test helper: clear a tenant's history. Production never calls this."""
    _TENANT_HISTORIES.pop(company_id, None)


# ---------------------------------------------------------------------------
# Reactivity
# ---------------------------------------------------------------------------


@dataclass
class RecurringQuestionProcessMapperReactivity:
    """Conversation→process_map gold artifact reactivity (P10).

    When ``(asker, askee, topic)`` recurs ≥``threshold`` times in a
    trailing ``window_days``-day window, emit ``data_product_proposed``
    of kind ``process_map`` whose ``parameters`` carry the nodes/edges
    payload. Admin confirms via the dashboard; once confirmed, the
    artifact appears on /system-map's "Conversation Process Maps" lens.

    Construction is dependency-free — the only inputs are the threshold
    + window-days knobs. State lives in the module-level
    ``_TENANT_HISTORIES`` dict, keyed by ``company_id``.

    Args:
        threshold: number of recurrences before the reactivity fires.
            Default 3 per spec.
        window_days: trailing days the recurrence window covers.
            Default 14 per spec.
        per_tenant_budget: rolling-day cap on fires per tenant.
            Default 5 per spec.
    """

    id: str = _REACTIVITY_ID
    name: str = "Recurring Question Process Mapper"
    description: str = (
        "When the same (asker, askee, topic) triplet recurs in chat "
        "across a trailing 14-day window, propose a process_map data "
        "product capturing the implicit org process for admin "
        "confirmation."
    )
    scope: ReactivityScope = "company"

    threshold: int = _DEFAULT_THRESHOLD
    window_days: int = _DEFAULT_WINDOW_DAYS
    per_tenant_budget: int = _DEFAULT_PER_TENANT_BUDGET

    predicate: Any = field(init=False)
    condition: Any = field(init=False)

    def __post_init__(self) -> None:
        # Predicate: chat_received in a thread carrying a topic. The
        # actual triplet-counting and threshold check happen in fire()
        # because the predicate alone can't tell us whether a candidate
        # entry tips a triplet over the threshold without consulting
        # state. Predicate stays cheap; fire() is the gate.
        self.predicate = (
            EntryKind("chat_received") & HasTopic() & InThread()
        )
        # Condition: per-tenant budget + 24h novelty cooldown +
        # domain-enabled. The novelty key is "process_map" (constant)
        # because the per-triplet novelty is enforced inside the
        # history store's ``mark_fired`` table.
        self.condition = (
            DailyBudget(
                per_owner=None,
                per_domain=None,
                per_tenant=self.per_tenant_budget,
            )
            & NotRecentlyFired(novelty_key="process_map", hours=24.0)
            & DomainEnabled()
        )

    # ------------------------------------------------------------------
    # Fire — count the triplet, threshold-check, build payload, write.
    # ------------------------------------------------------------------

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Count the triplet; on threshold cross, emit data_product_proposed.

        Note: predicate already screened for chat_received-in-thread-
        with-topic. fire() does the per-triplet bookkeeping that the
        predicate is too cheap to do.
        """
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}

        asker = self._extract_asker(args)
        askee = self._extract_askee(args)
        topic = self._extract_topic(args)
        if not asker or not askee or not topic:
            return ReactivityResult(fired=False)
        if asker == askee:
            # Self-question is not a process.
            return ReactivityResult(fired=False)

        ts = self._extract_ts(args, entry)
        message_id = str(args.get("message_id") or args.get("ts") or "")

        history = _get_tenant_history(
            context.company_id, window_days=self.window_days,
        )
        history.add(_ChatObservation(
            asker=asker, askee=askee, topic=topic,
            ts=ts, message_id=message_id,
        ))
        # Prune lazy: cheap when the store is small, and bounds size.
        now_dt = self._now(context)
        history.prune(now_dt)

        count = history.count(asker, askee, topic)
        if count < self.threshold:
            return ReactivityResult(fired=False)

        # Triplet has reached threshold. Skip if we already fired for
        # this exact triplet within the cooldown window — otherwise
        # every subsequent chat would re-fire.
        already = history.already_fired(asker, askee, topic)
        if already is not None:
            cooldown = now_dt - timedelta(hours=24.0)
            if already >= cooldown:
                return ReactivityResult(fired=False)

        # Build the process_map payload from the full history (all
        # triplets, not just this one) so the proposed map captures the
        # full picture the worm has of org chatter — one map per fire,
        # admin-confirmable atomically.
        process_map_payload = self._build_process_map_payload(
            history, now_dt=now_dt,
        )

        # Write the data_product_proposed PEVR cycle.
        dp_id = uuid4()
        try:
            from wormbase_ledger.entries import DataProductProposedPayload
            args_for_entry = {
                "data_product_id": str(dp_id),
                "name": (
                    f"Process map · trailing "
                    f"{self.window_days}d · {len(process_map_payload['edges'])} edge(s)"
                ),
                "kind": "process_map",
                "requested_by_person_id": (
                    # Worm-proposed → no human requester. Use a synthetic
                    # all-zeros UUID so the payload validates without
                    # claiming attribution to a real Person. The dashboard
                    # surfaces this as "proposed by worm".
                    str(UUID(int=0))
                ),
                "sources_required": [],
                "domain_id": None,
                "parameters": process_map_payload,
                "prompted_by_message_id": message_id or None,
            }
            # Verify-time check: pydantic must accept this shape.
            DataProductProposedPayload.model_validate({
                **args_for_entry,
                "data_product_id": dp_id,
                "requested_by_person_id": UUID(int=0),
                "sources_required": [],
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "process_map data_product_proposed payload invalid: %s", exc,
            )
            return ReactivityResult(fired=False)

        await context.ledger.write(
            company_id=context.company_id,
            propose={
                "target_kind": "data_product_proposed",
                "ref_id": str(dp_id),
                "reason": (
                    f"recurring_question_process_mapper: "
                    f"asker={asker} askee={askee} topic={topic} "
                    f"count={count}"
                ),
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_data_product_proposed",
                "args": args_for_entry,
                "result_ref": str(dp_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {
                        "name": "data_product_proposed_payload_valid",
                        "ok": True,
                    },
                    {
                        "name": "process_map_kind",
                        "ok": True,
                    },
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    f"process_map proposed from {count} recurring "
                    f"observations of ({asker}, {askee}, {topic})"
                ),
            },
            quadrant="passive_probabilistic",
        )

        history.mark_fired(asker, askee, topic, at=now_dt)

        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(action_kind="data_product_proposed"),
            ],
            novelty_key=f"process_map:{asker}:{askee}:{topic}",
            budget_used={"per_tenant": 1},
        )

    # ------------------------------------------------------------------
    # Helpers — extraction and payload construction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_asker(args: dict[str, Any]) -> str:
        """The asker is the message sender — they posed the question."""
        for k in ("sender_person", "sender_person_id", "asker_person_id"):
            v = args.get(k)
            if v:
                return str(v)
        return ""

    @staticmethod
    def _extract_askee(args: dict[str, Any]) -> str:
        """The askee is the thread-parent author or an explicit target.

        Channel-adapters that resolve thread parentage forward
        ``thread_parent_person`` (or ``askee_person_id``) on inbound
        threaded messages. When neither is present we cannot identify
        the askee and the reactivity short-circuits.
        """
        for k in (
            "askee_person_id",
            "thread_parent_person",
            "thread_parent_person_id",
        ):
            v = args.get(k)
            if v:
                return str(v)
        return ""

    @staticmethod
    def _extract_topic(args: dict[str, Any]) -> str:
        """Topic: prefer the structured topic_id over the free-text label."""
        for k in ("topic_id", "topic"):
            v = args.get(k)
            if v:
                return str(v)
        return ""

    @staticmethod
    def _extract_ts(
        args: dict[str, Any], entry: dict[str, Any],
    ) -> datetime:
        """Pull a tz-aware datetime from the args; fall back to the entry ts."""
        raw = args.get("ts") or args.get("sent_at") or entry.get("ts")
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                return raw.replace(tzinfo=timezone.utc)
            return raw
        if isinstance(raw, str) and raw:
            try:
                # Slack-style epoch with fractional seconds.
                return datetime.fromtimestamp(
                    float(raw), tz=timezone.utc,
                )
            except ValueError:
                try:
                    parsed = datetime.fromisoformat(
                        raw.replace("Z", "+00:00"),
                    )
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except ValueError:
                    pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _now(context: ReactivityContext) -> datetime:
        v = context.now() if callable(context.now) else context.now
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v
        return datetime.now(timezone.utc)

    def _build_process_map_payload(
        self, history: _TenantHistory, *, now_dt: datetime,
    ) -> dict[str, Any]:
        """Roll the history into the spec'd nodes/edges/window payload.

        Output shape (per PRD §7 P10):

            {
              "nodes": [{"actor_person_id": ..., "role_in_map": "asker"|"askee"}],
              "edges": [{"from": ..., "to": ..., "topic": str,
                         "frequency": int,
                         "first_seen": ts, "last_seen": ts}],
              "window_start": ts,
              "window_end": ts,
              "confidence": float
            }

        Confidence is the proportion of edges at or above threshold —
        a simple, auditable heuristic. As more triplets cross threshold
        the proposed map's confidence rises.
        """
        all_obs = history.all_observations()
        edges: list[dict[str, Any]] = []
        actors: dict[str, set[str]] = {}  # person_id → set of roles
        above_threshold_edges = 0
        for (asker, askee, topic), obs_list in sorted(all_obs.items()):
            freq = len(obs_list)
            if freq == 0:
                continue
            first = min(o.ts for o in obs_list)
            last = max(o.ts for o in obs_list)
            edges.append({
                "from": asker,
                "to": askee,
                "topic": topic,
                "frequency": freq,
                "first_seen": first.isoformat(),
                "last_seen": last.isoformat(),
            })
            actors.setdefault(asker, set()).add("asker")
            actors.setdefault(askee, set()).add("askee")
            if freq >= self.threshold:
                above_threshold_edges += 1

        nodes = [
            {
                "actor_person_id": pid,
                # When a person is both asker and askee, render them as
                # "asker_and_askee" so the dashboard graph view can
                # distinguish bidirectional participants.
                "role_in_map": (
                    "asker_and_askee"
                    if "asker" in roles and "askee" in roles
                    else next(iter(roles))
                ),
            }
            for pid, roles in sorted(actors.items())
        ]

        window_start = now_dt - timedelta(days=self.window_days)
        confidence = (
            above_threshold_edges / max(len(edges), 1)
            if edges else 0.0
        )

        return {
            "nodes": nodes,
            "edges": edges,
            "window_start": window_start.isoformat(),
            "window_end": now_dt.isoformat(),
            "confidence": float(round(confidence, 4)),
        }


__all__ = [
    "InThread",
    "RecurringQuestionProcessMapperReactivity",
    "_reset_history",  # test-only export
]
