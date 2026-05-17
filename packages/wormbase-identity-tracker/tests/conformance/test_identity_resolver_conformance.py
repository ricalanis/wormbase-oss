"""Conformance: _LedgerBackedIdentityResolver IS an IdentityResolver.

Per **C2** the Protocol shape is FROZEN after Wave A landing. This test
pins the conformance: any change to the Protocol that would break
runtime_checkable matching trips this test, blocking the regression.
"""
from __future__ import annotations

from uuid import uuid4

from wormbase_ledger import InMemoryLedger
from wormbase_identity_tracker import IdentityResolver
from wormbase_identity_tracker.resolver import _LedgerBackedIdentityResolver


def test_ledger_backed_resolver_satisfies_protocol() -> None:
    resolver = _LedgerBackedIdentityResolver(
        ledger=InMemoryLedger(), company_id=uuid4(),
    )
    assert isinstance(resolver, IdentityResolver)


def test_resolver_method_names_match_protocol() -> None:
    """The four Protocol method names must be present on the impl."""
    resolver = _LedgerBackedIdentityResolver(
        ledger=InMemoryLedger(), company_id=uuid4(),
    )
    for name in (
        "resolve_platform_id",
        "propose_person",
        "lookup_owner",
        "lookup_team",
    ):
        assert callable(getattr(resolver, name)), (
            f"missing or non-callable method: {name}"
        )
