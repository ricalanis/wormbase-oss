"""L2 Sub-wave A — three new lake-side catalog-drift detection entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=132.
18 kinds remain before the Wave F Addendum 4 ceiling at 150. L-axis
family count = 24 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 + L8=3 +
L1=3 + L2=3) per Addendum 4 §E. **L2 is the FINAL planned axis in this
generation per spec §11** — any future L9+ requires a doctrine review
before design begins.

Pins three new payload classes for the L2 lake loop that detects
structural changes in external-catalog snapshots + the admin lifecycle
that acknowledges/rejects them. L2 is the 8th lake-side compounding
axis. L2 introduces ZERO new cross-axis Protocol chains today — its
inference reads catalog-mirror substrate (``external_catalog_imported``
snapshots) via a lightweight ``CatalogSnapshotReader`` Protocol added
in Sub-wave B. Cross-axis chain count stays at 3.

* ``CatalogDriftProposedPayload`` (kind ``catalog_drift_proposed``) —
  emitted by the L2 Compounding axis when a strategy (``table_set`` /
  ``column_set`` / ``column_type``) detects a structural change.
  Carries strict 5-value ``Literal[...]`` ``drift_kind``; conditional
  nullability on ``column`` / ``before`` / ``after`` enforced by a
  ``model_post_init`` cross-field validator.
* ``CatalogDriftAcknowledgedPayload`` (kind
  ``catalog_drift_acknowledged``) — operator sign-off on a drift as
  known/expected. Unlike L1's promote and L3-L8's confirm, this is a
  no-op record (no downstream pipeline trigger, no cross-axis effect).
* ``CatalogDriftRejectedPayload`` (kind ``catalog_drift_rejected``) —
  operator rejection with a categorical reason. The L2-specific 5th
  reason is ``expected_change`` (distinct from L1's ``duplicate``,
  L8's ``wrong_pairing``, L6's ``wrong_level``, L5's ``wrong_type``,
  L4's ``already_handled`` and L7's ``wrong_threshold``).

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``reason`` pinned
  to the 5 documented values; non-empty ``drift_id`` /
  ``source_id`` / ``table_id`` / ``strategy``; ``drift_kind`` pinned
  to the 5-value enum.
* Conditional nullability rules per drift_kind:
  - ``column`` REQUIRED for ``column_*``, FORBIDDEN for ``table_*``.
  - ``before`` FORBIDDEN for ``*_added`` (no prior value).
  - ``after`` FORBIDDEN for ``*_removed`` (no current value).
  - ``column_type_changed`` REQUIRES both ``before`` AND ``after``.
* ``make_drift_id`` determinism + collision behavior (same args →
  same hash; different args → different hash; same drift re-emitted
  → same hash).
* No collision with pre-existing ``external_catalog_*`` namespace.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    CatalogDriftAcknowledgedPayload,
    CatalogDriftProposedPayload,
    CatalogDriftRejectedPayload,
    make_drift_id,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "catalog_drift_proposed",
        "catalog_drift_acknowledged",
        "catalog_drift_rejected",
    ],
)
def test_catalog_drift_kind_registered(kind: str) -> None:
    """Each new L2 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


def test_catalog_drift_kinds_do_not_collide_with_external_catalog() -> None:
    """L2's ``catalog_drift_*`` namespace is distinct from the
    pre-existing ``external_catalog_*`` catalog-mirror substrate.

    Per spec §3 / §7 naming-collision check: the existing
    ``external_catalog_imported`` / ``external_catalog_drift_detected``
    kinds are the catalog-mirror substrate (raw structural-change
    records); L2 introduces a separate ``catalog_drift_*`` namespace
    (no ``external_`` prefix) carrying inference-bearing fields
    (strategy / confidence / reasoning / evidence). Pinning this here
    so a future rename collision triggers at commit time."""
    catalog_mirror_kinds = {
        "external_catalog_imported",
        "external_catalog_drift_detected",
    }
    drift_kinds = {
        "catalog_drift_proposed",
        "catalog_drift_acknowledged",
        "catalog_drift_rejected",
    }
    # All catalog-mirror kinds present (we did not rename them).
    assert catalog_mirror_kinds <= set(KIND_REGISTRY.keys())
    # All catalog-drift kinds present (we added them).
    assert drift_kinds <= set(KIND_REGISTRY.keys())
    # No overlap (L2 didn't reuse existing kind names).
    assert catalog_mirror_kinds.isdisjoint(drift_kinds)


# ---------------------------------------------------------------------------
# make_drift_id determinism + collision behavior
# ---------------------------------------------------------------------------


