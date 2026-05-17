"""Agent identity — a Person sub-type for external + internal agents.

Per Wave 2 plan §Task 5 Step 1: ``Agent`` shares the Person id (1:1 in v1) and
adds ``external_provider`` + agent-specific metadata. The factory returns a
frozen dataclass; the caller is responsible for writing the
``agent_registered`` ledger entry via :func:`agent_query_pevr` (or a direct
``Ledger.write``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# Re-use AgentID from inference-router rather than redefining (single source
# of truth — see Wave 2 Task 4 for the boundary-convert design).
from wormbase_inference import AgentID  # noqa: F401  — re-exported


AgentProvider = Literal["claude", "openai", "kimi", "internal_worm", "other"]


@dataclass(frozen=True)
class Agent:
    """Person sub-type carrying external_provider + display_name.

    In v1 ``id == person_id`` (one-to-one mapping); the duplication exists so
    downstream code can treat ``Agent`` as a Person-shaped record without
    relitigating identity.
    """

    id: str  # UUID — same as Person.id (one-to-one in v1)
    company_id: str
    person_id: str
    external_provider: AgentProvider
    display_name: str
    registered_at: datetime
    registered_by: str  # admin Person UUID
    status: Literal["active", "inactive"] = "active"

    @classmethod
    def register(
        cls,
        *,
        person_id: str,
        company_id: str,
        external_provider: AgentProvider,
        display_name: str,
        registered_by: str,
        registered_at: datetime,
    ) -> "Agent":
        """Factory — creates a new Agent.

        Caller writes the ``agent_registered`` ledger entry via
        ``Ledger.write`` after the dataclass is built. Splitting the
        construction from the emission keeps this module synchronous and
        cheap to unit-test.
        """
        return cls(
            id=person_id,  # 1:1 with person_id in v1
            company_id=company_id,
            person_id=person_id,
            external_provider=external_provider,
            display_name=display_name,
            registered_at=registered_at,
            registered_by=registered_by,
        )


__all__ = ["Agent", "AgentID", "AgentProvider"]
