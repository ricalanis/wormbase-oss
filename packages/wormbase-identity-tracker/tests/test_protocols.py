"""IdentityResolver Protocol shape pin — runtime_checkable."""
from __future__ import annotations

from uuid import UUID, uuid4

from wormbase_identity_tracker.protocols import IdentityResolver
from wormbase_identity_tracker.types import (
    Person,
    PersonHint,
    ProposalRef,
    TeamMembership,
)


class _StubResolver:
    """Minimum surface that should pass isinstance(..., IdentityResolver)."""

    async def resolve_platform_id(
        self, *, platform: str, platform_user_id: str,
    ) -> Person | None:
        return None

    async def propose_person(
        self, hint: PersonHint, *, proposed_by: str,
    ) -> ProposalRef:
        return ProposalRef(person_id=uuid4(), entry_ids=())

    async def lookup_owner(self, topic):  # type: ignore[no-untyped-def]
        return None

    async def lookup_team(self, person_id: UUID) -> list[TeamMembership]:
        return []


def test_identity_resolver_is_runtime_checkable() -> None:
    stub = _StubResolver()
    assert isinstance(stub, IdentityResolver)


def test_identity_resolver_missing_method_fails_isinstance() -> None:
    class _Incomplete:
        async def resolve_platform_id(
            self, *, platform: str, platform_user_id: str,
        ) -> Person | None:
            return None

    assert not isinstance(_Incomplete(), IdentityResolver)
