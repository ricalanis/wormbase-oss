"""Wave 2 Task 4 — cache-key allow-list excludes governance + requester.

Two :class:`RouteRequest`s that differ ONLY in ``requested_by`` or
``governance_context`` must hit the same cached response — the model
output is governance-invariant; the audit trail records who saw it
under which envelope, but the response text is shared.

The ``_CACHE_KEY_FIELDS`` allow-list (in :mod:`protocol`) is the
single point of truth; the static-guard test below asserts the
allow-list is a strict subset of actual ``RouteRequest`` fields so
schema drift can't accidentally leak a new field into the cache key.
"""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

from wormbase_inference import GovernanceContext, RouteRequest
from wormbase_inference.protocol import _CACHE_KEY_FIELDS
from wormbase_inference.router import build_cache_key


def test_cache_key_invariant_across_governance_and_requester() -> None:
    """Two RouteRequests differing ONLY in governance / requester must
    produce the same cache key.

    Response text is governance-invariant — same prompt → same model
    output regardless of who asked or under which envelope. The audit
    row records the agent + envelope; the cache lookup is shared.
    """
    a = RouteRequest(
        call_type="reasoning",
        messages=(("user", "hi"),),
        requested_by="agent-1",
        governance_context=GovernanceContext(classification_ceiling="internal"),
    )
    b = RouteRequest(
        call_type="reasoning",
        messages=(("user", "hi"),),
        requested_by="agent-2",
        governance_context=GovernanceContext(
            classification_ceiling="confidential",
            cost_budget_usd=Decimal("1.00"),
        ),
    )
    c = RouteRequest(
        call_type="reasoning",
        messages=(("user", "hi"),),
        # No governance, no requester change — baseline.
    )

    key_a = build_cache_key(a)
    key_b = build_cache_key(b)
    key_c = build_cache_key(c)

    assert key_a == key_b == key_c
    assert len(key_a) == 64  # sha256 hex


def test_cache_key_changes_when_a_keyed_field_changes() -> None:
    """Sanity check the inverse: keyed fields DO affect the cache key.

    Different ``messages`` content must produce different cache keys —
    if the allow-list mistakenly excluded ``messages`` we'd cache every
    request under the same key, a catastrophic regression.
    """
    a = RouteRequest(call_type="reasoning", messages=(("user", "hi"),))
    b = RouteRequest(call_type="reasoning", messages=(("user", "bye"),))
    assert build_cache_key(a) != build_cache_key(b)


def test_cache_key_fields_subset_of_route_request() -> None:
    """Static guard: every entry in ``_CACHE_KEY_FIELDS`` exists on RouteRequest.

    The module-import-time assertion in ``protocol.py`` enforces this at
    import time; this test pins the contract from the test side so a
    future contributor can't silently delete the import-time guard.
    """
    field_names = {f.name for f in fields(RouteRequest)}
    drift = set(_CACHE_KEY_FIELDS) - field_names
    assert drift == set(), (
        f"_CACHE_KEY_FIELDS drifted from RouteRequest: {drift}. "
        "Either restore the missing field on RouteRequest or remove it "
        "from the allow-list."
    )
    # And the explicit exclusions are present on RouteRequest but
    # absent from the allow-list — both are metadata, not model inputs.
    assert "requested_by" in field_names
    assert "governance_context" in field_names
    assert "requested_by" not in _CACHE_KEY_FIELDS
    assert "governance_context" not in _CACHE_KEY_FIELDS
