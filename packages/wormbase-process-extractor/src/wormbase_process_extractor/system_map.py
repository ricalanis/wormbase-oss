"""D.1 — single-entry system-map synthesis.

Lifted from ``apps/worm-core/src/wormbase_core/process_extractor.py:198-340``
(the ``_SystemMapAccumulator`` dataclass) and ``:712-774`` (the legacy
``_update_system_map`` / ``_flush_system_map`` methods). The legacy code
operated on a *batch* of ``_ChatRow`` and flushed *all* dirty nodes per
batch; this module reshapes into:

* ``SystemMapAccumulator`` — public per-tenant mutable state (Counters
  for person→person mentions, person→channel speaks-in, channel→topic
  distribution), plus a ``dirty_nodes`` set tracking which node ids the
  next ``flush_one_node`` should consider.
* ``update_from_chat_entry(args, *, accumulator)`` — the single-entry
  reshape of ``_update_system_map``. Mutates the accumulator with one
  chat's actor + mentions + channel + topic.
* ``flush_one_node(accumulator)`` — emits **one** ``SystemMapNodePayload``
  per call (the highest-priority dirty node, where priority = sum of
  edge weights, ties broken by node-id sort), or ``None`` once the dirty
  set is exhausted.
* ``get_tenant_accumulator(company_id)`` — module-level lazy per-tenant
  registry, mirroring P10's ``_TENANT_HISTORIES`` pattern in
  ``packages/reactivities/.../process_mapper.py:60-62``. Same caveat:
  cross-process dispatch needs a projection-backed accumulator (out of
  scope for v1).

**Behavioural drift:** the polling loop's ``_flush_system_map`` flushed
all dirty nodes at once (one PEVR cycle per node, all in a tight loop).
The Reactivity model emits one node per fire — see spike §4 caveat 5
for the rationale. This is the canonical behavioural drift Wave C₂
introduces; it preserves the cumulative edge state but spreads emission
across multiple Reactivity fires.

The module is import-cheap: no LLM, no httpx, no Postgres. The
Reactivity wired by Block F.4 obtains the per-tenant accumulator via
``get_tenant_accumulator`` and calls ``update_from_chat_entry`` per
inbound chat plus ``flush_one_node`` per fire.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from wormbase_ledger.entries import SystemMapNodePayload

# Lifted verbatim from process_extractor.py:712 — single source of truth
# for which @-mention shapes contribute system-map edges.
_MENTION_PATTERN = re.compile(r"@(\w[\w.-]*)")

# Lifted verbatim from process_extractor.py:96-102 — domain-keyword hints
# used to bucket channel→topic edges. Held here rather than imported from
# the legacy module so this package stays free of worm-core imports.
_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "finance": ("q3", "q4", "close", "revenue", "invoice", "stripe", "runway"),
    "eng": ("deploy", "release", "incident", "rollback", "ci", "build", "merge"),
    "marketing": ("campaign", "launch", "newsletter", "ads", "spend"),
    "sales": ("pipeline", "lead", "deal", "renewal", "churn"),
    "ops": ("on-call", "oncall", "ticket", "support", "sev"),
}


def _detect_domain(text: str) -> str:
    """Lifted verbatim from ``process_extractor.py:105-111``."""
    lo = text.lower()
    for dom, hints in _DOMAIN_HINTS.items():
        for h in hints:
            if h in lo:
                return dom
    return "general"


# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------


@dataclass
class SystemMapAccumulator:
    """Per-tenant tally for who-mentions-whom and channel-topic distribution.

    Lifted from ``_SystemMapAccumulator`` (process_extractor.py:198-205) and
    extended with a ``dirty_nodes`` set so ``flush_one_node`` can emit one
    node per fire without re-scanning every Counter on every call.

    The three Counters mirror the legacy attributes verbatim:

    * ``person_to_person`` — ``(sender_id, mentioned_token) -> weight``
    * ``person_to_channel`` — ``(sender_id, channel_id) -> weight``
    * ``channel_to_topic`` — ``channel_id -> Counter[domain]``

    Mutating helpers (``add_message`` etc.) are convenience wrappers; the
    canonical entry point is :func:`update_from_chat_entry`, which calls
    them in the right order and flips the dirty bits.
    """

    person_to_person: Counter[tuple[str, str]] = field(default_factory=Counter)
    channel_to_topic: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    person_to_channel: Counter[tuple[str, str]] = field(default_factory=Counter)
    dirty_nodes: set[str] = field(default_factory=set)

    def add_message(
        self,
        *,
        sender_id: str,
        channel_id: str,
        text: str,
    ) -> None:
        """Mutate the three Counters with one chat's contribution."""
        if sender_id and channel_id:
            self.person_to_channel[(sender_id, channel_id)] += 1
        for m in _MENTION_PATTERN.finditer(text):
            target = m.group(1)
            if sender_id and target:
                self.person_to_person[(sender_id, target)] += 1
        if channel_id:
            domain = _detect_domain(text)
            self.channel_to_topic[channel_id][domain] += 1

    def mark_dirty(self, node_id: str) -> None:
        """Flag ``node_id`` for emission on the next flush."""
        if node_id:
            self.dirty_nodes.add(node_id)

    def clear_dirty(self, node_id: str) -> None:
        """Drop ``node_id`` from the pending-emit set."""
        self.dirty_nodes.discard(node_id)

    def node_kind_for(self, node_id: str) -> str:
        """Return ``"channel"`` if the id heads a channel→topic Counter,
        else ``"person"``. Channel ids dominate when both contribute (the
        legacy flush emitted both in turn; here we treat channel-id-shaped
        nodes as channels first since they only enter the accumulator via
        :meth:`add_message`'s channel path)."""
        if node_id in self.channel_to_topic:
            return "channel"
        return "person"

    def edges_for(self, node_id: str) -> list[dict[str, Any]]:
        """Return the edge list for one node, in the legacy emission order:
        ``mentions`` then ``speaks_in`` for persons; ``topic`` for channels.

        Mirrors ``_flush_system_map`` (process_extractor.py:733-771) but
        scoped to a single node-id rather than iterating every key.
        """
        if node_id in self.channel_to_topic:
            topics = self.channel_to_topic[node_id]
            return [
                {"kind": "topic", "target_id": t, "weight": float(w)}
                for t, w in topics.items()
                if w > 0
            ]
        edges: list[dict[str, Any]] = []
        for (s, dst), w in self.person_to_person.items():
            if s == node_id and w > 0:
                edges.append(
                    {"kind": "mentions", "target_id": dst, "weight": float(w)}
                )
        for (s, ch), w in self.person_to_channel.items():
            if s == node_id and w > 0:
                edges.append(
                    {"kind": "speaks_in", "target_id": ch, "weight": float(w)}
                )
        return edges


