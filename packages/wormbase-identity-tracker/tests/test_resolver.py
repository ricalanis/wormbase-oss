"""Resolver implementation tests — composes lifted modules.

Each Protocol method gets a focused test that asserts the resolver
correctly delegates to the underlying lifted helper / write_action.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_identity_tracker.resolver import _LedgerBackedIdentityResolver
from wormbase_identity_tracker.types import PersonHint
from wormbase_core.topic_extractor import Topic


@pytest.mark.asyncio
async def test_resolve_platform_id_returns_none_when_unknown() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    resolver = _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company,
    )
    person = await resolver.resolve_platform_id(
        platform="slack", platform_user_id="U999",
    )
    assert person is None


@pytest.mark.asyncio
async def test_resolve_platform_id_returns_person_after_propose() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    resolver = _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company,
    )
    hint = PersonHint(
        platform="slack",
        platform_user_id="U123",
        name="Alice",
        email="alice@example.com",
    )
    ref = await resolver.propose_person(hint, proposed_by="worm")
    assert ref.person_id is not None
    assert len(ref.entry_ids) == 4

    # Now resolve_platform_id should find Alice.
    person = await resolver.resolve_platform_id(
        platform="slack", platform_user_id="U123",
    )
    assert person is not None
    assert person.name == "Alice"
    assert person.email == "alice@example.com"
    assert person.platform == "slack"


@pytest.mark.asyncio
async def test_lookup_owner_delegates_to_owner_lookup() -> None:
    """Smoke test: when no owner has been granted, returns None."""
    company = uuid4()
    ledger = InMemoryLedger()
    resolver = _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company,
    )
    topic = Topic(
        kind="kpi",
        id=uuid4(),
        label="churn",
        confidence=0.9,
        domain_id=uuid4(),
    )
    owner = await resolver.lookup_owner(topic)
    assert owner is None


@pytest.mark.asyncio
async def test_lookup_team_returns_empty_when_no_domain_grants() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    resolver = _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company,
    )
    teams = await resolver.lookup_team(person_id=uuid4())
    assert teams == []


@pytest.mark.asyncio
async def test_propose_person_threads_proposed_by() -> None:
    """Custom proposed_by string is preserved in the ledger entry."""
    company = uuid4()
    ledger = InMemoryLedger()
    resolver = _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company,
    )
    hint = PersonHint(
        platform="slack", platform_user_id="U777",
        name="Bob",
    )
    admin_uuid = str(uuid4())
    await resolver.propose_person(hint, proposed_by=admin_uuid)

    rows = await ledger.fetch(company)
    propose_rows = [r for r in rows if r["kind"] == "propose"]
    assert any(
        r["payload"].get("proposed_by") == admin_uuid
        for r in propose_rows
    )
