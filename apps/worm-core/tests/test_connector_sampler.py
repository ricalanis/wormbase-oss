"""Sampler activation Wave — ``ConnectorSampler`` bridge tests.

Pins the SamplerProtocol-shape that ``ConnectorSampler`` exposes to
L3 / L5 / L8 strategies, and the graceful-fallback contract when the
underlying handle / connector / column lookup misses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from wormbase_core.connector_sampler import (
    DEFAULT_MAX_SAMPLE_N,
    ConnectorSampler,
    _parse_csv_column,
)
from wormbase_core.source_handle_provider import SourceHandleRecord

_COMPANY = UUID("00000000-0000-0000-0000-0000000c0001")


# ---------------------------------------------------------------------------
# Fakes — opaque AuthHandle + FakeConnector + FakeHandleProvider + FakeRegistry
# ---------------------------------------------------------------------------


@dataclass
class _FakeAuthHandle:
    payload: dict[str, Any]


@dataclass
class _FakeConnector:
    """In-memory connector that returns bytes from a per-resource_id map."""

    _bytes_per_resource: dict[str, bytes] = field(default_factory=dict)
    raise_on_sample: bool = False

    kind: str = "fake"

    async def sample(
        self, handle: Any, resource_id: str, n: int,
    ) -> bytes:
        del handle, n
        if self.raise_on_sample:
            raise RuntimeError("simulated connector failure")
        return self._bytes_per_resource.get(resource_id, b"")


class _FakeRegistry:
    """Test SurfaceDriverRegistry — fixture-friendly."""

    def __init__(
        self, *, kinds: dict[str, type[Any]] | None = None,
    ) -> None:
        self._kinds = dict(kinds or {})

    def get(self, kind: str) -> type[Any] | None:
        return self._kinds.get(kind)


class _FakeProvider:
    """Test SourceHandleProvider — returns a fixed record (or None)."""

    def __init__(
        self,
        *,
        record: SourceHandleRecord | None = None,
        raise_on_get: bool = False,
    ) -> None:
        self._record = record
        self._raise = raise_on_get

    async def get_handle(
        self, *, company_id: UUID, source_id: str,
    ) -> SourceHandleRecord | None:
        del company_id, source_id
        if self._raise:
            raise RuntimeError("simulated provider failure")
        return self._record


def _make_connector_class(
    *, csv_per_resource: dict[str, bytes], raise_on_sample: bool = False,
) -> type[Any]:
    """Return a connector class whose instance returns the fixed bytes."""

    class _C(_FakeConnector):
        def __init__(self) -> None:
            super().__init__(
                _bytes_per_resource=csv_per_resource,
                raise_on_sample=raise_on_sample,
            )

    return _C


# ---------------------------------------------------------------------------
# _parse_csv_column — pure helper
# ---------------------------------------------------------------------------


def test_parse_csv_column_returns_distinct_values() -> None:
    raw = b"email,name\na@x.com,Alice\nb@x.com,Bob\na@x.com,AliceDup\n"
    out = _parse_csv_column(raw, "email", n=10)
    assert out == {"a@x.com", "b@x.com"}


def test_parse_csv_column_caps_at_n() -> None:
    raw = b"x\n1\n2\n3\n4\n"
    out = _parse_csv_column(raw, "x", n=2)
    assert out == {"1", "2"}


def test_parse_csv_column_empty_bytes_returns_empty() -> None:
    assert _parse_csv_column(b"", "any", n=10) == set()


def test_parse_csv_column_missing_column_returns_empty() -> None:
    raw = b"only_col\nvalue\n"
    assert _parse_csv_column(raw, "absent_col", n=10) == set()


def test_parse_csv_column_tsv_dialect() -> None:
    raw = b"email\tname\na@x.com\tAlice\nb@x.com\tBob\n"
    out = _parse_csv_column(raw, "email", n=10)
    assert out == {"a@x.com", "b@x.com"}


def test_parse_csv_column_strips_whitespace_and_drops_empties() -> None:
    raw = b"k\n  v1  \n\nv2\n"
    out = _parse_csv_column(raw, "k", n=10)
    assert out == {"v1", "v2"}


# ---------------------------------------------------------------------------
# sample_column — happy + graceful-fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_column_returns_set_on_happy_path() -> None:
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={"tbl-1": "tbl-1"},
    )
    csv = b"email\na@x.com\nb@x.com\nc@x.com\n"
    registry = _FakeRegistry(
        kinds={"fake": _make_connector_class(
            csv_per_resource={"tbl-1": csv},
        )},
    )
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=registry,
    )
    out = await sampler.sample_column("tbl-1", "email", 10)
    assert out == {"a@x.com", "b@x.com", "c@x.com"}


@pytest.mark.asyncio
async def test_sample_column_returns_empty_when_handle_none() -> None:
    """No handle → empty (per-source honest stub fallback)."""
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=None),
        company_id=_COMPANY,
        connector_registry=_FakeRegistry(),
    )
    assert await sampler.sample_column("tbl-x", "email", 10) == set()


@pytest.mark.asyncio
async def test_sample_column_returns_empty_when_provider_raises() -> None:
    """Provider exception is logged + swallowed; sampler returns empty."""
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(raise_on_get=True),
        company_id=_COMPANY,
        connector_registry=_FakeRegistry(),
    )
    assert await sampler.sample_column("tbl-x", "email", 10) == set()


@pytest.mark.asyncio
async def test_sample_column_returns_empty_when_connector_kind_unknown() -> None:
    """Registry misses on the kind → empty (honest stub fallback)."""
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="unknown_kind",
        auth_handle=_FakeAuthHandle(payload={}),
    )
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=_FakeRegistry(),  # empty registry
    )
    assert await sampler.sample_column("tbl-x", "email", 10) == set()


@pytest.mark.asyncio
async def test_sample_column_returns_empty_when_connector_raises() -> None:
    """SurfaceDriver exception is logged + swallowed; sampler returns empty."""
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={"tbl-1": "tbl-1"},
    )
    registry = _FakeRegistry(
        kinds={"fake": _make_connector_class(
            csv_per_resource={}, raise_on_sample=True,
        )},
    )
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=registry,
    )
    assert await sampler.sample_column("tbl-1", "email", 10) == set()


@pytest.mark.asyncio
async def test_sample_column_returns_empty_when_column_not_in_header() -> None:
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={"tbl-1": "tbl-1"},
    )
    csv = b"name\nAlice\nBob\n"
    registry = _FakeRegistry(
        kinds={"fake": _make_connector_class(
            csv_per_resource={"tbl-1": csv},
        )},
    )
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=registry,
    )
    assert await sampler.sample_column("tbl-1", "email", 10) == set()


@pytest.mark.asyncio
async def test_sample_column_uses_identity_when_resource_map_misses() -> None:
    """Missing table_id in resource_map → identity fallback to table_id."""
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={},  # empty → falls back to table_id == resource_id
    )
    csv = b"x\n1\n2\n"
    registry = _FakeRegistry(
        kinds={"fake": _make_connector_class(
            csv_per_resource={"tbl-1": csv},
        )},
    )
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=registry,
    )
    assert await sampler.sample_column("tbl-1", "x", 10) == {"1", "2"}


@pytest.mark.asyncio
async def test_sample_column_zero_n_returns_empty() -> None:
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=None),
        company_id=_COMPANY,
        connector_registry=_FakeRegistry(),
    )
    assert await sampler.sample_column("tbl-1", "x", 0) == set()


@pytest.mark.asyncio
async def test_sample_column_n_caps_at_max_sample_n() -> None:
    """Pathological n above max_sample_n is capped at construction-time cap."""
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={"tbl-1": "tbl-1"},
    )
    # Generate 50 distinct rows.
    csv_lines = ["x"] + [str(i) for i in range(50)]
    csv = "\n".join(csv_lines).encode()
    captured: dict[str, int] = {}

    class _RecordingConnector(_FakeConnector):
        def __init__(self) -> None:
            super().__init__(_bytes_per_resource={"tbl-1": csv})

        async def sample(
            self, handle: Any, resource_id: str, n: int,
        ) -> bytes:
            captured["n"] = n
            return await super().sample(handle, resource_id, n)

    registry = _FakeRegistry(kinds={"fake": _RecordingConnector})
    # max_sample_n=10 — pathological caller asks for 1_000_000_000
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=record),
        company_id=_COMPANY,
        connector_registry=registry,
        max_sample_n=10,
    )
    out = await sampler.sample_column("tbl-1", "x", 1_000_000_000)
    assert captured["n"] == 10
    # Returned set is at most 10 items.
    assert len(out) <= 10


@pytest.mark.asyncio
async def test_sample_column_caches_handle_lookup_per_source_id() -> None:
    """Repeated calls for the same table_id resolve the handle once."""
    record = SourceHandleRecord(
        source_id="src-1",
        connector_kind="fake",
        auth_handle=_FakeAuthHandle(payload={}),
        resource_map={"tbl-1": "tbl-1"},
    )
    calls: list[str] = []

    class _CountingProvider:
        async def get_handle(
            self, *, company_id: UUID, source_id: str,
        ) -> SourceHandleRecord | None:
            del company_id
            calls.append(source_id)
            return record

    csv = b"x\n1\n"
    registry = _FakeRegistry(
        kinds={"fake": _make_connector_class(
            csv_per_resource={"tbl-1": csv},
        )},
    )
    sampler = ConnectorSampler(
        handle_provider=_CountingProvider(),
        company_id=_COMPANY,
        connector_registry=registry,
    )
    _ = await sampler.sample_column("tbl-1", "x", 1)
    _ = await sampler.sample_column("tbl-1", "x", 1)
    _ = await sampler.sample_column("tbl-1", "x", 1)
    assert calls.count("tbl-1") == 1


# ---------------------------------------------------------------------------
# estimate_table_size — always 0 today (SurfaceDriver Protocol lacks a size method)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_estimate_table_size_returns_zero() -> None:
    sampler = ConnectorSampler(
        handle_provider=_FakeProvider(record=None),
        company_id=_COMPANY,
        connector_registry=_FakeRegistry(),
    )
    assert await sampler.estimate_table_size("anything") == 0


# ---------------------------------------------------------------------------
# DEFAULT_MAX_SAMPLE_N constant — sanity check that the cap is sensible.
# ---------------------------------------------------------------------------


def test_default_max_sample_n_is_above_strategy_defaults() -> None:
    """Default cap MUST be above the strategies' default sample sizes.

    L3 SampleOverlapStrategy default = 1000 (per sample_size kwarg).
    L5 ValuePattern default = 20.
    L8 SampleOverlapEntityStrategy default = 200.
    The cap must accommodate the maximum (1000) without truncating.
    """
    assert DEFAULT_MAX_SAMPLE_N >= 1000