# ---------------------------------------------------------------------------
# Per-tenant module-level registry
# ---------------------------------------------------------------------------


# Mirrors ``_TENANT_HISTORIES`` in
# ``packages/reactivities/src/wormbase_reactivities/process_mapper.py:222``.
# Same caveat: the dict is per-process; cross-process Reactivity dispatch
# would need a projection-backed accumulator. Out of scope for v1.
_TENANT_ACCUMULATORS: dict[UUID, SystemMapAccumulator] = {}


def get_tenant_accumulator(company_id: UUID) -> SystemMapAccumulator:
    """Lazily construct and return the per-tenant ``SystemMapAccumulator``.

    Reactivity wiring (Block F.4) calls this once per fire to obtain the
    living accumulator before invoking :func:`update_from_chat_entry` and
    :func:`flush_one_node`.
    """
    accumulator = _TENANT_ACCUMULATORS.get(company_id)
    if accumulator is None:
        accumulator = SystemMapAccumulator()
        _TENANT_ACCUMULATORS[company_id] = accumulator
    return accumulator


def _reset_tenant_accumulator(company_id: UUID) -> None:
    """Test hook — drop one tenant's accumulator state."""
    _TENANT_ACCUMULATORS.pop(company_id, None)


# ---------------------------------------------------------------------------
# Single-entry update + per-fire flush
# ---------------------------------------------------------------------------


