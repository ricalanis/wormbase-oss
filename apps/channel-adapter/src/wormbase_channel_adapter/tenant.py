"""Tenant slug → ``company_id`` UUID resolution.

Wave-2C MVP hardcodes the tenant slug to ``"baseworm"`` (the demo Slack
workspace). The ledger stores ``company_id`` as a UUID, so we derive a
*stable* UUIDv5 from the slug under a fixed namespace. Same slug → same
UUID across restarts and machines, which means downstream services
(worm-core, dashboard) can pin queries to the same ID without a separate
mapping table.

Multi-tenant routing (parse session metadata to pick the right tenant) is
v1.1; the parser already exposes ``conversation_label`` / ``group_space``
for that future hook.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# Stable namespace UUID for the wormbase project. Generated once via
# ``uuid.uuid4()`` and frozen here on purpose — this value is part of the
# public contract: every consumer that wants to look up baseworm by slug
# MUST resolve through this namespace.
WORMBASE_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def tenant_to_company_uuid(slug: str) -> UUID:
    """Map a tenant slug (e.g. ``"baseworm"``) to a stable UUID.

    The result is deterministic: ``tenant_to_company_uuid("baseworm")``
    always returns the same UUID. Different slugs produce different UUIDs.
    """
    if not slug:
        raise ValueError("tenant slug must be non-empty")
    return uuid5(WORMBASE_TENANT_NAMESPACE, slug.strip().lower())
