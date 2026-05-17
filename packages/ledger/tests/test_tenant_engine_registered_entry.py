"""Tests for ``TenantEngineRegisteredPayload`` — post-rest #1 (2026-05-13).

Pins the new ledger entry kind that backs Phase 2 of the engine-per-tenant
routing design (``docs/superpowers/specs/2026-05-22-engine-per-tenant-
routing-design.md``):

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently
  for both shared and isolated engine kinds + the migration carry-over.
* The closed ``engine_kind`` Literal: shared | isolated only.
* The cross-field invariant: ``engine_kind="isolated"`` requires a non-
  empty ``engine_dsn_secret_ref``; ``engine_kind="shared"`` requires
  ``engine_dsn_secret_ref=None`` (no stray DSN ref on shared).
* ``provisioned_at`` and ``migrated_from_shared_at`` must be tz-aware
  (defensive; same invariant as ``LedgerEntry.ts``).
* ``tenant_slug`` and ``provisioned_by_person_id`` are non-empty.

KIND_REGISTRY grew 105 → 106 (additive per schema-evolution doctrine
Rule 2; under the 120-kind Wave F Addendum 1 ceiling). Engine-per-
tenant Phase 2 — Phases 3+4 (admin migration tool + production
cutover) deferred to operator-driven tooling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    TenantEngineRegisteredPayload,
)


def test_tenant_engine_registered_kind_registered() -> None:
    """Auto-registration via EntryPayload.__init_subclass__ — the kind
    appears in ``KIND_REGISTRY`` and maps back to the payload class."""
    assert "tenant_engine_registered" in KIND_REGISTRY
    assert (
        KIND_REGISTRY["tenant_engine_registered"]
        is TenantEngineRegisteredPayload
    )


def test_tenant_engine_registered_roundtrip_shared() -> None:
    """Shared-engine registration (Shape A canonical state) round-trips
    byte-equivalently and carries no DSN ref."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="acme",
        engine_kind="shared",
        engine_dsn_secret_ref=None,
        provisioned_at=now,
        migrated_from_shared_at=None,
        provisioned_by_person_id="person-uuid-installer",
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.kind == "tenant_engine_registered"
    assert p.engine_dsn_secret_ref is None


def test_tenant_engine_registered_roundtrip_isolated() -> None:
    """Isolated-engine registration (Shape B activation) round-trips
    byte-equivalently and carries the vault DSN reference."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="globex",
        engine_kind="isolated",
        engine_dsn_secret_ref="vault://wormbase/tenants/globex/engine_dsn",
        provisioned_at=now,
        migrated_from_shared_at=None,
        provisioned_by_person_id="person-uuid-admin",
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.engine_kind == "isolated"
    assert p.engine_dsn_secret_ref == (
        "vault://wormbase/tenants/globex/engine_dsn"
    )


def test_tenant_engine_registered_roundtrip_migration_carryover() -> None:
    """A Shape A → Shape B migration entry carries
    ``migrated_from_shared_at`` so the cutover moment is auditable
    (Phase 3 admin tool surface; payload contract is stable now)."""
    now = datetime.now(timezone.utc)
    migrated_at = now - timedelta(minutes=2)
    p = TenantEngineRegisteredPayload(
        tenant_slug="initech",
        engine_kind="isolated",
        engine_dsn_secret_ref="vault://wormbase/tenants/initech/engine_dsn",
        provisioned_at=now,
        migrated_from_shared_at=migrated_at,
        provisioned_by_person_id="person-uuid-admin",
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.migrated_from_shared_at == migrated_at


def test_tenant_engine_registered_isolated_requires_dsn_ref() -> None:
    """``engine_kind="isolated"`` REQUIRES a non-empty
    ``engine_dsn_secret_ref``. Without it the registry would point at
    a missing engine — a Shape B failure mode."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="isolated",
            engine_dsn_secret_ref=None,
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_shared_forbids_dsn_ref() -> None:
    """``engine_kind="shared"`` MUST NOT carry an
    ``engine_dsn_secret_ref``. A stray DSN ref on a shared
    registration would silently look like a misconfigured isolated
    engine to the registry resolver."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            engine_dsn_secret_ref="vault://stray/ref",  # invalid
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_rejects_invalid_engine_kind() -> None:
    """``engine_kind`` is a closed Literal — shared | isolated only."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="federated",  # type: ignore[arg-type]
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_rejects_naive_provisioned_at() -> None:
    """``provisioned_at`` must be tz-aware — same invariant as
    ``LedgerEntry.ts``."""
    naive_now = datetime.utcnow()  # naive — no tzinfo
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=naive_now,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_rejects_naive_migrated_from_shared_at() -> None:
    """``migrated_from_shared_at`` when present must be tz-aware too —
    the invariant doesn't get a pass for the optional field."""
    aware_now = datetime.now(timezone.utc)
    naive_migrated = datetime.utcnow()
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="isolated",
            engine_dsn_secret_ref="vault://x/y",
            provisioned_at=aware_now,
            migrated_from_shared_at=naive_migrated,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_rejects_empty_slug() -> None:
    """Empty ``tenant_slug`` is rejected — every registration must be
    attributable to a tenant."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
        )


def test_tenant_engine_registered_rejects_empty_provisioned_by() -> None:
    """``provisioned_by_person_id`` is the operator audit anchor — must
    be non-empty so the registration is always attributable."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="",
        )


