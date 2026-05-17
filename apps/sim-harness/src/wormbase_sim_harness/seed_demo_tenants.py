"""Seed the 3-5 demo tenants for the magic-link evaluator carousel.

Phase 1B.G of the multi-tenancy v2 plan
(``docs/superpowers/plans/2026-05-04-multitenancy-v2.md``). Each demo
tenant gets a ``tenant_signup_initiated`` + ``tenant_signup_completed``
pair (``signup_source='demo_seed'``), bypassing the magic-link path. The
``projection_tenants`` row carries ``signup_source='demo_seed'`` so the
magic-link confirm endpoint can filter to the demo carousel.

Idempotent: re-running ``wormbase demo seed --demo-tenants`` produces
the same tenant_id derivation (UUIDv5 of the slug under
``WORMBASE_TENANT_NAMESPACE``) and the projection upserts on tenant_id,
so the seed batch is safe to retry.
"""
from __future__ import annotations

import hashlib
from typing import Any

DEMO_TENANT_DEFAULTS: list[dict[str, Any]] = [
    {
        "slug": "wormbase-saas-demo",
        "display_name": "WormBase SaaS Demo",
        "domain_pack": "saas",
    },
    {
        "slug": "wormbase-fintech-demo",
        "display_name": "WormBase Fintech Demo",
        "domain_pack": "fintech",
    },
    {
        "slug": "wormbase-marketplace-demo",
        "display_name": "WormBase Marketplace Demo",
        "domain_pack": "marketplace",
    },
    {
        "slug": "wormbase-ecommerce-demo",
        "display_name": "WormBase Ecommerce Demo",
        # closest fit; an ecommerce-specific pack is Phase 4
        "domain_pack": "saas",
    },
    {
        "slug": "wormbase-agency-demo",
        "display_name": "WormBase Agency Demo",
        "domain_pack": "saas",
    },
]


def _slug_specific_hash(slug: str) -> str:
    """Deterministic placeholder for demo-seed pending_token_hash.

    Demo seeds bypass the actual magic-link request flow, so there's no
    real token to hash. Use a stable per-slug sha256 so the entry is
    deterministic across reseeds.
    """
    return hashlib.sha256(f"demo-seed:{slug}".encode()).hexdigest()


def build_seed_plan(tenants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce the ordered list of ledger writes that seed demo tenants.

    Each tenant becomes two entries:
      - tenant_signup_initiated: pre-fills the projection_tenants row.
      - tenant_signup_completed: marks status='active'.

    Caller writes these in order (one PEVR cycle per entry); the
    projection builder folds them.
    """
    plan: list[dict[str, Any]] = []
    for t in tenants:
        plan.append({
            "kind": "tenant_signup_initiated",
            "slug": t["slug"],
            "display_name": t["display_name"],
            "signup_source": "demo_seed",
            "signup_email": None,
            "pending_token_hash": _slug_specific_hash(t["slug"]),
        })
        plan.append({
            "kind": "tenant_signup_completed",
            "slug": t["slug"],
            "signup_source": "demo_seed",
            "assigned_tenant_slug": t["slug"],
            "signup_email": None,
        })
    return plan


__all__ = [
    "DEMO_TENANT_DEFAULTS",
    "build_seed_plan",
]