def test_make_drift_id_deterministic_same_args() -> None:
    """Same args → identical hash (idempotent dedup primitive)."""
    a = make_drift_id(
        source_id="src-stripe-1",
        table_id="charges",
        column=None,
        drift_kind="table_added",
    )
    b = make_drift_id(
        source_id="src-stripe-1",
        table_id="charges",
        column=None,
        drift_kind="table_added",
    )
    assert a == b


def test_make_drift_id_collision_only_on_full_tuple() -> None:
    """Different source / table / column / drift_kind / before / after
    → distinct hash. Same drift re-detected → dedup naturally."""
    base = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )
    diff_source = make_drift_id(
        source_id="src-stripe-2",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )
    diff_table = make_drift_id(
        source_id="src-stripe-1",
        table_id="orders",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )
    diff_column = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="phone",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )
    diff_kind = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="email",
        drift_kind="column_added",
        before=None,
        after={"type": "varchar(255)"},
    )
    diff_before = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "char(100)"},
        after={"type": "text"},
    )
    diff_after = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "varchar(512)"},
    )
    distinct = {
        base, diff_source, diff_table, diff_column,
        diff_kind, diff_before, diff_after,
    }
    assert len(distinct) == 7


def test_make_drift_id_is_32_hex_chars() -> None:
    """Returns a 32-char hex prefix (sha256[:32]); URL/SQL-safe opaque."""
    h = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="c1",
        drift_kind="column_added",
        before=None,
        after={"type": "int"},
    )
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_make_drift_id_keyword_only() -> None:
    """All args are keyword-only (no positional confusion at call sites)."""
    with pytest.raises(TypeError):
        # Positional call must fail — mirrors L1's make_candidate_id contract.
        make_drift_id(  # type: ignore[misc]
            "src-1", "t1", "c1", "column_added", None, {"type": "int"},
        )


def test_make_drift_id_stable_under_dict_iteration_order() -> None:
    """Stable JSON encoding (sort_keys) keeps the hash stable
    regardless of dict iteration order on before/after."""
    a = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="c1",
        drift_kind="column_type_changed",
        before={"type": "int", "nullable": False},
        after={"nullable": True, "type": "bigint"},
    )
    b = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="c1",
        drift_kind="column_type_changed",
        before={"nullable": False, "type": "int"},
        after={"type": "bigint", "nullable": True},
    )
    assert a == b


def test_make_drift_id_same_drift_rewrite_produces_same_hash() -> None:
    """Re-emitting the same drift always lands on the same drift_id —
    the natural dedup property the projection PK leans on."""
    args = dict(
        source_id="src-snowflake-1",
        table_id="warehouse.orders",
        column=None,
        drift_kind="table_removed",
        before={"row_count": 1_000_000, "column_count": 12},
        after=None,
    )
    hashes = {make_drift_id(**args) for _ in range(5)}  # type: ignore[arg-type]
    assert len(hashes) == 1


# ---------------------------------------------------------------------------
# CatalogDriftProposedPayload — roundtrip + base validators
# ---------------------------------------------------------------------------


def test_catalog_drift_proposed_roundtrip_table_added() -> None:
    """``table_added``: column=None, before=None, after carries snapshot."""
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="new_table",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"row_count_estimate": 0},
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="new_table",
        drift_kind="table_added",
        after={"row_count_estimate": 0},
        strategy="table_set",
        reasoning="table appears in current snapshot, absent from baseline",
        confidence=0.90,
        evidence={"before_tables": ["t1", "t2"], "after_tables": ["t1", "t2", "new_table"]},
    )
    assert CatalogDriftProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "catalog_drift_proposed"
    assert p.column is None
    assert p.before is None


def test_catalog_drift_proposed_roundtrip_table_removed() -> None:
    """``table_removed``: column=None, before carries snapshot, after=None."""
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="dropped_table",
        column=None,
        drift_kind="table_removed",
        before={"row_count_estimate": 50_000},
        after=None,
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="dropped_table",
        drift_kind="table_removed",
        before={"row_count_estimate": 50_000},
        strategy="table_set",
        reasoning="table absent from current snapshot, present in baseline",
        confidence=0.92,
        evidence={"before_tables": ["t1", "dropped_table"], "after_tables": ["t1"]},
    )
    assert CatalogDriftProposedPayload.model_validate(p.model_dump()) == p
    assert p.after is None


