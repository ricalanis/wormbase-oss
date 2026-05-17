"""Catalog-mirror Wave 2 Sub-wave A — ``catalog_table_imported`` payload.

Substrate for per-table column metadata. Wave 2 motivation: today's
``ExternalCatalogImportedPayload`` carries only counts + hashes, so L2
TableSet + L8 SchemaShape strategies cannot fold actual table /
column structure from the ledger. This payload carries one
``(source_id, snapshot_hash, table_id)`` per discovered table with
the per-column ``CatalogColumnSpec`` list — restoring first-class
per-table catalog structure to the ledger substrate.

Additive per schema-evolution doctrine Rule 2; net +1 →
KIND_REGISTRY=133. L-axis family count unchanged at 24 of 30 cap per
Addendum 4 §E — ``catalog_table_imported`` is substrate, not a
lake-axis kind.

These tests pin:

* Registration in ``KIND_REGISTRY`` + ``ALL_KINDS`` via
  ``EntryPayload.__init_subclass__`` (auto-registration).
* Roundtrip via ``model_dump → model_validate`` byte-equivalently
  for full-field, empty-columns, and nullable-type payloads.
* Strict validation: ``source_id`` / ``snapshot_hash`` / ``table_id``
  must be non-empty; ``columns`` may be the empty tuple; per-column
  ``CatalogColumnSpec.name`` must be non-empty; ``type`` is nullable.
* No collision with the established catalog-mirror namespace
  (``external_catalog_*``).
* Hash-stable JSON round-trip (frozen models so ``model_dump`` is
  byte-identical across replays).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    CatalogColumnSpec,
    CatalogTableImportedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_catalog_table_imported_registered_in_kind_registry() -> None:
    """The new kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert "catalog_table_imported" in KIND_REGISTRY
    assert "catalog_table_imported" in ALL_KINDS
    assert KIND_REGISTRY["catalog_table_imported"] is CatalogTableImportedPayload


def test_catalog_table_imported_does_not_collide_with_external_catalog_namespace() -> None:
    """The substrate-only kind sits alongside the existing
    catalog-mirror namespace; no collision with the established
    ``external_catalog_*`` kinds."""
    established = {
        "external_catalog_imported",
        "external_catalog_drift_detected",
        "external_lineage_imported",
        "external_policy_imported",
        "external_metric_imported",
    }
    # All established kinds remain registered.
    assert established <= set(KIND_REGISTRY.keys())
    # New substrate kind is distinct from all of them.
    assert "catalog_table_imported" not in established


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


def test_full_payload_roundtrips() -> None:
    """Full payload (multi-column table) round-trips byte-identically."""
    p = CatalogTableImportedPayload(
        source_id="src-snowflake-1",
        snapshot_hash="abc123def456",
        table_id="ANALYTICS.PUBLIC.ORDERS",
        columns=(
            CatalogColumnSpec(name="id", type="NUMBER"),
            CatalogColumnSpec(name="amount", type="NUMBER(10,2)"),
            CatalogColumnSpec(name="customer_id", type="VARCHAR"),
            CatalogColumnSpec(name="created_at", type="TIMESTAMP_TZ"),
        ),
    )
    dumped = p.model_dump()
    rehydrated = CatalogTableImportedPayload.model_validate(dumped)
    assert rehydrated == p


def test_empty_columns_tuple_is_valid() -> None:
    """A table with no discovered columns is a valid state — e.g. a
    permissions-denied connector that sees the table exists but
    cannot list its columns. The validator must accept the empty
    tuple without raising."""
    p = CatalogTableImportedPayload(
        source_id="src-1",
        snapshot_hash="hash-1",
        table_id="t1",
        columns=(),
    )
    assert p.columns == ()
    # And it round-trips through JSON.
    raw = json.dumps(p.model_dump())
    rehydrated = CatalogTableImportedPayload.model_validate_json(raw)
    assert rehydrated == p


def test_columns_default_is_empty_tuple() -> None:
    """``columns`` may be omitted at construction; default is ``()``."""
    p = CatalogTableImportedPayload(
        source_id="src-1",
        snapshot_hash="hash-1",
        table_id="t1",
    )
    assert p.columns == ()