def update_from_chat_entry(
    args: dict[str, Any],
    *,
    accumulator: SystemMapAccumulator,
) -> None:
    """Mutate ``accumulator`` with one ``chat_received`` entry's contribution.

    Reads ``args["text"]``, ``args["sender_person"]``, ``args["channel_id"]``
    and updates all three Counters plus the ``dirty_nodes`` set so the next
    :func:`flush_one_node` call sees the affected nodes.

    Silently no-ops on missing/empty text — the entry simply contributes no
    edges. Sender and channel are coerced via ``str(...)`` to match the
    legacy code (``str(r.sender_person)``).
    """
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return
    sender_raw = args.get("sender_person")
    sender_id = str(sender_raw) if sender_raw is not None else ""
    channel_raw = args.get("channel_id")
    channel_id = str(channel_raw) if channel_raw is not None else ""

    accumulator.add_message(
        sender_id=sender_id,
        channel_id=channel_id,
        text=text,
    )
    if sender_id:
        accumulator.mark_dirty(sender_id)
    if channel_id:
        accumulator.mark_dirty(channel_id)
    for m in _MENTION_PATTERN.finditer(text):
        token = m.group(1)
        if token:
            # Mentioned tokens themselves don't have edges *out* (they're
            # only edge targets); leaving them out of dirty_nodes preserves
            # the legacy behavior where only senders/channels emit nodes.
            pass


def flush_one_node(
    accumulator: SystemMapAccumulator,
) -> SystemMapNodePayload | None:
    """Pop and emit the highest-priority dirty node, or ``None`` if drained.

    Priority = sum of edge weights for that node. Ties broken by node-id
    sort for determinism (the legacy code's emission order was sorted-set
    insertion order; here we make the tie-break explicit so test fixtures
    with equal weights still produce a stable order).

    Behavioural drift vs the polling loop: the legacy ``_flush_system_map``
    drained *all* dirty nodes per call; this function emits **one** per
    call. The Reactivity wired by Block F.4 may either re-fire on a
    schedule until ``flush_one_node`` returns ``None``, or accept the
    one-per-fire cadence as the desired throttle. See spike §4 caveat 5.
    """
    if not accumulator.dirty_nodes:
        return None

    # Compute priority (cumulative edge weight) for every dirty node and
    # pick the max; tie-break by node-id sort.
    candidates: list[tuple[float, str, list[dict[str, Any]]]] = []
    for node_id in accumulator.dirty_nodes:
        edges = accumulator.edges_for(node_id)
        if not edges:
            continue
        weight = sum(float(e["weight"]) for e in edges)
        candidates.append((weight, node_id, edges))

    if not candidates:
        # Every dirty node is empty — clear them and return None to avoid
        # an infinite re-scan of the same empty set.
        accumulator.dirty_nodes.clear()
        return None

    # Sort: weight desc, then node_id asc. Reverse-sort weight by negating.
    candidates.sort(key=lambda c: (-c[0], c[1]))
    _weight, node_id, edges = candidates[0]
    node_kind = accumulator.node_kind_for(node_id)
    accumulator.clear_dirty(node_id)

    return SystemMapNodePayload(
        node_kind=node_kind,
        node_id=node_id,
        edges=edges,
    )


__all__ = [
    "SystemMapAccumulator",
    "_reset_tenant_accumulator",
    "flush_one_node",
    "get_tenant_accumulator",
    "update_from_chat_entry",
]