# ---------------------------------------------------------------------------
# Multi-region routing (post-rest #7, 2026-05-13)
#
# Additive ``region`` field — default None preserves byte-identical
# Phase 1+2 (#1) replay. When set, pins the tenant's preferred region
# for ops + monitoring. KIND_REGISTRY size unchanged at 106.
# ---------------------------------------------------------------------------


def test_tenant_engine_registered_region_defaults_to_none() -> None:
    """The ``region`` field is additive with a ``None`` default — the
    pre-region payload shape continues to validate cleanly so replay
    over Phase 1+2 entries is byte-identical."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="acme",
        engine_kind="shared",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-1",
    )
    assert p.region is None


def test_tenant_engine_registered_region_roundtrip() -> None:
    """A full payload with ``region`` round-trips byte-equivalently —
    multi-region routing extension preserves replay determinism."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="globex",
        engine_kind="isolated",
        engine_dsn_secret_ref="vault://wormbase/tenants/globex/engine_dsn",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-admin",
        region="eu-central-1",
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.region == "eu-central-1"


def test_tenant_engine_registered_region_optional_on_shared() -> None:
    """The ``region`` field is independent of ``engine_kind`` — shared
    engines can carry a region too (a tenant pinned to us-west-2 still
    rides the shared engine in that region)."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="acme",
        engine_kind="shared",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-1",
        region="us-west-2",
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.region == "us-west-2"
    assert p.engine_dsn_secret_ref is None  # shared/None invariant preserved


# ---------------------------------------------------------------------------
# Per-tenant HNSW tuning (next-pass #6, 2026-05-13)
#
# Additive ``hnsw_m`` / ``hnsw_ef_construction`` fields — defaults
# ``(None, None)`` preserve byte-identical Phase 1+2 + post-rest #7
# replay. Ranges match the v019 migration env-knob ranges
# (m ∈ [4, 64], ef_construction ∈ [16, 256]) so payload-level and
# migration-runner-level invariants line up. KIND_REGISTRY size
# unchanged at 106. The v019 wire-up is deferred to the Phase 3+4
# admin migration tool; these fields exist as durable record only.
# ---------------------------------------------------------------------------


def test_tenant_engine_registered_hnsw_params_default_to_none() -> None:
    """Both HNSW fields are additive with ``None`` defaults — the
    pre-tuning payload shape continues to validate cleanly so replay
    over pre-#6 entries is byte-identical."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="acme",
        engine_kind="shared",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-1",
    )
    assert p.hnsw_m is None
    assert p.hnsw_ef_construction is None


def test_tenant_engine_registered_hnsw_params_roundtrip() -> None:
    """A full payload with both HNSW overrides round-trips byte-
    equivalently — per-tenant tuning preserves replay determinism."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="globex",
        engine_kind="isolated",
        engine_dsn_secret_ref="vault://wormbase/tenants/globex/engine_dsn",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-admin",
        hnsw_m=24,
        hnsw_ef_construction=128,
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.hnsw_m == 24
    assert p.hnsw_ef_construction == 128


def test_tenant_engine_registered_hnsw_params_independently_optional() -> None:
    """Each HNSW field is independently optional — overriding ``m``
    only (or ``ef_construction`` only) is supported because v019's
    env globals are read independently too."""
    now = datetime.now(timezone.utc)
    p = TenantEngineRegisteredPayload(
        tenant_slug="initech",
        engine_kind="shared",
        provisioned_at=now,
        provisioned_by_person_id="person-uuid-1",
        hnsw_m=32,
        # hnsw_ef_construction left at default (None)
    )
    assert TenantEngineRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.hnsw_m == 32
    assert p.hnsw_ef_construction is None


def test_tenant_engine_registered_rejects_hnsw_m_below_range() -> None:
    """``hnsw_m`` below the v019 range [4, 64] is rejected — payload-
    level invariant matches the migration-runner-level invariant."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
            hnsw_m=3,  # below min
        )


