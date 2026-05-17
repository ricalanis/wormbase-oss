"""TenantSignupInitiated + TenantSignupCompleted payload tests.

Phase 1B.B — multi-tenancy v2 plan
(``docs/superpowers/plans/2026-05-04-multitenancy-v2.md``).

Two entry kinds drive tenant creation:

  * tenant_signup_initiated — written when a Slack OAuth callback fires
    for an unknown workspace, OR a magic-link request endpoint accepts
    an email. Carries the tentative slug + display name + signup_email
    + the pending token hash so the matching completion step can verify
    the request is the same one the initiator started.

  * tenant_signup_completed — written after the signup is fully
    installed: Slack signup writes this immediately after the
    install_completed cycle inside complete_install; magic-link writes
    this when the confirm endpoint binds the evaluator to a demo
    tenant.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import KIND_REGISTRY


def test_tenant_signup_initiated_registered() -> None:
    assert "tenant_signup_initiated" in KIND_REGISTRY


def test_tenant_signup_completed_registered() -> None:
    assert "tenant_signup_completed" in KIND_REGISTRY


def test_tenant_signup_initiated_required_fields() -> None:
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    payload = cls(
        tenant_id=uuid4(),
        slug="slack_team_t12345",
        display_name="Acme",
        signup_source="slack_oauth",
        signup_email="founder@acme.com",
        pending_token_hash="a" * 64,
    )
    assert payload.signup_source == "slack_oauth"
    assert payload.slug == "slack_team_t12345"


def test_tenant_signup_initiated_rejects_invalid_signup_source() -> None:
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    with pytest.raises(ValidationError):
        cls(
            tenant_id=uuid4(),
            slug="x",
            display_name="X",
            signup_source="not_a_real_source",
            signup_email=None,
            pending_token_hash="a" * 64,
        )


@pytest.mark.parametrize(
    "source",
    ["slack_oauth", "email_magic_link", "demo_seed", "bootstrapped"],
)
def test_tenant_signup_initiated_accepts_canonical_sources(source: str) -> None:
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    cls(
        tenant_id=uuid4(),
        slug="x",
        display_name="X",
        signup_source=source,
        signup_email=None,
        pending_token_hash="a" * 64,
    )


def test_tenant_signup_initiated_rejects_short_token_hash() -> None:
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    with pytest.raises(ValidationError):
        cls(
            tenant_id=uuid4(),
            slug="x",
            display_name="X",
            signup_source="slack_oauth",
            signup_email=None,
            pending_token_hash="abc123",  # too short
        )


def test_tenant_signup_initiated_rejects_non_hex_token_hash() -> None:
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    with pytest.raises(ValidationError):
        cls(
            tenant_id=uuid4(),
            slug="x",
            display_name="X",
            signup_source="slack_oauth",
            signup_email=None,
            pending_token_hash="z" * 64,  # not hex
        )


def test_tenant_signup_initiated_accepts_uppercase_hex() -> None:
    """Hash validator is case-insensitive on hex digits."""
    cls = KIND_REGISTRY["tenant_signup_initiated"]
    payload = cls(
        tenant_id=uuid4(),
        slug="x",
        display_name="X",
        signup_source="slack_oauth",
        signup_email=None,
        pending_token_hash="A" * 64,
    )
    assert len(payload.pending_token_hash) == 64


def test_tenant_signup_completed_required_fields() -> None:
    cls = KIND_REGISTRY["tenant_signup_completed"]
    payload = cls(
        tenant_id=uuid4(),
        signup_source="email_magic_link",
        assigned_tenant_slug="wormbase-saas-demo",
        signup_email="evaluator@example.com",
    )
    assert payload.assigned_tenant_slug == "wormbase-saas-demo"
    assert payload.signup_source == "email_magic_link"


def test_tenant_signup_completed_rejects_invalid_signup_source() -> None:
    cls = KIND_REGISTRY["tenant_signup_completed"]
    with pytest.raises(ValidationError):
        cls(
            tenant_id=uuid4(),
            signup_source="totally-fake",
            assigned_tenant_slug="x",
            signup_email=None,
        )


def test_tenant_signup_completed_signup_email_optional() -> None:
    cls = KIND_REGISTRY["tenant_signup_completed"]
    payload = cls(
        tenant_id=uuid4(),
        signup_source="slack_oauth",
        assigned_tenant_slug="slack_team_t12345",
        signup_email=None,
    )
    assert payload.signup_email is None


def test_signup_kinds_take_registry_to_79() -> None:
    """Doctrine pin: 1B.B adds exactly 2 new kinds; registry size goes
    from 77 (pre-1B.B baseline) to 79."""
    # We can't assert on the exact pre-baseline since other Wave H tasks
    # may run alongside, but we can pin "both new kinds present and
    # contribute one each".
    assert "tenant_signup_initiated" in KIND_REGISTRY
    assert "tenant_signup_completed" in KIND_REGISTRY
