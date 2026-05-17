"""Tests for ``AgentMetadataUpdatedPayload`` — final wave item #5 (2026-05-13).

Pins the new ledger entry kind that backs the agent detail page's Edit
modal:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* ``display_name`` / ``description`` are optional (``None`` = unchanged);
  the agent detail page's fold honors None as "no change at this entry".
* ``updated_by_person_id`` is required (admin person who performed the
  edit; defense-in-depth admin enforcement lives in the dashboard server
  action AND the HTTP endpoint).
* ``reason`` is optional free-text audit prose.

KIND_REGISTRY grew 103 → 104 (additive per schema-evolution doctrine
Rule 2; under the 120-kind Wave F Addendum 1 ceiling). The agent's
identity (agent_id, person_id, external_provider) remains immutable —
only the human-readable surface mutates through this entry. To revoke an
agent, use ``agent_grant`` status=revoked (Path 5). To change operational
fields (kind, scopes), revoke + re-register.
"""
from __future__ import annotations

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    AgentMetadataUpdatedPayload,
)


def test_agent_metadata_updated_kind_registered() -> None:
    """Auto-registration via EntryPayload.__init_subclass__ — the kind
    appears in ``KIND_REGISTRY`` and maps back to the payload class."""
    assert "agent_metadata_updated" in KIND_REGISTRY
    assert KIND_REGISTRY["agent_metadata_updated"] is AgentMetadataUpdatedPayload


def test_agent_metadata_updated_roundtrip_full_fields() -> None:
    """All fields populated round-trip byte-equivalently via model_dump
    → model_validate."""
    p = AgentMetadataUpdatedPayload(
        agent_id="agent-uuid-1",
        display_name="Kimi DS Agent",
        description="Daily DS-agent for finance + product teams.",
        updated_by_person_id="admin-person-uuid",
        reason="rebrand for clarity post-onboarding",
    )
    assert AgentMetadataUpdatedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "agent_metadata_updated"


def test_agent_metadata_updated_display_name_only() -> None:
    """``description=None`` is honored as 'no change to description' on
    the fold side — the payload still validates without it."""
    p = AgentMetadataUpdatedPayload(
        agent_id="agent-uuid-2",
        display_name="Renamed Agent",
        updated_by_person_id="admin-person-uuid",
    )
    assert p.description is None
    assert p.reason is None
    # Round-trip should preserve the None vs absent semantics.
    assert AgentMetadataUpdatedPayload.model_validate(p.model_dump()) == p


def test_agent_metadata_updated_description_only() -> None:
    """``display_name=None`` for a description-only update — preserves
    status-consolidation: one kind handles either field independently."""
    p = AgentMetadataUpdatedPayload(
        agent_id="agent-uuid-3",
        description="Updated charter: now also covers compliance.",
        updated_by_person_id="admin-person-uuid",
        reason="quarterly scope review",
    )
    assert p.display_name is None
    assert p.description == "Updated charter: now also covers compliance."
    assert AgentMetadataUpdatedPayload.model_validate(p.model_dump()) == p


def test_agent_metadata_updated_requires_updated_by_person_id() -> None:
    """``updated_by_person_id`` is required — without it, validation fails.
    Defense in depth: the admin role check lives on the dashboard server
    action AND the HTTP endpoint; this is the ledger-side belt+braces."""
    with pytest.raises(Exception):
        AgentMetadataUpdatedPayload(  # type: ignore[call-arg]
            agent_id="agent-uuid-4",
            display_name="Some Name",
            # updated_by_person_id missing
        )


def test_agent_metadata_updated_both_fields_none_still_validates() -> None:
    """Both display_name and description ``None`` is a degenerate but
    valid payload — the dashboard server action rejects it earlier (form
    validation: at least one must differ from current), but the ledger
    accepts it as a metadata audit-only entry. Keeps the kind purely
    additive and avoids a server-side schema-level rejection that would
    couple the entry shape to dashboard form rules."""
    p = AgentMetadataUpdatedPayload(
        agent_id="agent-uuid-5",
        updated_by_person_id="admin-person-uuid",
        reason="metadata audit checkpoint",
    )
    assert p.display_name is None
    assert p.description is None
    assert AgentMetadataUpdatedPayload.model_validate(p.model_dump()) == p