def test_tenant_engine_registered_rejects_hnsw_m_above_range() -> None:
    """``hnsw_m`` above the v019 range [4, 64] is rejected — payload-
    level invariant matches the migration-runner-level invariant."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
            hnsw_m=65,  # above max
        )


def test_tenant_engine_registered_rejects_hnsw_ef_construction_below_range() -> None:
    """``hnsw_ef_construction`` below v019 range [16, 256] is rejected."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
            hnsw_ef_construction=15,  # below min
        )


def test_tenant_engine_registered_rejects_hnsw_ef_construction_above_range() -> None:
    """``hnsw_ef_construction`` above v019 range [16, 256] is rejected."""
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        TenantEngineRegisteredPayload(
            tenant_slug="acme",
            engine_kind="shared",
            provisioned_at=now,
            provisioned_by_person_id="person-uuid-1",
            hnsw_ef_construction=257,  # above max
        )


def test_tenant_engine_registered_hnsw_range_boundaries_accepted() -> None:
    """Boundary values ``m=4``, ``m=64``, ``ef=16``, ``ef=256`` are
    inclusively valid — pins the v019 range contract exactly."""
    now = datetime.now(timezone.utc)
    for m in (4, 64):
        for ef in (16, 256):
            p = TenantEngineRegisteredPayload(
                tenant_slug="acme",
                engine_kind="shared",
                provisioned_at=now,
                provisioned_by_person_id="person-uuid-1",
                hnsw_m=m,
                hnsw_ef_construction=ef,
            )
            assert p.hnsw_m == m
            assert p.hnsw_ef_construction == ef


def test_kind_registry_size_unchanged_by_hnsw_fields() -> None:
    """Next-pass #6 is additive on an existing kind — KIND_REGISTRY
    size MUST remain unchanged across the hnsw field-pin work.

    L3 Sub-wave A (2026-05-29) lands the lake-side lineage-discovery
    loop's three new kinds (``lineage_edge_proposed`` /
    ``lineage_edge_confirmed`` / ``lineage_edge_rejected``), bumping
    the baseline from 106 → 109 per schema-evolution doctrine Rule
    2. The hnsw work itself remains additive on an existing kind;
    only the L3 batch grows the registry. Test name retains the
    hnsw-pin framing; the assertion tracks current size.

    Onboarding Sub-wave C (2026-05-30) adds ``domain_pack_selected``
    + ``person_invited`` — 109 → 111 per Rule 2.

    L7 Sub-wave A (2026-05-30) adds ``quality_check_proposed`` /
    ``quality_check_confirmed`` / ``quality_check_rejected`` — 111 →
    114 per Rule 2.

    L4 Sub-wave A (2026-06-02) adds ``schema_impact_proposed`` /
    ``schema_impact_confirmed`` / ``schema_impact_rejected`` — 114 →
    117 per Rule 2.

    L5 Sub-wave A (2026-06-05) adds ``semantic_type_proposed`` /
    ``semantic_type_confirmed`` / ``semantic_type_rejected`` — 117 →
    120 per Rule 2; 30 headroom under the 150-kind Rule-5 ceiling
    raised by Wave F Addendum 4.

    L6 Sub-wave A (2026-06-06) adds ``column_classification_proposed`` /
    ``column_classification_confirmed`` /
    ``column_classification_rejected`` — 120 → 123 per Rule 2; 27
    headroom under the 150-kind Rule-5 ceiling. L-axis family count
    12 → 15 of 30 cap per Addendum 4 §E.

    L8 Sub-wave A (2026-06-07) adds ``entity_stitch_proposed`` /
    ``entity_stitch_confirmed`` / ``entity_stitch_rejected`` — 123 →
    126 per Rule 2; 24 headroom under the 150-kind Rule-5 ceiling.
    L-axis family count 15 → 18 of 30 cap per Addendum 4 §E.

    L1 Sub-wave A (2026-06-08) adds ``source_candidate_proposed`` /
    ``source_candidate_promoted`` / ``source_candidate_rejected`` —
    126 → 129 per Rule 2; 21 headroom under the 150-kind Rule-5
    ceiling. L-axis family count 18 → 21 of 30 cap per Addendum 4
    §E (9 headroom remaining for L2 + 2 future axes).

    L2 Sub-wave A (2026-06-09) adds ``catalog_drift_proposed`` /
    ``catalog_drift_acknowledged`` / ``catalog_drift_rejected`` —
    129 → 132 per Rule 2; 18 headroom under the 150-kind Rule-5
    ceiling. L-axis family count 21 → 24 of 30 cap per Addendum 4
    §E. **L2 is the FINAL planned axis in this generation per
    spec §11** (any future L9+ requires doctrine review).

    Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on) adds
    ``catalog_table_imported`` — 132 → 133 per Rule 2; substrate
    only, L-axis family count unchanged at 24 of 30."""
    assert len(KIND_REGISTRY) == 133
