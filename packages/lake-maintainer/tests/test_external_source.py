"""ExternalSource (the wrapper that backs both family='external' and family='filedrop')."""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_lake_maintainer.external_source import AcquirableSourceImpl
from wormbase_lake_maintainer.protocols import AcquirableSource


class _FakeConnector:
    kind = "csv_local"
    capability = {"discover", "profile", "sample"}
    classification_hints: list = []
    status = "production"
    status_note = ""

    def __init__(self) -> None:
        self.discover_calls = 0
        self.profile_calls: list[str] = []
        self.sample_calls: list[tuple[str, int]] = []

    async def authenticate(self, secrets):
        return {"handle": "fake"}

    async def discover(self, handle):
        self.discover_calls += 1
        from wormbase_connectors.types import ResourceProposal
        # > CORRECTED 2026-05-03: ResourceProposal has no `uri` field.
        # > resource_id doubles as the URI per the day-one-connector
        # > convention (csv_local.py:154, postgres.py:122, +6 others).
        return [ResourceProposal(
            resource_id="file:///tmp/sales.csv",
            name="sales.csv",
            kind="file",
            metadata={"path": "file:///tmp/sales.csv", "mimetype": "text/csv"},
        )]

    async def profile(self, handle, resource_id):
        self.profile_calls.append(resource_id)
        from wormbase_connectors.types import Profile
        # > CORRECTED 2026-05-03: Profile uses column_count (not col_count),
        # > columns: list[dict] (not list[str]), schema_hash: str (not bytes),
        # > and has no byte_count/mime fields.
        return Profile(
            row_count=5,
            column_count=3,
            columns=[{"name": "id"}, {"name": "revenue"}, {"name": "ts"}],
            schema_hash="0x" + "01" * 64,
        )

    async def sample(self, handle, resource_id, n):
        self.sample_calls.append((resource_id, n))
        return b"id,revenue,ts\n1,100,2026-04-01\n"

    def watch(self, handle, resource_id):
        async def _empty():
            if False:
                yield None
        return _empty()


@pytest.mark.asyncio
async def test_external_source_implements_protocol() -> None:
    src = AcquirableSourceImpl(
        id=uuid4(),
        family="external",
        classification="internal",
        domain=None,
        owner=None,
        connector=_FakeConnector(),
        auth_handle={"handle": "fake"},
    )
    assert isinstance(src, AcquirableSource)


@pytest.mark.asyncio
async def test_external_source_delegates_discover() -> None:
    fake = _FakeConnector()
    src = AcquirableSourceImpl(
        id=uuid4(), family="external", classification="internal",
        domain=None, owner=None, connector=fake, auth_handle={"h": 1},
    )
    proposals = await src.discover()
    assert len(proposals) == 1
    # > CORRECTED 2026-05-03: assert resource_id (the URI), not .uri.
    assert proposals[0].resource_id == "file:///tmp/sales.csv"
    assert fake.discover_calls == 1


@pytest.mark.asyncio
async def test_external_source_delegates_profile_and_sample() -> None:
    fake = _FakeConnector()
    src = AcquirableSourceImpl(
        id=uuid4(), family="external", classification="internal",
        domain=None, owner=None, connector=fake, auth_handle={"h": 1},
    )
    profile = await src.profile("sales")
    assert profile.row_count == 5
    assert fake.profile_calls == ["sales"]
    sample = await src.sample("sales", n=100)
    assert sample.startswith(b"id,revenue,ts")
    assert fake.sample_calls == [("sales", 100)]


@pytest.mark.asyncio
async def test_filedrop_family_uses_same_impl() -> None:
    """C3: external + filedrop share AcquirableSourceImpl; family is metadata."""
    src = AcquirableSourceImpl(
        id=uuid4(), family="filedrop", classification="internal",
        domain=None, owner=None,
        connector=_FakeConnector(), auth_handle={"h": 1},
    )
    assert src.family == "filedrop"
    assert isinstance(src, AcquirableSource)
