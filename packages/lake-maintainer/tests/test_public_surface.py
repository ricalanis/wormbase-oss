"""Lock the package's public surface."""
from __future__ import annotations


def test_protocols_are_re_exported() -> None:
    from wormbase_lake_maintainer import (
        AcquirableSource,
        MaintainableSource,
        LakeStore,
    )
    assert AcquirableSource is not None
    assert MaintainableSource is not None
    assert LakeStore is not None


def test_report_types_are_re_exported() -> None:
    from wormbase_lake_maintainer import (
        DriftReport,
        ClassificationUpdate,
        StalenessReport,
        LineageReport,
        SourceId,
    )
    assert DriftReport is not None
    assert ClassificationUpdate is not None
    assert StalenessReport is not None
    assert LineageReport is not None
    assert SourceId is not None
