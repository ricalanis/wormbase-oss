"""Smoke test the public invariants against a hand-rolled stub Connector.

This test runs without any optional dependency (no pyarrow, no monorepo).
It builds a minimum-viable Connector class in-line and asserts every
public ``assert_*`` function passes. A negative-path test asserts a
broken connector raises ``AssertionError`` from the right invariant.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from wormbase_tools_test import (
    INVARIANT_NAMES,
    assert_authenticate_invalid_raises,
    assert_authenticate_valid_returns_authhandle,
    assert_discover_stable_ordering,
    assert_profile_idempotent,
    assert_sample_deterministic,
    assert_watch_cancellable,
    is_authhandle_shaped,
    is_profile_shaped,
    is_resource_proposal_shaped,
    run_full_conformance,
)


@dataclass(frozen=True)
class _SecretBundle:
    payload: dict[str, Any]


@dataclass(frozen=True)
class _AuthHandle:
    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ResourceProposal:
    resource_id: str
    name: str
    kind: str
    classification_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Profile:
    row_count: int | None
    column_count: int | None
    columns: list[dict[str, Any]]
    schema_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


class GoodConnector:
    """A minimum-viable Connector that passes all six invariants."""

    kind = "good"
    capability: set[str] = {"discover", "profile", "sample"}
    classification_hints: list[str] = []
    status = "production"
    status_note = "Always green."

    async def authenticate(self, secrets: _SecretBundle) -> _AuthHandle:
        if "key" not in secrets.payload:
            raise ValueError("good requires {key: str}")
        return _AuthHandle(
            connector_kind=self.kind,
            handle_id="h-1",
            extra={"key": secrets.payload["key"]},
        )

    async def discover(self, handle: _AuthHandle) -> list[_ResourceProposal]:
        return [
            _ResourceProposal(
                resource_id="rid-1",
                name="rid-1",
                kind="endpoint",
                classification_hint=None,
                metadata={},
            )
        ]

    async def profile(self, handle: _AuthHandle, resource_id: str) -> _Profile:
        cols = [{"name": "id", "dtype": "int"}]
        h = hashlib.sha256(b"id:int").hexdigest()[:16]
        return _Profile(
            row_count=42,
            column_count=1,
            columns=cols,
            schema_hash=h,
            extra={},
        )

    async def sample(
        self, handle: _AuthHandle, resource_id: str, n: int
    ) -> bytes:
        return b"id\n1\n2\n3\n"[:n]

    async def watch(
        self, handle: _AuthHandle, resource_id: str
    ) -> AsyncIterator[Any]:
        if False:
            yield


def test_shape_predicates() -> None:
    h = _AuthHandle(connector_kind="x", handle_id="y")
    assert is_authhandle_shaped(h)
    assert not is_authhandle_shaped(object())

    r = _ResourceProposal(resource_id="r", name="n", kind="k")
    assert is_resource_proposal_shaped(r)
    assert not is_resource_proposal_shaped(h)

    p = _Profile(row_count=1, column_count=1, columns=[{"name": "x"}], schema_hash="h")
    assert is_profile_shaped(p)
    assert not is_profile_shaped(r)


def test_invariant_names_are_six() -> None:
    assert len(INVARIANT_NAMES) == 6


@pytest.mark.asyncio
async def test_good_connector_passes_all_six() -> None:
    c = GoodConnector()
    valid = _SecretBundle({"key": "abc"})
    invalid = _SecretBundle({})

    handle = await assert_authenticate_valid_returns_authhandle(c, valid)
    assert handle.connector_kind == "good"

    await assert_authenticate_invalid_raises(c, invalid)

    proposals = await assert_discover_stable_ordering(c, handle)
    assert proposals[0].resource_id == "rid-1"

    await assert_profile_idempotent(c, handle, "rid-1")
    await assert_sample_deterministic(c, handle, "rid-1", n=8)
    await assert_watch_cancellable(c, handle, "rid-1")


@pytest.mark.asyncio
async def test_run_full_conformance_returns_six_passes() -> None:
    c = GoodConnector()
    results = await run_full_conformance(
        c,
        valid_secrets=_SecretBundle({"key": "abc"}),
        invalid_secrets=_SecretBundle({}),
    )
    assert set(results) == set(INVARIANT_NAMES)
    assert all(v == "pass" for v in results.values())


# ---------------------------------------------------------------------------
# Negative paths — broken connectors must fail the right invariant
# ---------------------------------------------------------------------------


class BrokenAuthAcceptsAll(GoodConnector):
    """Doesn't reject malformed bundles."""

    kind = "broken_auth"

    async def authenticate(self, secrets: _SecretBundle) -> _AuthHandle:
        return _AuthHandle(connector_kind=self.kind, handle_id="x")


@pytest.mark.asyncio
async def test_broken_auth_fails_invariant_2() -> None:
    c = BrokenAuthAcceptsAll()
    with pytest.raises(AssertionError, match="did not raise"):
        await assert_authenticate_invalid_raises(c, _SecretBundle({}))


class BrokenDiscoverNonStable(GoodConnector):
    """Returns a different order each call."""

    kind = "broken_discover"

    def __init__(self) -> None:
        self._n = 0

    async def discover(self, handle: _AuthHandle) -> list[_ResourceProposal]:
        self._n += 1
        items = [
            _ResourceProposal(resource_id="a", name="a", kind="x"),
            _ResourceProposal(resource_id="b", name="b", kind="x"),
        ]
        return items if self._n % 2 == 1 else list(reversed(items))


@pytest.mark.asyncio
async def test_broken_discover_fails_invariant_3() -> None:
    c = BrokenDiscoverNonStable()
    handle = await c.authenticate(_SecretBundle({"key": "abc"}))
    with pytest.raises(AssertionError, match="ordering not stable"):
        await assert_discover_stable_ordering(c, handle)


class BrokenSampleNonDeterministic(GoodConnector):
    """Returns different bytes on each call."""

    kind = "broken_sample"

    def __init__(self) -> None:
        self._n = 0

    async def sample(
        self, handle: _AuthHandle, resource_id: str, n: int
    ) -> bytes:
        self._n += 1
        return f"call-{self._n}".encode()


@pytest.mark.asyncio
async def test_broken_sample_fails_invariant_5() -> None:
    c = BrokenSampleNonDeterministic()
    handle = await c.authenticate(_SecretBundle({"key": "abc"}))
    with pytest.raises(AssertionError, match="drifted between calls"):
        await assert_sample_deterministic(c, handle, "rid-1", n=8)
