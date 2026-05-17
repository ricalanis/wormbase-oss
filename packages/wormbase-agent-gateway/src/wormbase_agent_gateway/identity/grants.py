"""agent_grant model — covers BOTH data grants and model grants.

Per doctrine Addendum 3: ONE entry kind (``agent_grant``) with a status field
for active/revoked (no separate ``agent_grant_revoked`` kind). The grant axis
distinguishes data vs model via :data:`GrantKind`:

- ``domain.read`` / ``resource.read`` / ``resource.maintainer`` — data grants
- ``model.access`` — model grant; only kind that carries
  ``budget_remaining_usd``

Revocation produces a NEW frozen grant (preserves id) rather than mutating
the original — keeps the value-type contract sound.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal


GrantKind = Literal[
    "domain.read",
    "resource.read",
    "resource.maintainer",
    "model.access",
]


@dataclass(frozen=True)
class AgentGrant:
    """Per-agent grant. status="active" on assign; status="revoked" on revoke.

    ``grant_target`` semantics depend on ``grant_kind``:

    - ``domain.read``         → domain UUID
    - ``resource.read``       → resource UUID
    - ``resource.maintainer`` → resource UUID
    - ``model.access``        → model_kind string (e.g. ``"kimi"`` / ``"gemma"``)

    ``budget_remaining_usd`` is populated only for ``model.access`` grants;
    other kinds leave it ``None``.
    """

    id: str
    agent_id: str
    grant_kind: GrantKind
    grant_target: str
    status: Literal["active", "revoked"]
    granted_by: str
    granted_at: datetime
    budget_remaining_usd: Decimal | None = None

    @classmethod
    def assign(
        cls,
        *,
        id: str,
        agent_id: str,
        grant_kind: GrantKind,
        grant_target: str,
        granted_by: str,
        granted_at: datetime,
        budget_remaining_usd: Decimal | None = None,
    ) -> "AgentGrant":
        """Factory — creates a new grant with status="active"."""
        return cls(
            id=id,
            agent_id=agent_id,
            grant_kind=grant_kind,
            grant_target=grant_target,
            status="active",
            granted_by=granted_by,
            granted_at=granted_at,
            budget_remaining_usd=budget_remaining_usd,
        )

    def revoke(self, *, revoked_at: datetime) -> "AgentGrant":
        """Return a NEW grant with status="revoked"; preserves id + axis.

        The ``granted_at`` field is repurposed as the most-recent-state
        timestamp so projections can sort by it without tracking a
        separate ``revoked_at`` column. ``id`` is preserved so projections
        upsert in place.
        """
        return replace(self, status="revoked", granted_at=revoked_at)


__all__ = ["AgentGrant", "GrantKind"]
