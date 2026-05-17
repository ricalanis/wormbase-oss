"""Unit tests for ``identity/agent.py`` — Agent dataclass + register factory."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_agent_gateway.identity import Agent, AgentID


def test_register_creates_agent_with_person_id_1to1() -> None:
    """v1 contract: Agent.id == Agent.person_id."""
    pid = str(uuid4())
    cid = str(uuid4())
    admin = str(uuid4())
    now = datetime.now(UTC)
    a = Agent.register(
        person_id=pid,
        company_id=cid,
        external_provider="claude",
        display_name="Claude Research Agent",
        registered_by=admin,
        registered_at=now,
    )
    assert a.id == pid
    assert a.person_id == pid
    assert a.company_id == cid
    assert a.external_provider == "claude"
    assert a.display_name == "Claude Research Agent"
    assert a.registered_by == admin
    assert a.registered_at == now
    assert a.status == "active"


def test_register_supports_all_external_providers() -> None:
    """All five literal providers construct cleanly."""
    pid = str(uuid4())
    cid = str(uuid4())
    admin = str(uuid4())
    now = datetime.now(UTC)
    for provider in ("claude", "openai", "kimi", "internal_worm", "other"):
        a = Agent.register(
            person_id=pid,
            company_id=cid,
            external_provider=provider,  # type: ignore[arg-type]
            display_name="x",
            registered_by=admin,
            registered_at=now,
        )
        assert a.external_provider == provider


def test_agent_is_frozen() -> None:
    """Agent is a frozen dataclass — mutation raises."""
    a = Agent.register(
        person_id=str(uuid4()),
        company_id=str(uuid4()),
        external_provider="claude",
        display_name="x",
        registered_by=str(uuid4()),
        registered_at=datetime.now(UTC),
    )
    with pytest.raises(FrozenInstanceError):
        a.display_name = "mutated"  # type: ignore[misc]


def test_agent_id_reexport_matches_inference_router() -> None:
    """AgentID re-exported from identity module is the inference-router type."""
    from wormbase_inference import AgentID as InferenceAgentID

    assert AgentID is InferenceAgentID
    # And the from_legacy_string boundary-convert still works through the re-export.
    aid = AgentID.from_legacy_string("agent-uuid-1")
    assert aid.value == "agent-uuid-1"
