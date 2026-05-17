"""L2 Sub-wave B — protocol/dataclass/Reader-Protocol shape tests.

Pins:

  * :func:`make_drift_id` re-export from :mod:`wormbase_ledger`.
  * :class:`ProposedCatalogDrift` is frozen + carries the documented
    11-field surface.
  * :class:`CatalogDriftStrategy` runtime-conformance on the 3
    strategies (TableSet / ColumnSet / ColumnType).
  * The 1 new lightweight Reader Protocol
    (:class:`CatalogSnapshotReader`) is runtime_checkable and
    advertises the canonical method.
  * Snapshot dataclasses (:class:`CatalogSnapshot`,
    :class:`CatalogTable`, :class:`CatalogColumn`) are frozen +
    carry the documented field surface.
  * Doctrine pin: L2 introduces 1 NEW lightweight Reader Protocol,
    but NO new cross-axis chain in the L4→L3 / L6→L5 / L8→L5 sense.
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_agent_gateway.catalog_drift import (
    CatalogColumn,
    CatalogDriftStrategy,
    CatalogSnapshot,
    CatalogSnapshotReader,
    CatalogTable,
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    ProposedCatalogDrift,
    TableSetDriftStrategy,
    make_drift_id,
)


# ---------------------------------------------------------------------------
# make_drift_id — re-export integrity + determinism
# ---------------------------------------------------------------------------


def test_make_drift_id_is_re_exported_from_ledger() -> None:
    """The L2 subpackage re-exports the canonical hash from wormbase_ledger.

    Pin: the L2 strategies + composite + ledger payload validator all
    consume the same function — re-export keeps the contract obvious.
    """
    from wormbase_ledger import make_drift_id as ledger_helper
    assert make_drift_id is ledger_helper


def test_make_drift_id_is_deterministic() -> None:
    """Same args → same id across calls (replay-stable)."""
    a = make_drift_id(
        source_id="src-1",
        table_id="src-1.public.users",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"table_id": "src-1.public.users"},
    )
    b = make_drift_id(
        source_id="src-1",
        table_id="src-1.public.users",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"table_id": "src-1.public.users"},
    )
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_drift_id_distinguishes_drift_kind() -> None:
    """drift_kind IS in the hash — added vs removed yield distinct ids."""
    added = make_drift_id(
        source_id="src-1", table_id="t", column=None,
        drift_kind="table_added", before=None,
        after={"table_id": "t"},
    )
    removed = make_drift_id(
        source_id="src-1", table_id="t", column=None,
        drift_kind="table_removed", before={"table_id": "t"},
        after=None,
    )
    assert added != removed


def test_make_drift_id_distinguishes_before_after_payloads() -> None:
    """Different before/after payloads → different ids (column_type_changed)."""
    a = make_drift_id(
        source_id="src-1", table_id="t", column="c",
        drift_kind="column_type_changed",
        before={"type": "varchar(100)"}, after={"type": "varchar(255)"},
    )
    b = make_drift_id(
        source_id="src-1", table_id="t", column="c",
        drift_kind="column_type_changed",
        before={"type": "varchar(100)"}, after={"type": "text"},
    )
    assert a != b


# ---------------------------------------------------------------------------
# ProposedCatalogDrift — frozen dataclass + field surface
# ---------------------------------------------------------------------------


def _proposal(**overrides):
    base = dict(
        drift_id="d1",
        source_id="src-1",
        table_id="src-1.public.users",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"table_id": "src-1.public.users"},
        strategy="table_set",
        confidence=0.9,
        reasoning="test",
        evidence={},
    )
    base.update(overrides)
    return ProposedCatalogDrift(**base)


def test_proposed_catalog_drift_is_frozen() -> None:
    """:class:`ProposedCatalogDrift` is a frozen dataclass."""
    p = _proposal()
    try:
        p.drift_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedCatalogDrift should be frozen")


def test_proposed_catalog_drift_field_surface() -> None:
    """:class:`ProposedCatalogDrift` carries exactly the 11 documented fields."""
    p = _proposal()
    expected = {
        "drift_id",
        "source_id",
        "table_id",
        "column",
        "drift_kind",
        "before",
        "after",
        "strategy",
        "confidence",
        "reasoning",
        "evidence",
    }
    actual = set(p.__dataclass_fields__)
    assert actual == expected, (
        f"ProposedCatalogDrift field surface drift: "
        f"extra={actual - expected}, missing={expected - actual}"
    )


def test_proposed_catalog_drift_before_after_are_dict_or_none() -> None:
    """``before``/``after`` typed as ``dict | None`` (Sub-wave A handoff #3)."""
    # dict ✓
    p1 = _proposal(before={"type": "x"}, after={"type": "y"},
                    drift_kind="column_type_changed", column="c")
    assert isinstance(p1.before, dict)
    assert isinstance(p1.after, dict)
    # None ✓
    p2 = _proposal(before=None, after={"table_id": "t"})
    assert p2.before is None
    assert isinstance(p2.after, dict)


# ---------------------------------------------------------------------------
# CatalogDriftStrategy Protocol — runtime conformance
# ---------------------------------------------------------------------------


def test_strategies_satisfy_catalog_drift_strategy_protocol() -> None:
    """All 3 strategies are instances of :class:`CatalogDriftStrategy`."""
    ts = TableSetDriftStrategy()
    cs = ColumnSetDriftStrategy()
    ct = ColumnTypeDriftStrategy()
    for service in (ts, cs, ct):
        assert isinstance(service, CatalogDriftStrategy), (
            f"{type(service).__name__} does not satisfy CatalogDriftStrategy"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert TableSetDriftStrategy.name == "table_set"
    assert ColumnSetDriftStrategy.name == "column_set"
    assert ColumnTypeDriftStrategy.name == "column_type"


@pytest.mark.asyncio
async def test_catalog_drift_strategy_propose_signature_is_snapshot_pair_scoped() -> None:
    """``propose(*, company_id, current, baseline)`` is the canonical signature.

    Pin: L2 strategies are snapshot-pair-scoped (NOT company-scoped like
    L1; NOT pair- / table- / snapshot-scoped like L3-L8). The gather_fn
    reconstructs the snapshot pair and passes it to propose.
    """
    ts = TableSetDriftStrategy()
    sig = inspect.signature(ts.propose)
    assert set(sig.parameters) == {"company_id", "current", "baseline"}


# ---------------------------------------------------------------------------
# CatalogSnapshotReader Protocol
# ---------------------------------------------------------------------------


class _FakeCatalogSnapshotReader:
    async def read_current_and_baseline(self, *, company_id, source_id):
        return (
            CatalogSnapshot(source_id=source_id, as_of=datetime.now(UTC)),
            None,
        )


def test_catalog_snapshot_reader_is_runtime_checkable() -> None:
    """:class:`CatalogSnapshotReader` is a ``@runtime_checkable`` Protocol."""
    fake = _FakeCatalogSnapshotReader()
    assert isinstance(fake, CatalogSnapshotReader)


def test_catalog_snapshot_reader_advertises_method() -> None:
    """Pin: ``read_current_and_baseline(*, company_id, source_id)``."""
    sig = inspect.signature(CatalogSnapshotReader.read_current_and_baseline)
    assert set(sig.parameters) == {"self", "company_id", "source_id"}


# ---------------------------------------------------------------------------
# CatalogSnapshot / CatalogTable / CatalogColumn — frozen, field surface
# ---------------------------------------------------------------------------


def test_catalog_snapshot_is_frozen() -> None:
    """:class:`CatalogSnapshot` is a frozen dataclass."""
    s = CatalogSnapshot(source_id="src", as_of=datetime.now(UTC))
    try:
        s.source_id = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("CatalogSnapshot should be frozen")


def test_catalog_snapshot_field_surface() -> None:
    """Pin: 3 fields — source_id / as_of / tables (default = empty tuple)."""
    s = CatalogSnapshot(source_id="src", as_of=datetime.now(UTC))
    expected = {"source_id", "as_of", "tables"}
    actual = set(s.__dataclass_fields__)
    assert actual == expected
    # Default tables is empty tuple
    assert s.tables == ()


def test_catalog_table_is_frozen_and_field_surface() -> None:
    """:class:`CatalogTable` is frozen; 2 fields — table_id / columns (default ())."""
    t = CatalogTable(table_id="src.public.users")
    try:
        t.table_id = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("CatalogTable should be frozen")
    expected = {"table_id", "columns"}
    actual = set(t.__dataclass_fields__)
    assert actual == expected
    # Default columns is empty tuple — matches today's
    # external_catalog_imported payload limitation.
    assert t.columns == ()


def test_catalog_column_is_frozen_and_field_surface() -> None:
    """:class:`CatalogColumn` is frozen; 2 fields — name / type (default None)."""
    c = CatalogColumn(name="customer_id")
    try:
        c.name = "x"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("CatalogColumn should be frozen")
    expected = {"name", "type"}
    actual = set(c.__dataclass_fields__)
    assert actual == expected
    # Default type is None (today's catalog metadata lacks types)
    assert c.type is None


# ---------------------------------------------------------------------------
# Doctrine pin — NO new cross-axis chain (1 platform-Reader Protocol only)
# ---------------------------------------------------------------------------


def test_l2_introduces_one_lightweight_reader_protocol() -> None:
    """L2 ships 1 NEW lightweight Reader Protocol — NOT a cross-axis chain.

    Per spec §4.6: L4→L3, L6→L5, L8→L5 chains read peer lake-axis
    projections. L2's :class:`CatalogSnapshotReader` consumes the
    catalog-mirror substrate (``external_catalog_imported`` entries)
    whose producer is catalog-mirror Reactivities, not a Compounding
    loop. Cross-axis chain count stays at 3.
    """
    from wormbase_agent_gateway.catalog_drift import protocol as proto
    assert hasattr(proto, "CatalogSnapshotReader")
    # And the 3 Record dataclasses
    assert hasattr(proto, "CatalogSnapshot")
    assert hasattr(proto, "CatalogTable")
    assert hasattr(proto, "CatalogColumn")


@pytest.mark.asyncio
async def test_propose_returns_list_of_proposed_catalog_drift() -> None:
    """A strategy's ``propose`` returns a list of ProposedCatalogDrift."""
    ts = TableSetDriftStrategy()
    out = await ts.propose(
        company_id=UUID(int=1),
        current=CatalogSnapshot(source_id="src", as_of=datetime.now(UTC)),
        baseline=None,
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedCatalogDrift) for p in out)
