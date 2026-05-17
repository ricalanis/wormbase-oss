"""Lifecycle test — wire_identity_for_install registers + returns resolver."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ReactivityRegistry
from wormbase_identity_tracker import IdentityResolver
from wormbase_identity_tracker.lifecycle import wire_identity_for_install


@dataclass
class _FakeInstall:
    id: object
    platform: str


def fake_lookup(platform: str, user: str) -> dict | None:
    return {"name": user, "email": None}


@pytest.mark.asyncio
async def test_wire_identity_for_install_registers_three_reactivities() -> None:
    """Wave B.5 G.6: factory returns three Reactivities; wire registers all."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = _FakeInstall(id=uuid4(), platform="slack")

    resolver = await wire_identity_for_install(
        install=install,
        member_lookup=fake_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )

    # Resolver satisfies the Protocol.
    assert isinstance(resolver, IdentityResolver)

    # Three Reactivities registered: unknown_platform_id (Wave A) plus
    # position_inference (G.4) and resource_ownership (G.5).
    records = registry.list()
    ids = {r.id for r in records}
    assert "unknown_platform_id" in ids
    assert "position_inference" in ids
    assert "resource_ownership" in ids
    assert len(records) == 3


@pytest.mark.asyncio
async def test_wire_identity_for_install_idempotent_resolver_shape() -> None:
    """Calling wire twice on different installs returns two resolvers; both
    satisfy the Protocol; registry tracks two registrations only if reactivity
    ids differ — but for v1 the id is fixed, so a second wire raises."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install1 = _FakeInstall(id=uuid4(), platform="slack")
    install2 = _FakeInstall(id=uuid4(), platform="discord")

    await wire_identity_for_install(
        install=install1, member_lookup=fake_lookup,
        reactivity_registry=registry, ledger=ledger, company_id=company,
    )

    # Second wire: same reactivity id ("unknown_platform_id") collides
    # with the existing registration. The registry rejects the duplicate.
    with pytest.raises(ValueError, match="already registered"):
        await wire_identity_for_install(
            install=install2, member_lookup=fake_lookup,
            reactivity_registry=registry, ledger=ledger, company_id=company,
        )
