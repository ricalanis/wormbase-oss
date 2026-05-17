"""Structural conformance tests for the three Protocols."""
from __future__ import annotations

from wormbase_lake_maintainer.protocols import (
    AcquirableSource,
    MaintainableSource,
    LakeStore,
)
from wormbase_lake_maintainer.types import (
    DriftReport,
    ClassificationUpdate,
    StalenessReport,
    LineageReport,
    Profile,
    ResourceProposal,
)


def test_acquirable_source_is_runtime_checkable() -> None:
    class _Stub:
        id = "x"
        family = "external"
        classification = "internal"
        domain = None
        owner = None

        async def discover(self):
            return []

        async def profile(self, resource_id):
            return Profile(
                row_count=0,
                column_count=0,
                columns=[],
                schema_hash="0x" + "00" * 64,
            )

        async def sample(self, resource_id, n):
            return b""

    assert isinstance(_Stub(), AcquirableSource)


def test_maintainable_source_is_runtime_checkable() -> None:
    class _Stub:
        id = "x"
        family = "conversation"
        source_mode = "wormbase_owned"

        async def detect_drift(self):
            return DriftReport(drifted=False, reason="")

        async def refresh_classification(self):
            return ClassificationUpdate(
                updated=False, classification="internal",
            )

        async def staleness_signal(self):
            return StalenessReport(
                stale=False, last_seen=None,
            )

        async def lineage_health(self):
            return LineageReport(
                healthy=True, broken_edges=[],
            )

    assert isinstance(_Stub(), MaintainableSource)


def test_lake_store_is_runtime_checkable() -> None:
    class _Stub:
        async def write_bronze(self, **k):
            return None

        async def write_silver(self, **k):
            return None

        async def write_gold(self, **k):
            return None

        async def read_layer(self, **k):
            if False:
                yield {}

    assert isinstance(_Stub(), LakeStore)


def test_report_types_are_dataclasses() -> None:
    from dataclasses import is_dataclass
    assert is_dataclass(DriftReport)
    assert is_dataclass(ClassificationUpdate)
    assert is_dataclass(StalenessReport)
    assert is_dataclass(LineageReport)


def test_resource_proposal_carries_kind_and_resource_id() -> None:
    # Live shape per packages/connectors/src/wormbase_connectors/types.py:58-72:
    # ResourceProposal(resource_id, name, kind, classification_hint?, metadata?).
    # No `uri` field — file/object identification is connector-internal via
    # resource_id. The plan's stub used `uri=` which doesn't exist.
    rp = ResourceProposal(resource_id="r1", name="x.csv", kind="csv")
    assert rp.kind == "csv"
    assert rp.name == "x.csv"
    assert rp.resource_id == "r1"
