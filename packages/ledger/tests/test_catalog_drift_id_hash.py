"""Dedicated tests for ``make_drift_id`` — L2 Sub-wave A.

Mirror of the L1 ``make_candidate_id`` / L8 ``make_stitch_id`` shape.
The composite PK ``(company_id, drift_id)`` on
``projection_catalog_drifts`` leans on this hash for natural dedup,
so the hash function's determinism + collision behavior IS the
projection's idempotency contract.

Split out from ``test_catalog_drift_payloads.py`` (which has its own
hash tests adjacent to payload tests) for the same reason L8 / L1
ship dedicated id-hash modules: the hash is referenced from
Sub-waves B/C/D (inference strategies, worm-core endpoints,
dashboard accessors) — pinning its semantics in a standalone
module surfaces breakages independently of payload-layer changes.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from wormbase_ledger.entries import make_drift_id


# ---------------------------------------------------------------------------
# Determinism + opacity
# ---------------------------------------------------------------------------


def test_make_drift_id_pure_function() -> None:
    """No global state — same args always produce the same hash."""
    args = dict(
        source_id="src-1",
        table_id="t1",
        column="c1",
        drift_kind="column_added",
        before=None,
        after={"type": "int"},
    )
    assert (
        make_drift_id(**args)  # type: ignore[arg-type]
        == make_drift_id(**args)  # type: ignore[arg-type]
        == make_drift_id(**args)  # type: ignore[arg-type]
    )


def test_make_drift_id_returns_32_lowercase_hex_chars() -> None:
    """Hex-only output keeps the hash URL-safe + SQL-safe."""
    h = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column=None,
        drift_kind="table_added",
    )
    assert isinstance(h, str)
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_make_drift_id_matches_sha256_prefix_definition() -> None:
    """The hash IS sha256-of-canonical-JSON truncated to 32 hex chars —
    pin the algorithm so callers can verify off-line if needed."""
    source_id = "src-1"
    table_id = "t1"
    column = "c1"
    drift_kind = "column_type_changed"
    before = {"type": "int"}
    after = {"type": "bigint"}
    canonical = json.dumps(
        {
            "source_id": source_id,
            "table_id": table_id,
            "column": column,
            "drift_kind": drift_kind,
            "before": before,
            "after": after,
        },
        sort_keys=True,
    )
    expected = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    actual = make_drift_id(
        source_id=source_id,
        table_id=table_id,
        column=column,
        drift_kind=drift_kind,
        before=before,
        after=after,
    )
    assert actual == expected


# ---------------------------------------------------------------------------
# Collision behavior across the identifying tuple
# ---------------------------------------------------------------------------


def test_make_drift_id_distinguishes_source_table_column() -> None:
    """Different identifying fields → different hashes."""
    base = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="c1",
        drift_kind="column_added",
        before=None,
        after={"type": "int"},
    )
    diffs = {
        make_drift_id(
            source_id="src-2",
            table_id="t1",
            column="c1",
            drift_kind="column_added",
            before=None,
            after={"type": "int"},
        ),
        make_drift_id(
            source_id="src-1",
            table_id="t2",
            column="c1",
            drift_kind="column_added",
            before=None,
            after={"type": "int"},
        ),
        make_drift_id(
            source_id="src-1",
            table_id="t1",
            column="c2",
            drift_kind="column_added",
            before=None,
            after={"type": "int"},
        ),
    }
    assert base not in diffs
    assert len(diffs) == 3


def test_make_drift_id_distinguishes_drift_kind() -> None:
    """The 5 documented drift_kinds produce distinct hashes for an
    otherwise-identical identifying tuple."""
    kinds = (
        "table_added", "table_removed",
        "column_added", "column_removed", "column_type_changed",
    )
    hashes = set()
    for kind in kinds:
        # Use a column / before / after shape compatible with each
        # kind so the hash space exercises the full tuple.
        if kind == "table_added":
            args = dict(source_id="src-1", table_id="t1", column=None,
                        drift_kind=kind, before=None, after={"t": 1})
        elif kind == "table_removed":
            args = dict(source_id="src-1", table_id="t1", column=None,
                        drift_kind=kind, before={"t": 1}, after=None)
        elif kind == "column_added":
            args = dict(source_id="src-1", table_id="t1", column="c1",
                        drift_kind=kind, before=None, after={"type": "int"})
        elif kind == "column_removed":
            args = dict(source_id="src-1", table_id="t1", column="c1",
                        drift_kind=kind, before={"type": "int"}, after=None)
        else:  # column_type_changed
            args = dict(source_id="src-1", table_id="t1", column="c1",
                        drift_kind=kind,
                        before={"type": "int"}, after={"type": "bigint"})
        hashes.add(make_drift_id(**args))  # type: ignore[arg-type]
    assert len(hashes) == 5


def test_make_drift_id_distinguishes_before_after_payloads() -> None:
    """Distinct before/after content for the same column-type-change →
    distinct drift_id (so a renamed-then-rolled-back transient doesn't
    collide with the original drift)."""
    base = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"type": "int"}, after={"type": "bigint"},
    )
    rolled_back = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"type": "bigint"}, after={"type": "int"},
    )
    nested_change = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"type": "int", "nullable": False},
        after={"type": "int", "nullable": True},
    )
    assert {base, rolled_back, nested_change} == {base, rolled_back, nested_change}
    assert len({base, rolled_back, nested_change}) == 3


# ---------------------------------------------------------------------------
# Stable JSON encoding under dict iteration noise
# ---------------------------------------------------------------------------


def test_make_drift_id_stable_under_before_after_key_order() -> None:
    """Key-insertion-order differences on before/after MUST NOT change
    the hash — sort_keys=True canonicalises the JSON encoding."""
    a = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"type": "int", "nullable": False, "default": 0},
        after={"default": 1, "nullable": True, "type": "bigint"},
    )
    b = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"default": 0, "nullable": False, "type": "int"},
        after={"type": "bigint", "nullable": True, "default": 1},
    )
    assert a == b


def test_make_drift_id_stable_under_nested_dict_key_order() -> None:
    """Nested-dict key order doesn't change the hash either (sort_keys
    recurses)."""
    a = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_added",
        before=None,
        after={"type": "int", "constraints": {"primary": True, "unique": True}},
    )
    b = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_added",
        before=None,
        after={"constraints": {"unique": True, "primary": True}, "type": "int"},
    )
    assert a == b


# ---------------------------------------------------------------------------
# Idempotency contract
# ---------------------------------------------------------------------------


def test_make_drift_id_same_drift_rewrite_dedups_at_pk() -> None:
    """The natural dedup property the projection PK leans on: re-
    emitting the same drift always lands on the same drift_id."""
    args = dict(
        source_id="src-snowflake-1",
        table_id="warehouse.orders",
        column=None,
        drift_kind="table_removed",
        before={"row_count": 1_000_000},
        after=None,
    )
    seen = {make_drift_id(**args) for _ in range(10)}  # type: ignore[arg-type]
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# Argument discipline
# ---------------------------------------------------------------------------


def test_make_drift_id_requires_keyword_arguments() -> None:
    """Mirror of L1's contract: positional args are refused so call
    sites can't accidentally swap source_id and table_id."""
    with pytest.raises(TypeError):
        make_drift_id(  # type: ignore[misc]
            "src-1", "t1", "c1", "column_added", None, {"type": "int"},
        )


def test_make_drift_id_accepts_none_before_after_defaults() -> None:
    """``before`` and ``after`` default to None for callers that only
    need the identifying tuple (e.g. dashboard lookup helpers)."""
    h1 = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column=None,
        drift_kind="table_added",
    )
    h2 = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column=None,
        drift_kind="table_added",
        before=None,
        after=None,
    )
    assert h1 == h2
