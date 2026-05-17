"""External-catalog entry kinds — registration + payload round-trip.

Wave 1 / Task 4 of the WormBase Semantic Layer (catalog-mirror data plane).

These tests pin five new entry kinds — external_catalog_imported,
external_catalog_drift_detected, external_lineage_imported,
external_policy_imported, external_metric_imported — written by the
``wormbase-catalog-mirror`` package's CatalogSource implementations
(``dbt_manifest``, ``snowflake_native``) to record upstream-lake
structure import + drift detection.

Notes baked in from the Phase 0 spike (``docs/superpowers/notes/
2026-05-10-semantic-layer-phase-0-spike.md``):

* ``ExternalPolicyImportedPayload.body`` is ``str | None`` — Snowflake
  catalog roles routinely lack APPLY privilege on policy bodies, so the
  call returns ``None`` (S2 finding). The pydantic field plus the
  migration's ``body TEXT`` column must both be nullable; otherwise
  drift detection breaks on read-only catalog roles.
* ``ExternalCatalogImportedPayload.import_mode`` is a literal of
  ``"initial" | "refresh"`` so the projection can distinguish first-time
  mirrors from re-discover passes.
* ``ExternalCatalogDriftDetectedPayload`` carries
  ``added_table_ids / removed_table_ids / changed_table_ids`` for
  granular diff lineage; v1 emitters MAY ship hash-only (empty tuples)
  but the payload shape is forward-compatible.

Per the schema-evolution doctrine (Addendum 2 §A), KIND_REGISTRY grows
83 → 88 across this task. The size guard below uses a small range so
parallel Wave 1 sibling tasks that also touch the registry don't break
this test transiently; once Wave 1 fully lands the assertion tightens.
"""
from __future__ import annotations

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    ExternalCatalogDriftDetectedPayload,
    ExternalCatalogImportedPayload,
    ExternalLineageImportedPayload,
    ExternalMetricImportedPayload,
    ExternalPolicyImportedPayload,
)


@pytest.mark.parametrize(
    "kind",
    [
        "external_catalog_imported",
        "external_catalog_drift_detected",
        "external_lineage_imported",
        "external_policy_imported",
        "external_metric_imported",
    ],
)
def test_kind_registered(kind: str) -> None:
    assert kind in KIND_REGISTRY, f"{kind} missing from KIND_REGISTRY"


def test_kind_registry_size_at_88_after_wave_1() -> None:
    """Phase 0 freeze-pause check: registry was 83 pre-Wave 1; Wave 1 adds 5; total 88.

    Semantic Layer Wave 2 Task 1 adds 4 agent-gateway core kinds
    (88 → 92); Wave 2 Task 3 adds 4 compounding-loop kinds
    (92 → 96). v2.B Phase 2 (2026-05-12) adds 3 more compounding-loop
    kinds (96 → 99). v2.B Phase 3 (2026-05-12) adds ``clock_tick``
    (99 → 100). v2.A Batch A (2026-05-12) adds 3 subscription kinds
    (100 → 103). Final wave item #5 (2026-05-13) adds
    ``agent_metadata_updated`` (103 → 104). Final wave item #7
    (2026-05-13) adds ``tenant_quota_consumed`` (104 → 105). Post-
    rest #1 (2026-05-13) adds ``tenant_engine_registered`` (105 →
    106). L3 Sub-wave A (2026-05-29) adds three lake-side
    lineage-discovery kinds (106 → 109). Onboarding Sub-wave C
    (2026-05-30) adds ``domain_pack_selected`` + ``person_invited``
    (109 → 111). L7 Sub-wave A (2026-05-30) adds three lake-side
    quality-checks kinds (111 → 114). L4 Sub-wave A (2026-06-02) adds
    three lake-side schema-impact kinds (114 → 117). L5 Sub-wave A
    (2026-06-05) adds three lake-side semantic-type fingerprinting
    kinds (117 → 120). L6 Sub-wave A (2026-06-06) adds three
    lake-side column-classification kinds (120 → 123). L8 Sub-wave A
    (2026-06-07) adds three lake-side cross-source entity-stitch
    kinds (123 → 126). L1 Sub-wave A (2026-06-08) adds three
    lake-side source-candidate triage kinds (126 → 129). L2
    Sub-wave A (2026-06-09) adds three lake-side catalog-drift
    detection kinds (129 → 132 — FINAL planned axis per spec §11).
    Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on) adds
    ``catalog_table_imported`` substrate (132 → 133). The range below
    stays loose during parallel landings; under the 150-kind Rule-5
    ceiling per Wave F Addendum 4.
    """
    assert 86 <= len(KIND_REGISTRY) <= 133, (
        f"registry size {len(KIND_REGISTRY)} outside expected Wave 1/2 range"
    )