def test_catalog_drift_proposed_roundtrip_column_added() -> None:
    """``column_added``: column REQUIRED, before=None, after carries snapshot."""
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="customers",
        column="phone",
        drift_kind="column_added",
        before=None,
        after={"type": "varchar(20)"},
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="customers",
        column="phone",
        drift_kind="column_added",
        after={"type": "varchar(20)"},
        strategy="column_set",
        reasoning="column appears in current snapshot, absent from baseline",
        confidence=0.85,
        evidence={"before_columns": ["id", "name"], "after_columns": ["id", "name", "phone"]},
    )
    assert CatalogDriftProposedPayload.model_validate(p.model_dump()) == p
    assert p.column == "phone"
    assert p.before is None


def test_catalog_drift_proposed_roundtrip_column_removed() -> None:
    """``column_removed``: column REQUIRED, before carries snapshot, after=None."""
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="customers",
        column="legacy_field",
        drift_kind="column_removed",
        before={"type": "int"},
        after=None,
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="customers",
        column="legacy_field",
        drift_kind="column_removed",
        before={"type": "int"},
        strategy="column_set",
        reasoning="column absent from current snapshot, present in baseline",
        confidence=0.88,
        evidence={"before_columns": ["id", "legacy_field"], "after_columns": ["id"]},
    )
    assert CatalogDriftProposedPayload.model_validate(p.model_dump()) == p
    assert p.after is None


def test_catalog_drift_proposed_roundtrip_column_type_changed() -> None:
    """``column_type_changed``: column REQUIRED, both before AND after REQUIRED."""
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
        strategy="column_type",
        reasoning="type widened from varchar(255) to text",
        confidence=0.95,
        evidence={"before_type": "varchar(255)", "after_type": "text"},
    )
    assert CatalogDriftProposedPayload.model_validate(p.model_dump()) == p
    assert p.before == {"type": "varchar(255)"}
    assert p.after == {"type": "text"}


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_catalog_drift_proposed_rejects_out_of_range_confidence(bad: float) -> None:
    """confidence outside [0.0, 1.0] raises ValidationError."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=None,
        drift_kind="table_added", before=None, after={},
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            drift_kind="table_added",
            after={},
            strategy="table_set",
            reasoning="r",
            confidence=bad,
            evidence={},
        )
    assert "confidence" in str(exc.value)


@pytest.mark.parametrize(
    "field",
    [
        "drift_id",
        "source_id",
        "table_id",
        "strategy",
    ],
)
def test_catalog_drift_proposed_rejects_empty_required_string(field: str) -> None:
    """Each required identifier / strategy field rejects the empty string."""
    valid = dict(
        drift_id="abc123",
        source_id="src-1",
        table_id="t1",
        drift_kind="table_added",
        after={},
        strategy="table_set",
        reasoning="r",
        confidence=0.5,
        evidence={},
    )
    valid[field] = ""
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(**valid)  # type: ignore[arg-type]
    assert field in str(exc.value) or "non-empty" in str(exc.value)


@pytest.mark.parametrize(
    "strategy",
    ["table_set", "column_set", "column_type"],
)
def test_catalog_drift_proposed_accepts_canonical_strategies(strategy: str) -> None:
    """The three canonical strategies (spec §4) round-trip cleanly."""
    # Pick a drift_kind compatible with each strategy.
    if strategy == "table_set":
        kind, column, before, after = "table_added", None, None, {"t": 1}
    elif strategy == "column_set":
        kind, column, before, after = "column_added", "c1", None, {"type": "int"}
    else:
        kind, column, before, after = (
            "column_type_changed", "c1", {"type": "int"}, {"type": "bigint"},
        )
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=column,
        drift_kind=kind, before=before, after=after,
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="t1",
        column=column,
        drift_kind=kind,  # type: ignore[arg-type]
        before=before,
        after=after,
        strategy=strategy,
        reasoning="r",
        confidence=0.85,
        evidence={},
    )
    assert p.strategy == strategy


def test_catalog_drift_proposed_accepts_future_strategy_plugin() -> None:
    """``strategy`` is an open string field with a non-empty guard —
    future strategy plug-ins ship without ledger churn (only the
    canonical three are documented per spec §4)."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=None,
        drift_kind="table_added", before=None, after={},
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="t1",
        drift_kind="table_added",
        after={},
        strategy="custom_drift_plugin",
        reasoning="experimental strategy",
        confidence=0.5,
        evidence={},
    )
    assert p.strategy == "custom_drift_plugin"


