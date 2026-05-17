"""Agent identity, grants, agent_query PEVR helper, and credential lifecycle.

Per Wave 2 Task 5. Public surface:

- :class:`Agent` — Person sub-type carrying external_provider + display_name
- :class:`AgentGrant` — per-agent data/model grant with active/revoked status
- :func:`agent_query_pevr` — wraps ``Ledger.write`` into a single-kind 4-phase
  cycle (per doctrine Addendum 3)
- :func:`issue_data_credential` / :func:`issue_model_credential` /
  :func:`revoke_credential` — credential broker delegation + ledger emission
"""
from __future__ import annotations

from .agent import Agent, AgentID, AgentProvider
from .audit import agent_query_pevr
from .credential import (
    issue_data_credential,
    issue_model_credential,
    revoke_credential,
)
from .grants import AgentGrant, GrantKind

__all__ = [
    "Agent",
    "AgentGrant",
    "AgentID",
    "AgentProvider",
    "GrantKind",
    "agent_query_pevr",
    "issue_data_credential",
    "issue_model_credential",
    "revoke_credential",
]