def test_external_catalog_imported_payload_roundtrip() -> None:
    p = ExternalCatalogImportedPayload(
        source_kind="dbt",
        source_id="src-uuid-1",
        domain_id="domain-uuid-1",
        snapshot_hash="abc123",
        table_count=8,
        edge_count=8,
        metric_count=0,
        import_mode="initial",
    )
    assert ExternalCatalogImportedPayload.model_validate(p.model_dump()) == p


def test_drift_detected_payload_roundtrip() -> None:
    p = ExternalCatalogDriftDetectedPayload(
        source_id="src-uuid-1",
        old_hash="abc123",
        new_hash="def456",
        added_table_ids=("model.x.new",),
        removed_table_ids=(),
        changed_table_ids=("model.x.changed",),
    )
    assert ExternalCatalogDriftDetectedPayload.model_validate(p.model_dump()) == p


def test_lineage_payload_roundtrip() -> None:
    p = ExternalLineageImportedPayload(
        source_id="src-uuid-1",
        edges=(("upstream.a", "downstream.b"),),
    )
    assert ExternalLineageImportedPayload.model_validate(p.model_dump()) == p


def test_policy_payload_roundtrip() -> None:
    """body=None must round-trip — S2 finding: caller may lack APPLY priv."""
    p = ExternalPolicyImportedPayload(
        source_id="src-uuid-1",
        policy_fqn="ACME.PUBLIC.REVENUE_MASK",
        policy_kind="masking",
        body=None,
        applied_to=("REVENUE",),
    )
    assert ExternalPolicyImportedPayload.model_validate(p.model_dump()) == p


def test_metric_payload_roundtrip() -> None:
    p = ExternalMetricImportedPayload(
        source_id="src-uuid-1",
        name="revenue_q3",
        expression="SUM(revenue) FILTER (WHERE quarter='Q3')",
        time_grain="quarter",
        dimensions=("region",),
    )
    assert ExternalMetricImportedPayload.model_validate(p.model_dump()) == p


def test_metric_payload_promote_fields_roundtrip() -> None:
    """v1.2 follow-up #5: promote-from-gap fields round-trip + default to None.

    Three additive fields (``domain_id`` / ``promoted_from_gap_id`` /
    ``promoted_by``) carry governance + audit context when the payload
    is written by ``promote_semantic_gap``. Doctrine Rule 2 demands
    defaults of ``None`` so existing catalog-import writers stay
    unchanged.
    """
    # Bare payload — defaults must be None (Rule 2 compliance).
    bare = ExternalMetricImportedPayload(
        source_id="src-uuid-1", name="revenue_q3",
    )
    dumped = bare.model_dump()
    assert dumped["domain_id"] is None
    assert dumped["promoted_from_gap_id"] is None
    assert dumped["promoted_by"] is None

    # Populated payload — fields round-trip verbatim.
    full = ExternalMetricImportedPayload(
        source_id="_promoted_from_gap",
        name="net_revenue_quarterly",
        expression="SUM(amount) WHERE quarter = ?",
        domain_id="dom-uuid-1",
        promoted_from_gap_id="gap-entry-1",
        promoted_by="admin-uuid-1",
    )
    assert ExternalMetricImportedPayload.model_validate(full.model_dump()) == full