# ---------------------------------------------------------------------------
# drift_kind enum conformance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drift_kind,column,before,after",
    [
        ("table_added", None, None, {"t": 1}),
        ("table_removed", None, {"t": 1}, None),
        ("column_added", "c1", None, {"type": "int"}),
        ("column_removed", "c1", {"type": "int"}, None),
        ("column_type_changed", "c1", {"type": "int"}, {"type": "bigint"}),
    ],
)
def test_catalog_drift_proposed_accepts_every_drift_kind(
    drift_kind: str, column: str | None, before: dict | None, after: dict | None,
) -> None:
    """Every documented drift_kind round-trips with its canonical
    nullability shape per spec §3.4."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=column,
        drift_kind=drift_kind, before=before, after=after,
    )
    p = CatalogDriftProposedPayload(
        drift_id=drift_id,
        source_id="src-1",
        table_id="t1",
        column=column,
        drift_kind=drift_kind,  # type: ignore[arg-type]
        before=before,
        after=after,
        strategy="table_set" if drift_kind.startswith("table_") else "column_set",
        reasoning="r",
        confidence=0.9,
        evidence={},
    )
    assert p.drift_kind == drift_kind


def test_catalog_drift_proposed_rejects_unknown_drift_kind() -> None:
    """``drift_kind`` is a strict Literal[...] — unknown values raise."""
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id="abc",
            source_id="src-1",
            table_id="t1",
            drift_kind="bogus_drift_kind",  # type: ignore[arg-type]
            after={},
            strategy="table_set",
            reasoning="r",
            confidence=0.5,
            evidence={},
        )
    assert "drift_kind" in str(exc.value)


# ---------------------------------------------------------------------------
# column null-rule enforcement (cross-field validators)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("drift_kind", ["table_added", "table_removed"])
def test_table_drift_kinds_forbid_column(drift_kind: str) -> None:
    """``column`` MUST be None for ``table_*`` drifts."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=None,
        drift_kind=drift_kind,
    )
    before = None if drift_kind == "table_added" else {"t": 1}
    after = {"t": 1} if drift_kind == "table_added" else None
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="should_not_be_set",
            drift_kind=drift_kind,  # type: ignore[arg-type]
            before=before,
            after=after,
            strategy="table_set",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "column" in str(exc.value)


@pytest.mark.parametrize(
    "drift_kind",
    ["column_added", "column_removed", "column_type_changed"],
)
def test_column_drift_kinds_require_column(drift_kind: str) -> None:
    """``column`` MUST be set (non-None) for ``column_*`` drifts."""
    if drift_kind == "column_added":
        before, after = None, {"type": "int"}
    elif drift_kind == "column_removed":
        before, after = {"type": "int"}, None
    else:
        before, after = {"type": "int"}, {"type": "bigint"}
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=None,
        drift_kind=drift_kind, before=before, after=after,
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            drift_kind=drift_kind,  # type: ignore[arg-type]
            before=before,
            after=after,
            strategy="column_set",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "column" in str(exc.value)


def test_column_drift_kinds_reject_empty_string_column() -> None:
    """``column``, when set, must be non-empty (empty-string trip wire)."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column="",
        drift_kind="column_added", before=None, after={"type": "int"},
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="",
            drift_kind="column_added",
            after={"type": "int"},
            strategy="column_set",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    # Could match either the non-empty validator or the column-required
    # cross-field check; both are valid rejections.
    assert "column" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# before/after null-rule enforcement (cross-field validators)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("drift_kind", ["table_added", "column_added"])
def test_added_drift_kinds_forbid_before(drift_kind: str) -> None:
    """``before`` MUST be None for ``*_added`` (no prior value to record)."""
    column = "c1" if drift_kind == "column_added" else None
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=column,
        drift_kind=drift_kind, before={"t": 1}, after={"type": "int"},
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column=column,
            drift_kind=drift_kind,  # type: ignore[arg-type]
            before={"t": 1},  # forbidden
            after={"type": "int"},
            strategy="table_set" if drift_kind == "table_added" else "column_set",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "before" in str(exc.value)


@pytest.mark.parametrize("drift_kind", ["table_removed", "column_removed"])
def test_removed_drift_kinds_forbid_after(drift_kind: str) -> None:
    """``after`` MUST be None for ``*_removed`` (no current value to record)."""
    column = "c1" if drift_kind == "column_removed" else None
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column=column,
        drift_kind=drift_kind, before={"t": 1}, after={"t": 2},
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column=column,
            drift_kind=drift_kind,  # type: ignore[arg-type]
            before={"t": 1},
            after={"t": 2},  # forbidden
            strategy="table_set" if drift_kind == "table_removed" else "column_set",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "after" in str(exc.value)


def test_column_type_changed_requires_before_and_after() -> None:
    """``column_type_changed`` MUST carry both before AND after."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before={"type": "int"}, after=None,
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="c1",
            drift_kind="column_type_changed",
            before={"type": "int"},
            after=None,  # missing
            strategy="column_type",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "before" in str(exc.value) or "after" in str(exc.value)


