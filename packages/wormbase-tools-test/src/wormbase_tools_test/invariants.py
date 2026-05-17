"""Six conformance invariants for the WormBase Connector Protocol.

These are the public, monorepo-independent equivalents of the
parametrized cases in
``tests/contract/test_connector_protocol_conformance.py``. Each
``assert_*`` function takes a connector instance plus the inputs it
needs and either returns silently (pass) or raises an
``AssertionError`` (fail). The functions are duck-typed: they do not
import ``wormbase_connectors.types``, so any class whose return values
have the right shape conforms.

The functions are designed to be called directly (programmatic use) or
via the pytest plugin in :mod:`wormbase_tools_test.plugin`.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any


# ---------------------------------------------------------------------------
# Structural shape predicates — duck-typed alternatives to ``isinstance``
# ---------------------------------------------------------------------------


def is_authhandle_shaped(obj: Any) -> bool:
    """Return True iff ``obj`` looks like an AuthHandle (Protocol §types)."""
    return (
        hasattr(obj, "connector_kind")
        and hasattr(obj, "handle_id")
        and isinstance(obj.connector_kind, str)
        and isinstance(obj.handle_id, str)
    )


def is_resource_proposal_shaped(obj: Any) -> bool:
    """Return True iff ``obj`` looks like a ResourceProposal."""
    return (
        hasattr(obj, "resource_id")
        and hasattr(obj, "name")
        and hasattr(obj, "kind")
        and isinstance(obj.resource_id, str)
        and isinstance(obj.name, str)
        and isinstance(obj.kind, str)
    )


def is_profile_shaped(obj: Any) -> bool:
    """Return True iff ``obj`` looks like a Profile."""
    return (
        hasattr(obj, "schema_hash")
        and hasattr(obj, "columns")
        and hasattr(obj, "row_count")
        and hasattr(obj, "column_count")
        and isinstance(obj.schema_hash, str)
        and isinstance(obj.columns, list)
    )


# ---------------------------------------------------------------------------
# The six invariants — async; each takes the inputs it needs
# ---------------------------------------------------------------------------


async def assert_authenticate_valid_returns_authhandle(
    connector: Any,
    valid_secrets: Any,
) -> Any:
    """Invariant 1: valid secrets → an AuthHandle naming the connector kind.

    Returns the resulting handle so callers can chain into other invariants.
    """
    handle = await connector.authenticate(valid_secrets)
    assert is_authhandle_shaped(handle), (
        f"authenticate returned {type(handle).__name__}; "
        "expected AuthHandle-shaped (connector_kind: str, handle_id: str)"
    )
    assert handle.connector_kind, "AuthHandle.connector_kind must be non-empty"
    assert handle.handle_id, "AuthHandle.handle_id must be non-empty"
    return handle


async def assert_authenticate_invalid_raises(
    connector: Any,
    invalid_secrets: Any,
) -> None:
    """Invariant 2: malformed secrets → ValueError (or KeyError)."""
    try:
        await connector.authenticate(invalid_secrets)
    except (ValueError, KeyError):
        return
    raise AssertionError(
        "authenticate(invalid_secrets) did not raise ValueError/KeyError; "
        "the Connector Protocol requires malformed bundles to be rejected"
    )


async def assert_discover_stable_ordering(
    connector: Any,
    handle: Any,
) -> list[Any]:
    """Invariant 3: discover() is idempotent — two calls return same order.

    Returns the first call's result so callers can pick a known
    resource_id from it.
    """
    first = await connector.discover(handle)
    second = await connector.discover(handle)
    assert isinstance(first, list), (
        f"discover returned {type(first).__name__}; expected list"
    )
    for r in first:
        assert is_resource_proposal_shaped(r), (
            f"discover yielded {type(r).__name__}; "
            "expected ResourceProposal-shaped (resource_id, name, kind)"
        )
    order_first = [(r.kind, r.resource_id) for r in first]
    order_second = [(r.kind, r.resource_id) for r in second]
    assert order_first == order_second, (
        "discover ordering not stable across calls — "
        f"first={order_first} second={order_second}"
    )
    return first


async def assert_profile_idempotent(
    connector: Any,
    handle: Any,
    known_resource_id: str,
    is_skeletal: bool = False,
) -> None:
    """Invariant 4: profile(handle, rid) is idempotent for the same input.

    For skeletal connectors (``status != 'production'`` declared via
    ``is_skeletal=True``), we instead assert profile raises
    ``NotImplementedError``.
    """
    if is_skeletal:
        try:
            await connector.profile(handle, known_resource_id or "any")
        except NotImplementedError:
            return
        raise AssertionError(
            "skeletal connector must raise NotImplementedError from profile()"
        )
    first = await connector.profile(handle, known_resource_id)
    second = await connector.profile(handle, known_resource_id)
    assert is_profile_shaped(first), (
        f"profile returned {type(first).__name__}; "
        "expected Profile-shaped (schema_hash, columns, row_count, column_count)"
    )
    assert is_profile_shaped(second)
    assert first.schema_hash == second.schema_hash, (
        f"profile schema_hash drifted between calls: "
        f"{first.schema_hash!r} vs {second.schema_hash!r}"
    )
    assert first.columns == second.columns, (
        "profile columns drifted between calls — schema is unstable"
    )
    assert first.column_count == second.column_count


async def assert_sample_deterministic(
    connector: Any,
    handle: Any,
    known_resource_id: str,
    n: int = 32,
    is_skeletal: bool = False,
    byte_cap_strict: bool = False,
) -> None:
    """Invariant 5: sample is bytes, deterministic for same (handle, rid, n).

    Set ``byte_cap_strict=True`` for connectors whose ``n`` semantics
    are byte-cap (s3_csv, http_csv, mcp); otherwise ``n`` is treated as
    a record-count cap and the byte length isn't checked literally.
    """
    if is_skeletal:
        try:
            await connector.sample(handle, known_resource_id or "any", n)
        except NotImplementedError:
            return
        raise AssertionError(
            "skeletal connector must raise NotImplementedError from sample()"
        )
    first = await connector.sample(handle, known_resource_id, n)
    second = await connector.sample(handle, known_resource_id, n)
    assert isinstance(first, bytes), (
        f"sample returned {type(first).__name__}; expected bytes"
    )
    assert isinstance(second, bytes)
    assert first == second, (
        f"sample drifted between calls (lengths {len(first)} vs {len(second)})"
    )
    if byte_cap_strict:
        assert len(first) <= n, (
            f"sample returned {len(first)} bytes > n={n} (byte-cap connector)"
        )


async def assert_watch_cancellable(
    connector: Any,
    handle: Any,
    known_resource_id: str,
    is_skeletal: bool = False,
    max_changes_to_drain: int = 5,
) -> None:
    """Invariant 6: watch returns an async iterator that exhausts cleanly.

    Day-one connectors yield zero changes (CDC is post-day-one). The
    test drains up to ``max_changes_to_drain`` and exits — no leaked
    coroutines, no unraised exceptions.
    """
    if is_skeletal:
        try:
            async for _ in connector.watch(handle, known_resource_id or "any"):
                pass
        except NotImplementedError:
            return
        raise AssertionError(
            "skeletal connector must raise NotImplementedError from watch()"
        )
    iterator = connector.watch(handle, known_resource_id)
    assert isinstance(iterator, AsyncIterator) or inspect.isasyncgen(iterator), (
        f"watch returned {type(iterator).__name__}; expected AsyncIterator"
    )
    count = 0
    async for _change in iterator:
        count += 1
        if count >= max_changes_to_drain:
            break


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


INVARIANT_NAMES: tuple[str, ...] = (
    "authenticate_valid_returns_authhandle",
    "authenticate_invalid_raises",
    "discover_stable_ordering",
    "profile_idempotent",
    "sample_deterministic",
    "watch_cancellable",
)


async def run_full_conformance(
    connector: Any,
    valid_secrets: Any,
    invalid_secrets: Any,
    known_resource_id: str | None = None,
    is_skeletal: bool = False,
    sample_n: int = 32,
    byte_cap_strict: bool = False,
) -> dict[str, str]:
    """Run all six invariants against a connector. Return a result dict.

    ``known_resource_id`` may be left None — we'll infer it from the
    first ResourceProposal returned by ``discover``.
    """
    results: dict[str, str] = {}

    handle = await assert_authenticate_valid_returns_authhandle(
        connector, valid_secrets
    )
    results["authenticate_valid_returns_authhandle"] = "pass"

    await assert_authenticate_invalid_raises(connector, invalid_secrets)
    results["authenticate_invalid_raises"] = "pass"

    proposals = await assert_discover_stable_ordering(connector, handle)
    results["discover_stable_ordering"] = "pass"

    if known_resource_id is None and proposals:
        known_resource_id = proposals[0].resource_id

    if known_resource_id is None and not is_skeletal:
        raise AssertionError(
            "no known_resource_id provided and discover returned []. "
            "Production connectors must surface at least one resource for "
            "profile/sample tests; provide one via the conftest fixture."
        )

    await assert_profile_idempotent(
        connector, handle, known_resource_id or "", is_skeletal=is_skeletal
    )
    results["profile_idempotent"] = "pass"

    await assert_sample_deterministic(
        connector,
        handle,
        known_resource_id or "",
        n=sample_n,
        is_skeletal=is_skeletal,
        byte_cap_strict=byte_cap_strict,
    )
    results["sample_deterministic"] = "pass"

    await assert_watch_cancellable(
        connector, handle, known_resource_id or "", is_skeletal=is_skeletal
    )
    results["watch_cancellable"] = "pass"

    return results
