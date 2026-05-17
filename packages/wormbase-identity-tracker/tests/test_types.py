"""Value-type construction + frozen-ness checks."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_identity_tracker.types import (
    Person,
    PersonHint,
    Position,
    ProposalRef,
    ResourceRole,
    TeamMembership,
)


def test_person_is_frozen_dataclass_with_six_fields() -> None:
    p = Person(person_id=uuid4(), name="Alice")
    assert p.email is None
    assert p.platform is None
    assert p.platform_user_id is None
    assert p.preferences == {}
    with pytest.raises(Exception):  # frozen
        p.name = "Bob"  # type: ignore[misc]


def test_person_hint_required_fields() -> None:
    h = PersonHint(
        platform="slack",
        platform_user_id="U123",
        name="Alice",
    )
    assert h.email is None
    assert h.position is None


def test_proposal_ref_carries_person_id_and_entry_ids() -> None:
    pid = uuid4()
    eids = (uuid4(), uuid4(), uuid4(), uuid4())
    ref = ProposalRef(person_id=pid, entry_ids=eids)
    assert ref.person_id == pid
    assert len(ref.entry_ids) == 4
    # Frozen
    with pytest.raises(Exception):
        ref.person_id = uuid4()  # type: ignore[misc]


def test_team_membership_carries_role_and_granted_at() -> None:
    tid = uuid4()
    ts = datetime.now(UTC)
    m = TeamMembership(team_id=tid, role="owner", granted_at=ts)
    assert m.team_id == tid
    assert m.role == "owner"
    assert m.granted_at == ts


def test_team_membership_granted_at_optional() -> None:
    m = TeamMembership(team_id=uuid4(), role="contributor")
    assert m.granted_at is None


# ---------------------------------------------------------------------------
# Position — Wave B.5 G.2
# ---------------------------------------------------------------------------


def test_position_dataclass_shape() -> None:
    """Plan-spec shape: name + confidence + signals tuple."""
    p = Position(name="senior_engineer", confidence=0.7, signals=("commit_msg",))
    assert p.name == "senior_engineer"
    assert p.confidence == 0.7
    assert p.signals == ("commit_msg",)


def test_position_signals_default_empty() -> None:
    p = Position(name="analyst", confidence=0.5)
    assert p.signals == ()


def test_position_is_frozen() -> None:
    p = Position(name="ic", confidence=0.5)
    with pytest.raises(Exception):  # frozen
        p.name = "manager"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ResourceRole — Wave B.5 G.2
# ---------------------------------------------------------------------------


def test_resource_role_dataclass_shape() -> None:
    """Plan-spec shape: person_id + resource_id + role + confidence."""
    pid = uuid4()
    rid = uuid4()
    rr = ResourceRole(
        person_id=pid,
        resource_id=rid,
        role="maintainer",
        confidence=0.8,
    )
    assert rr.person_id == pid
    assert rr.resource_id == rid
    assert rr.role == "maintainer"
    assert rr.confidence == 0.8
    assert rr.signals == ()


def test_resource_role_with_signals() -> None:
    rr = ResourceRole(
        person_id=uuid4(),
        resource_id=uuid4(),
        role="maintainer",
        confidence=0.9,
        signals=("chat_mention", "data_product_consumed"),
    )
    assert rr.signals == ("chat_mention", "data_product_consumed")


def test_resource_role_is_frozen() -> None:
    rr = ResourceRole(
        person_id=uuid4(),
        resource_id=uuid4(),
        role="maintainer",
        confidence=0.5,
    )
    with pytest.raises(Exception):  # frozen
        rr.role = "contributor"  # type: ignore[misc]
