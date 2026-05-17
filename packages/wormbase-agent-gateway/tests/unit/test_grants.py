"""Unit tests for ``identity/grants.py`` — AgentGrant + status-field consolidation."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from wormbase_agent_gateway.identity import AgentGrant


def _make(**overrides) -> AgentGrant:
    base = {
        "id": str(uuid4()),
        "agent_id": str(uuid4()),
        "grant_kind": "domain.read",
        "grant_target": str(uuid4()),
        "granted_by": str(uuid4()),
        "granted_at": datetime.now(UTC),
    }
    base.update(overrides)
    return AgentGrant.assign(**base)


def test_assign_returns_active_grant() -> None:
    g = _make()
    assert g.status == "active"


def test_revoke_returns_new_grant_with_revoked_status_and_same_id() -> None:
    """Per Addendum 3: ONE entry kind with status field; revoke preserves id."""
    g = _make()
    later = datetime.now(UTC)
    revoked = g.revoke(revoked_at=later)
    # New value, not mutation.
    assert revoked is not g
    assert revoked.id == g.id
    assert revoked.agent_id == g.agent_id
    assert revoked.grant_kind == g.grant_kind
    assert revoked.grant_target == g.grant_target
    assert revoked.granted_by == g.granted_by
    assert revoked.status == "revoked"
    # granted_at carries the revocation timestamp (used by projections to
    # sort by most-recent-state without a separate revoked_at column).
    assert revoked.granted_at == later


def test_grant_is_frozen() -> None:
    g = _make()
    with pytest.raises(FrozenInstanceError):
        g.status = "revoked"  # type: ignore[misc]


def test_model_access_grant_carries_budget() -> None:
    """Per Addendum 3: model.access is the only kind that populates budget."""
    g = _make(
        grant_kind="model.access",
        grant_target="kimi",
        budget_remaining_usd=Decimal("10.00"),
    )
    assert g.grant_kind == "model.access"
    assert g.grant_target == "kimi"
    assert g.budget_remaining_usd == Decimal("10.00")
    # Revoking preserves the budget field too.
    revoked = g.revoke(revoked_at=datetime.now(UTC))
    assert revoked.budget_remaining_usd == Decimal("10.00")
    assert revoked.status == "revoked"