def test_column_type_changed_requires_before_when_after_set() -> None:
    """Symmetric: ``column_type_changed`` rejects missing ``before``."""
    drift_id = make_drift_id(
        source_id="src-1", table_id="t1", column="c1",
        drift_kind="column_type_changed",
        before=None, after={"type": "int"},
    )
    with pytest.raises(ValidationError) as exc:
        CatalogDriftProposedPayload(
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="c1",
            drift_kind="column_type_changed",
            before=None,  # missing
            after={"type": "int"},
            strategy="column_type",
            reasoning="r",
            confidence=0.9,
            evidence={},
        )
    assert "before" in str(exc.value) or "after" in str(exc.value)


# ---------------------------------------------------------------------------
# CatalogDriftAcknowledgedPayload
# ---------------------------------------------------------------------------


def test_catalog_drift_acknowledged_roundtrip_full() -> None:
    """Full payload (with notes) survives roundtrip."""
    p = CatalogDriftAcknowledgedPayload(
        drift_id="abc123",
        acknowledged_by_person_id="person-uuid-1",
        notes="known schema migration; planned for Q3",
    )
    assert CatalogDriftAcknowledgedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "catalog_drift_acknowledged"


def test_catalog_drift_acknowledged_roundtrip_minimal() -> None:
    """Minimal payload — no notes (acknowledgment without further commentary)."""
    p = CatalogDriftAcknowledgedPayload(
        drift_id="abc123",
        acknowledged_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert CatalogDriftAcknowledgedPayload.model_validate(p.model_dump()) == p


def test_catalog_drift_acknowledged_rejects_empty_drift_id() -> None:
    """Empty drift_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        CatalogDriftAcknowledgedPayload(
            drift_id="",
            acknowledged_by_person_id="person-uuid-1",
        )
    assert "drift_id" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# CatalogDriftRejectedPayload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "inconsequential",
        "expected_change",
        "out_of_scope",
        "other",
    ],
)
def test_catalog_drift_rejected_accepts_every_reason(reason: str) -> None:
    """All 5 documented rejection reasons are accepted (including the
    L2-specific ``expected_change``)."""
    p = CatalogDriftRejectedPayload(
        drift_id="abc123",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason
    assert CatalogDriftRejectedPayload.model_validate(p.model_dump()) == p


def test_catalog_drift_rejected_includes_expected_change() -> None:
    """``expected_change`` is the L2-specific reason (distinct from L1's
    ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``, L5's
    ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``)."""
    p = CatalogDriftRejectedPayload(
        drift_id="abc123",
        rejected_by_person_id="person-uuid-1",
        reason="expected_change",
        notes="planned schema migration; not noteworthy drift",
    )
    assert p.reason == "expected_change"
    assert p.kind == "catalog_drift_rejected"


def test_catalog_drift_rejected_rejects_unknown_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        CatalogDriftRejectedPayload(
            drift_id="abc123",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value)


def test_catalog_drift_rejected_rejects_empty_drift_id() -> None:
    """Empty drift_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        CatalogDriftRejectedPayload(
            drift_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "drift_id" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# Subscription eligibility
# ---------------------------------------------------------------------------


def test_catalog_drift_kinds_are_subscription_eligible() -> None:
    """L2 kinds appear in the subscription-eligible catalog. The
    family bucket is whatever ``FAMILY_PREFIXES`` resolves
    ``catalog_*`` to (today: ``other``; future addition of a
    ``catalog_*`` family entry would re-bucket cleanly)."""
    from wormbase_ledger.subscription_eligibility import (
        get_subscription_eligible_kinds,
    )

    rows = get_subscription_eligible_kinds()
    by_kind = {row["kind"]: row for row in rows}
    for kind in (
        "catalog_drift_proposed",
        "catalog_drift_acknowledged",
        "catalog_drift_rejected",
    ):
        assert kind in by_kind, f"{kind} missing from subscription-eligible catalog"
        # Family bucket stays stable — pin whatever today's mapping is
        # so a future re-bucket triggers visibly.
        assert by_kind[kind]["family"] in ("external_catalog", "other"), (
            f"{kind} resolved to unexpected family {by_kind[kind]['family']!r}; "
            "expected external_catalog (if catalog_* prefix added) or other"
        )
