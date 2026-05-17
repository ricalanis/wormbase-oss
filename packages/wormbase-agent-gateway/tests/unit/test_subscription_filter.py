"""Unit tests for the agent event subscription filter.

The filter is the deterministic engine that decides whether a given
ledger entry matches a given subscription. It is a pure function: no
I/O, no globals, no side-effects. Wire-replay reproduces match
decisions byte-identically because of that purity, so these tests pin
the contract every replay run depends on.

Coverage:

  * ``kinds`` axis: match, no-match, empty-matches-all.
  * ``domains`` axis: present-and-matching, present-but-not-matching.
  * ``agent_id_ref`` axis: explicit equality.
  * ``payload_path_eq`` axis: matching, no-match, missing-path
    (resilient against schema drift).
  * Serialization roundtrip (the ledger stores the dict form).
  * Purity smoke (calling the compiled predicate twice with the same
    input yields the same output).
"""

from __future__ import annotations

from wormbase_agent_gateway.subscriptions.filter import (
    AgentEventFilter,
    compile_filter,
    deserialize_filter,
    serialize_filter,
)

ENTRY_BAD_PATTERN = {
    "kind": "bad_pattern_proposed",
    "args": {
        "agent_id": "agent_xyz",
        "domain": "finance",
        "canonical_intent": "weekly revenue by region",
    },
    "seq": 100,
}


def test_compile_filter_kinds_match() -> None:
    """``kinds`` includes the entry's kind → match."""
    f = AgentEventFilter(kinds=("bad_pattern_proposed",))
    pred = compile_filter(f)
    assert pred(ENTRY_BAD_PATTERN) is True


def test_compile_filter_kinds_no_match() -> None:
    """``kinds`` doesn't include the entry's kind → no match."""
    f = AgentEventFilter(kinds=("other_kind",))
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is False


def test_compile_filter_empty_kinds_matches_all() -> None:
    """Empty ``kinds`` means 'don't constrain on kind' → always match."""
    f = AgentEventFilter()
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is True


def test_compile_filter_domain_match() -> None:
    """``domains`` intersects with the entry's ``args.domain`` → match."""
    f = AgentEventFilter(kinds=("bad_pattern_proposed",), domains=("finance",))
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is True


def test_compile_filter_domain_no_match() -> None:
    """``domains`` doesn't include the entry's domain → no match."""
    f = AgentEventFilter(kinds=("bad_pattern_proposed",), domains=("sales",))
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is False


def test_compile_filter_agent_id_ref_match() -> None:
    """``agent_id_ref`` equals the entry's ``args.agent_id`` → match."""
    f = AgentEventFilter(agent_id_ref="agent_xyz")
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is True


def test_compile_filter_payload_path_eq_match() -> None:
    """``payload_path_eq`` walks dotted paths through nested dicts."""
    f = AgentEventFilter(
        payload_path_eq=(("args.canonical_intent", "weekly revenue by region"),),
    )
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is True


def test_compile_filter_payload_path_eq_no_match() -> None:
    """Path resolves, but value differs → no match."""
    f = AgentEventFilter(
        payload_path_eq=(("args.canonical_intent", "something else"),),
    )
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is False


def test_compile_filter_missing_path_no_match() -> None:
    """Missing path returns None, which never equals the expected str → no match.

    This is the resilience property: a stale subscription whose path
    no longer exists in the entry shape simply doesn't match, rather
    than crashing the dispatcher.
    """
    f = AgentEventFilter(
        payload_path_eq=(("args.nonexistent_key", "x"),),
    )
    assert compile_filter(f)(ENTRY_BAD_PATTERN) is False


def test_filter_serialization_roundtrip() -> None:
    """``serialize_filter`` → ``deserialize_filter`` reproduces the filter.

    The ledger stores filters as dicts (boundary-free); the dispatcher
    deserializes on each fire. Equality is by-value, enforced by
    ``@dataclass(frozen=True, slots=True)``.
    """
    f = AgentEventFilter(
        kinds=("bad_pattern_proposed", "data_product_recommended"),
        domains=("finance",),
        agent_id_ref="agent_xyz",
        payload_path_eq=(("args.canonical_intent", "weekly revenue"),),
    )
    serialized = serialize_filter(f)
    assert isinstance(serialized, dict)
    f2 = deserialize_filter(serialized)
    assert f == f2


def test_compile_is_pure_no_side_effects() -> None:
    """Calling the compiled predicate twice on the same input is referentially
    transparent — this is the wire-replay invariant in miniature.
    """
    f = AgentEventFilter(kinds=("bad_pattern_proposed",))
    pred = compile_filter(f)
    assert pred(ENTRY_BAD_PATTERN) is True
    assert pred(ENTRY_BAD_PATTERN) is True
