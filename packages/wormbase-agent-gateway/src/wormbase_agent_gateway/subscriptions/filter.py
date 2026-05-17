"""Deterministic pattern-match engine for agent event subscriptions.

The dispatcher compiles each subscription's :class:`AgentEventFilter`
into a pure predicate (``Callable[[dict], bool]``) at registration
time. The compiled predicate has no globals, no I/O, no side-effects —
the same inputs always produce the same output. That's how wire-replay
reproduces the dispatch decisions byte-identically.

Design choice (D3 in the v2.A plan): four axes — ``kinds``, ``domains``,
``agent_id_ref``, ``payload_path_eq`` — chosen because the four
enumerated v2.A event types (bad-pattern alerts, data-product
recommendations, semantic-gap escalations, source events) all fit, and
because four axes is the upper bound at which the filter stays
human-readable on the ledger entry. JSONPath / CEL / SQL are
deliberately rejected: they introduce expression evaluation, which
breaks the "the filter is human-readable from the ledger" property.

Future axes can be added as additive fields (Rule 2 of the
schema-evolution doctrine applies to dataclass shape as well as
ledger-entry shape).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentEventFilter:
    """Deterministic pattern-match over ledger entries.

    Empty/None fields don't constrain. All present fields are
    intersected (logical AND). Compiled at registration time into a
    pure predicate via :func:`compile_filter`.

    Attributes:
        kinds: Any of these entry kinds match. Empty = all kinds.
        domains: ``entry.args.domain`` must match one of these. Empty
            = don't constrain on domain.
        agent_id_ref: ``entry.args.agent_id`` must equal this. None =
            don't constrain on agent.
        payload_path_eq: Tuple of ``(dotted_path, expected_value)``
            pairs; each path is looked up via dict traversal from the
            entry root. All paths must equal their expected value.
    """

    kinds: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    agent_id_ref: str | None = None
    payload_path_eq: tuple[tuple[str, str], ...] = ()


def _lookup_path(entry: dict, dotted: str) -> Any:
    """Walk a dotted path through nested dicts; return None if absent.

    Returning None on missing keys (rather than raising) keeps the
    filter resilient against schema drift: a stale subscription with a
    path that no longer exists simply doesn't match, rather than
    crashing the dispatcher.
    """
    cur: Any = entry
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def compile_filter(f: AgentEventFilter) -> Callable[[dict], bool]:
    """Compile a filter into a pure predicate over ledger entries.

    Capturing the filter's fields into local closures lets the hot
    path avoid attribute lookups on every entry. The returned function
    is referentially transparent — same inputs always return the same
    output, no globals mutated, no I/O performed.
    """
    kinds_set = set(f.kinds) if f.kinds else None
    domains_set = set(f.domains) if f.domains else None
    agent_id_ref = f.agent_id_ref
    payload_checks = tuple(f.payload_path_eq)

    def _match(entry: dict) -> bool:
        if kinds_set is not None and entry.get("kind") not in kinds_set:
            return False
        if domains_set is not None:
            args = entry.get("args") or {}
            if args.get("domain") not in domains_set:
                return False
        if agent_id_ref is not None:
            args = entry.get("args") or {}
            if args.get("agent_id") != agent_id_ref:
                return False
        for path, expected in payload_checks:
            if _lookup_path(entry, path) != expected:
                return False
        return True

    return _match


def serialize_filter(f: AgentEventFilter) -> dict:
    """Convert filter to the ledger-storable dict form.

    Used when writing the ``agent_subscription_created`` entry: the
    ledger stores filters as plain dicts so wire-replay stays
    boundary-free (no agent-gateway types crossing the substrate).
    """
    return {
        "kinds": list(f.kinds),
        "domains": list(f.domains),
        "agent_id_ref": f.agent_id_ref,
        "payload_path_eq": [list(t) for t in f.payload_path_eq],
    }


def deserialize_filter(d: dict) -> AgentEventFilter:
    """Restore a filter from its ledger-storable dict form.

    Tolerates missing keys (defaults to empty) so older subscription
    entries written before a future axis was added remain readable.
    """
    return AgentEventFilter(
        kinds=tuple(d.get("kinds", ())),
        domains=tuple(d.get("domains", ())),
        agent_id_ref=d.get("agent_id_ref"),
        payload_path_eq=tuple(tuple(t) for t in d.get("payload_path_eq", ())),
    )
