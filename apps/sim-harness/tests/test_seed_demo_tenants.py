"""Phase 1B.G — demo tenant carousel seeding tests.

Pairs with the spike + plan at:
  - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
  - docs/superpowers/plans/2026-05-04-multitenancy-v2.md
"""
from __future__ import annotations

from wormbase_sim_harness.seed_demo_tenants import (
    DEMO_TENANT_DEFAULTS,
    build_seed_plan,
)


def test_default_carousel_has_five_tenants() -> None:
    assert len(DEMO_TENANT_DEFAULTS) == 5


def test_default_carousel_slugs_are_canonical() -> None:
    expected = {
        "wormbase-saas-demo",
        "wormbase-fintech-demo",
        "wormbase-marketplace-demo",
        "wormbase-ecommerce-demo",
        "wormbase-agency-demo",
    }
    actual = {t["slug"] for t in DEMO_TENANT_DEFAULTS}
    assert actual == expected


def test_each_demo_tenant_has_required_metadata() -> None:
    for t in DEMO_TENANT_DEFAULTS:
        assert t["slug"]
        assert t["display_name"]
        assert t["domain_pack"] in {"saas", "fintech", "marketplace"}


def test_build_seed_plan_emits_initiated_then_completed() -> None:
    plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
    # Each tenant: 1 initiated + 1 completed.
    assert len(plan) == 2 * len(DEMO_TENANT_DEFAULTS)
    # Pairs ordered by tenant index.
    for i, tenant in enumerate(DEMO_TENANT_DEFAULTS):
        assert plan[2 * i]["kind"] == "tenant_signup_initiated"
        assert plan[2 * i]["slug"] == tenant["slug"]
        assert plan[2 * i + 1]["kind"] == "tenant_signup_completed"
        assert plan[2 * i + 1]["assigned_tenant_slug"] == tenant["slug"]


def test_build_seed_plan_assigns_signup_source_demo_seed() -> None:
    plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
    for entry in plan:
        assert entry["signup_source"] == "demo_seed"


def test_build_seed_plan_signup_email_is_null() -> None:
    """Demo tenants are seeded sans evaluator email; the magic-link
    confirm step is what binds an email to the tenant via demo_visitors."""
    plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
    for entry in plan:
        assert entry["signup_email"] is None


def test_build_seed_plan_pending_hash_is_64_hex() -> None:
    """The hash slot is filled with a deterministic per-slug sha256."""
    plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
    for entry in plan:
        if entry["kind"] != "tenant_signup_initiated":
            continue
        assert len(entry["pending_token_hash"]) == 64
        assert all(
            c in "0123456789abcdef" for c in entry["pending_token_hash"]
        )


def test_build_seed_plan_pending_hash_distinct_per_slug() -> None:
    """Two different demo slugs produce two different hashes."""
    plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
    initiated = [e for e in plan if e["kind"] == "tenant_signup_initiated"]
    hashes = {e["pending_token_hash"] for e in initiated}
    assert len(hashes) == len(initiated)


def test_build_seed_plan_idempotent_per_slug() -> None:
    """Running build_seed_plan twice on the same tenant list produces
    byte-identical output — caller can rely on idempotency of the seed
    batch (caller-side idempotency comes from UUIDv5 derivation +
    projection upsert)."""
    plan_a = build_seed_plan(DEMO_TENANT_DEFAULTS)
    plan_b = build_seed_plan(DEMO_TENANT_DEFAULTS)
    assert plan_a == plan_b


def test_build_seed_plan_handles_subset_of_tenants() -> None:
    """Caller may pass a subset of the carousel — useful for tests
    and small-deployment fits."""
    subset = DEMO_TENANT_DEFAULTS[:2]
    plan = build_seed_plan(subset)
    assert len(plan) == 4  # 2 tenants * 2 entries each
