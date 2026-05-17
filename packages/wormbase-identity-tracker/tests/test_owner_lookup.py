"""Owner lookup tests — moved from apps/worm-core/tests/test_owner_lookup.py.

Identical to the original; only the import path changed:
  - `from wormbase_core.owner_lookup import Person, lookup_owner`
  + `from wormbase_identity_tracker.owner_lookup import Person, lookup_owner`

Topic stays in ``wormbase_core.topic_extractor`` and is imported there.

Resolution order: resource-facet maintainer > domain-facet owner >
resource-facet contributor > domain-facet contributor. Person preferences
opt-out via ``preferences.resource_conversations: false``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from wormbase_identity_tracker.owner_lookup import lookup_owner
from wormbase_core.topic_extractor import Topic


# Stable UUIDs.
DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")
PROCESS_RECOVERY = UUID("cccccccc-0000-0000-0000-000000000001")

CAROL = UUID("eeeeeeee-0000-0000-0000-0000000000c1")
DAVE = UUID("eeeeeeee-0000-0000-0000-0000000000d1")
ADMIN = UUID("00000000-0000-0000-0000-000000000099")


async def _propose_person(ledger, company_id, person_id: UUID, name: str,
                          email: str, platform: str = "slack",
                          platform_user_id: str = "U-x") -> None:
    args = {
        "person_id": str(person_id),
        "tenant_id": str(company_id),
        "name": name,
        "email": email,
        "platform": platform,
        "platform_user_id": platform_user_id,
        "proposed_by": "worm",
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "person_proposed",
                 "ref_id": str(person_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_person_proposed", "args": a,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _domain_role(ledger, company_id, person_id: UUID,
                       domain_id: UUID, role: str) -> None:
    args = {
        "person_id": str(person_id),
        "domain_id": str(domain_id),
        "role": role,
        "granted_by": str(ADMIN),
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "domain_role_assigned",
                 "ref_id": str(domain_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_domain_role_assigned", "args": a,
            "result_ref": str(domain_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _resource_role(ledger, company_id, person_id: UUID,
                         resource_id: UUID, role: str,
                         resource_type: str = "kpi") -> None:
    args = {
        "person_id": str(person_id),
        "resource_id": str(resource_id),
        "resource_type": resource_type,
        "role": role,
        "granted_by": str(ADMIN),
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "resource_role_assigned",
                 "ref_id": str(resource_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_resource_role_assigned", "args": a,
            "result_ref": str(resource_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _set_preferences(ledger, company_id, person_id: UUID,
                           prefs: dict[str, Any]) -> None:
    args = {
        "person_id": str(person_id),
        "preferences": prefs,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "person_preferences",
                 "ref_id": str(person_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "set_person_preferences", "args": a,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


def _kpi_topic() -> Topic:
    return Topic(
        kind="kpi", id=KPI_CHURN, label="churn",
        confidence=0.95, domain_id=DOMAIN_RETENTION,
    )


def _process_topic() -> Topic:
    return Topic(
        kind="process", id=PROCESS_RECOVERY, label="customer recovery flow",
        confidence=0.95, domain_id=None,
    )


# ---------------------------------------------------------------------------
# Domain-facet owner resolution
# ---------------------------------------------------------------------------


async def test_lookup_owner_via_domain_owner_grant(ledger, company_id):
    await _propose_person(ledger, company_id, CAROL, "Carol",
                          "carol@x.com", "slack", "U-CAROL")
    await _domain_role(ledger, company_id, CAROL, DOMAIN_RETENTION, "owner")

    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
    assert person.person_id == CAROL
    assert person.name == "Carol"
    assert person.platform_user_id == "U-CAROL"


async def test_lookup_owner_no_grants_returns_none(ledger, company_id):
    await _propose_person(ledger, company_id, CAROL, "Carol", "carol@x.com")
    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is None


async def test_lookup_owner_domain_contributor_fallback(ledger, company_id):
    """No owner, only contributor — still return them."""
    await _propose_person(ledger, company_id, DAVE, "Dave", "dave@x.com",
                          platform_user_id="U-DAVE")
    await _domain_role(ledger, company_id, DAVE, DOMAIN_RETENTION,
                       "contributor")
    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
    assert person.person_id == DAVE


# ---------------------------------------------------------------------------
# Resource-facet maintainer beats domain owner
# ---------------------------------------------------------------------------


async def test_lookup_owner_resource_maintainer_wins(ledger, company_id):
    """Resource-facet maintainer takes precedence over domain owner."""
    await _propose_person(ledger, company_id, CAROL, "Carol", "carol@x.com",
                          platform_user_id="U-CAROL")
    await _propose_person(ledger, company_id, DAVE, "Dave", "dave@x.com",
                          platform_user_id="U-DAVE")
    await _domain_role(ledger, company_id, CAROL, DOMAIN_RETENTION, "owner")
    await _resource_role(ledger, company_id, DAVE, KPI_CHURN, "maintainer")

    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
    assert person.person_id == DAVE


# ---------------------------------------------------------------------------
# Topic without domain_id — only resource-facet matters
# ---------------------------------------------------------------------------


async def test_lookup_owner_process_topic_no_domain(ledger, company_id):
    """Process topics carry no domain_id (yet); only resource-facet
    grants resolve them."""
    await _propose_person(ledger, company_id, CAROL, "Carol",
                          "c@x.com", platform_user_id="U-CAROL")
    await _resource_role(ledger, company_id, CAROL, PROCESS_RECOVERY,
                         "maintainer", resource_type="process")
    person = await lookup_owner(_process_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
    assert person.person_id == CAROL


# ---------------------------------------------------------------------------
# Person preferences mute
# ---------------------------------------------------------------------------


async def test_lookup_owner_preferences_mute(ledger, company_id):
    """Person.preferences.resource_conversations=False suppresses lookup."""
    await _propose_person(ledger, company_id, CAROL, "Carol",
                          "carol@x.com")
    await _domain_role(ledger, company_id, CAROL, DOMAIN_RETENTION, "owner")
    await _set_preferences(ledger, company_id, CAROL,
                           {"resource_conversations": False})

    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is None


async def test_lookup_owner_preferences_explicit_enable(ledger, company_id):
    """Explicit True doesn't suppress."""
    await _propose_person(ledger, company_id, CAROL, "Carol",
                          "carol@x.com")
    await _domain_role(ledger, company_id, CAROL, DOMAIN_RETENTION, "owner")
    await _set_preferences(ledger, company_id, CAROL,
                           {"resource_conversations": True})

    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
    assert person.person_id == CAROL


async def test_lookup_owner_preferences_default_allows(ledger, company_id):
    """Missing preferences key defaults to allowing."""
    await _propose_person(ledger, company_id, CAROL, "Carol",
                          "carol@x.com")
    await _domain_role(ledger, company_id, CAROL, DOMAIN_RETENTION, "owner")
    person = await lookup_owner(_kpi_topic(),
                                 ledger=ledger, company_id=company_id)
    assert person is not None