def test_column_spec_nullable_type_roundtrips() -> None:
    """``CatalogColumnSpec.type`` is nullable — connectors that lack
    column-type introspection (raw CSV headers, etc.) can leave it
    None. Round-trip must preserve the None correctly."""
    p = CatalogTableImportedPayload(
        source_id="src-csv-1",
        snapshot_hash="hash-csv-1",
        table_id="customers.csv",
        columns=(
            CatalogColumnSpec(name="header1"),
            CatalogColumnSpec(name="header2", type=None),
            CatalogColumnSpec(name="header3", type="string"),
        ),
    )
    dumped = p.model_dump()
    assert dumped["columns"] == (
        {"name": "header1", "type": None},
        {"name": "header2", "type": None},
        {"name": "header3", "type": "string"},
    )
    rehydrated = CatalogTableImportedPayload.model_validate(dumped)
    assert rehydrated == p


def test_json_roundtrip_is_byte_stable() -> None:
    """Two dumps of the same payload produce byte-identical JSON
    (the frozen model + tuple-typed columns make replay-stable
    serialization possible)."""
    p = CatalogTableImportedPayload(
        source_id="src-1",
        snapshot_hash="h-1",
        table_id="t1",
        columns=(
            CatalogColumnSpec(name="c1", type="int"),
            CatalogColumnSpec(name="c2", type="varchar"),
        ),
    )
    a = p.model_dump_json()
    b = p.model_dump_json()
    assert a == b


# ---------------------------------------------------------------------------
# Validation — required fields
# ---------------------------------------------------------------------------


def test_source_id_required_non_empty() -> None:
    """``source_id`` must be non-empty."""
    with pytest.raises(ValidationError):
        CatalogTableImportedPayload(
            source_id="",
            snapshot_hash="h",
            table_id="t",
        )


def test_snapshot_hash_required_non_empty() -> None:
    """``snapshot_hash`` must be non-empty (it links back to the parent
    ``external_catalog_imported``'s snapshot_hash)."""
    with pytest.raises(ValidationError):
        CatalogTableImportedPayload(
            source_id="s",
            snapshot_hash="",
            table_id="t",
        )


def test_table_id_required_non_empty() -> None:
    """``table_id`` must be non-empty."""
    with pytest.raises(ValidationError):
        CatalogTableImportedPayload(
            source_id="s",
            snapshot_hash="h",
            table_id="",
        )


def test_source_id_missing_raises() -> None:
    """Omitted ``source_id`` raises ValidationError (required field)."""
    with pytest.raises(ValidationError):
        CatalogTableImportedPayload(  # type: ignore[call-arg]
            snapshot_hash="h",
            table_id="t",
        )


def test_extra_fields_forbidden() -> None:
    """The frozen / extra='forbid' config rejects unknown keys at
    write time so the on-wire schema cannot accidentally pick up
    drifted fields from a stale emitter."""
    with pytest.raises(ValidationError):
        CatalogTableImportedPayload(  # type: ignore[call-arg]
            source_id="s",
            snapshot_hash="h",
            table_id="t",
            unknown_field="oops",
        )


# ---------------------------------------------------------------------------
# Validation — per-column CatalogColumnSpec
# ---------------------------------------------------------------------------


def test_column_spec_name_required_non_empty() -> None:
    """``CatalogColumnSpec.name`` must be non-empty."""
    with pytest.raises(ValidationError):
        CatalogColumnSpec(name="")


def test_column_spec_extra_fields_forbidden() -> None:
    """Per-column spec also forbids unknown keys."""
    with pytest.raises(ValidationError):
        CatalogColumnSpec(  # type: ignore[call-arg]
            name="c1",
            type="int",
            description="oops",
        )


def test_column_spec_default_type_is_none() -> None:
    """Constructing without ``type`` defaults to None."""
    spec = CatalogColumnSpec(name="c1")
    assert spec.type is None


def test_column_spec_roundtrip_with_explicit_none() -> None:
    """Explicit ``type=None`` survives the round-trip."""
    spec = CatalogColumnSpec(name="c1", type=None)
    dumped = spec.model_dump()
    assert dumped == {"name": "c1", "type": None}
    rehydrated = CatalogColumnSpec.model_validate(dumped)
    assert rehydrated == spec


# ---------------------------------------------------------------------------
# Frozen / immutability
# ---------------------------------------------------------------------------


def test_payload_is_frozen() -> None:
    """Frozen model — mutating the payload after construction raises."""
    p = CatalogTableImportedPayload(
        source_id="s", snapshot_hash="h", table_id="t",
    )
    with pytest.raises(ValidationError):
        p.source_id = "other"  # type: ignore[misc]


def test_column_spec_is_frozen() -> None:
    """``CatalogColumnSpec`` is frozen — mutation raises."""
    spec = CatalogColumnSpec(name="c1", type="int")
    with pytest.raises(ValidationError):
        spec.type = "varchar"  # type: ignore[misc]
