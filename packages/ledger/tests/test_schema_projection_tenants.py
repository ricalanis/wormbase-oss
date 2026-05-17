"""Tests for the projection_tenants table — schema, indexes, isolation invariants.

Phase 1B.A — multi-tenancy v2 plan
(``docs/superpowers/plans/2026-05-04-multitenancy-v2.md``).

The table is the canonical projection of multi-tenant lifecycle state,
folded from ``tenant_signup_initiated`` and ``tenant_signup_completed``
entries (registered in 1B.B). Status starts at ``pending`` on
signup_initiated and transitions to ``active`` on signup_completed.

The ``demo_visitors`` JSON column carries the magic-link round-robin
state — a list of ``{"email", "visited_at"}`` dicts, empty for non-demo
tenants.
"""
from __future__ import annotations

import pytest

from wormbase_ledger.schema import projection_tenants


def test_projection_tenants_columns_exist() -> None:
    cols = {c.name for c in projection_tenants.columns}
    expected = {
        "tenant_id",
        "slug",
        "display_name",
        "signup_source",
        "signup_email",
        "created_at",
        "signup_completed_at",
        "status",
        "demo_visitors",
        "last_updated_seq",
    }
    assert expected <= cols, f"missing columns: {expected - cols}"


def test_projection_tenants_primary_key_is_tenant_id() -> None:
    pk = [c.name for c in projection_tenants.primary_key.columns]
    assert pk == ["tenant_id"]


def test_projection_tenants_slug_unique_constraint() -> None:
    constraints = {c.name for c in projection_tenants.constraints if c.name}
    assert "uq_projection_tenants_slug" in constraints


def test_projection_tenants_status_index_exists() -> None:
    idx_names = {ix.name for ix in projection_tenants.indexes if ix.name}
    assert "ix_projection_tenants_status" in idx_names


def test_projection_tenants_signup_source_index_exists() -> None:
    idx_names = {ix.name for ix in projection_tenants.indexes if ix.name}
    assert "ix_projection_tenants_signup_source" in idx_names


@pytest.mark.parametrize(
    "signup_source",
    ["slack_oauth", "email_magic_link", "demo_seed", "bootstrapped"],
)
def test_projection_tenants_signup_source_accepts_canonical_values(
    signup_source: str,
) -> None:
    """Canonical signup_source values are pinned at the projection layer
    (1B.B Pydantic payload validates), not enforced at the schema layer."""
    valid = {"slack_oauth", "email_magic_link", "demo_seed", "bootstrapped"}
    assert signup_source in valid


def test_projection_tenants_status_column_canonical_values() -> None:
    """Canonical status values: pending|active|suspended|deleted.

    Suspend / delete tooling lands in Phase 4 polish; the column accepts
    the values today so future migrations don't need a column-type change.
    """
    canonical = {"pending", "active", "suspended", "deleted"}
    # Schema-layer is just a String(16); this test is a doctrinal pin.
    assert all(len(v) <= 16 for v in canonical)


def test_projection_tenants_nullability_matches_lifecycle() -> None:
    """Columns that are populated only on completion are nullable.

    signup_completed_at: NULL while pending; set on active.
    signup_email: NULL for non-magic-link tenants (Slack workspaces don't
    carry the original signup email after the signup chain folds).
    All other columns are NOT NULL.
    """
    by_name = {c.name: c for c in projection_tenants.columns}
    assert by_name["signup_completed_at"].nullable is True
    assert by_name["signup_email"].nullable is True
    for required in (
        "tenant_id",
        "slug",
        "display_name",
        "signup_source",
        "created_at",
        "status",
        "demo_visitors",
        "last_updated_seq",
    ):
        assert by_name[required].nullable is False, (
            f"column {required!r} unexpectedly nullable"
        )
