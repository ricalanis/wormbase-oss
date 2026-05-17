"""Pinned-mirror equivalence test for the WhatsApp bot-phone env resolver.

Phase F1 (2026-05-06) consolidated the env-var resolution for the
WhatsApp bot phone into a single precedence chain, with the function
deliberately duplicated in two packages per CLAUDE.md §1.5 rule 3
(no package-to-package imports). The two homes:

* ``wormbase_chat_presence.predicates.resolve_whatsapp_bot_phone``
  — used by ``MentionsWorm._match_whatsapp``.
* ``wormbase_channel_adapters.whatsapp.resolve_whatsapp_bot_phone``
  — used by ``WhatsAppChannelAdapter._resolve_bot_jid_for_tenant`` and
  ``WhatsAppChannelAdapter._resolve_bot_phone_for_rate_limit``.

Both must yield BYTE-IDENTICAL results for the same inputs. This file
asserts that across the precedence cases below; if the resolvers ever
drift, this test fails and the agent must consciously reconcile both
sites (or hoist into a shared module — but per CLAUDE.md §1.5 rule 3
that requires re-arguing the package boundary, not silently sliding it).

Per the Schema-Evolution Doctrine Rule 2 spirit (pinned mirrors over
silent drift), the test exists as the contract, not the convention.

Precedence pinned (returning first non-empty match, '+' stripped):

  1. WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>   (when tenant_id given)
  2. WORMBASE_WHATSAPP_BOT_PHONE_<COMPANY_UPPER>  (when company_id given)
  3. WORMBASE_WHATSAPP_BOT_PHONE                  (single-tenant fallback)

Both UUID-suffix and tenant-slug-suffix forms supported simultaneously
via the precedence chain — operators may set ONE or BOTH; both work.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_channel_adapters.whatsapp import (
    resolve_whatsapp_bot_phone as resolver_channel_adapter,
)
from wormbase_chat_presence.predicates import (
    resolve_whatsapp_bot_phone as resolver_chat_presence,
)


_TENANT = "tenant_x"
_COMPANY = UUID("12345678-1234-1234-1234-123456789abc")
_TENANT_PHONE = "15551112222"
_COMPANY_PHONE = "15553334444"
_GLOBAL_PHONE = "15555556666"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any pre-existing WORMBASE_WHATSAPP_BOT_PHONE* env vars per-test.

    Any test in this suite that needs an env value sets it explicitly via
    monkeypatch. Prevents bleed from adjacent tests that may have set
    different conventions.
    """
    import os

    for name in list(os.environ.keys()):
        if name.startswith("WORMBASE_WHATSAPP_BOT_PHONE"):
            monkeypatch.delenv(name, raising=False)


def _assert_resolvers_agree(
    *,
    tenant_id: str | None = None,
    company_id: str | UUID | None = None,
    expected: str | None,
) -> None:
    """Both resolvers must return the same value for the same inputs.

    Run them in a deterministic order (chat-presence first, then
    channel-adapter) and compare; failure messages name the divergence
    clearly so a future drift is easy to triage.
    """
    chat = resolver_chat_presence(
        tenant_id=tenant_id, company_id=company_id,
    )
    adapter = resolver_channel_adapter(
        tenant_id=tenant_id, company_id=company_id,
    )
    assert chat == adapter, (
        f"resolver drift: chat-presence={chat!r}, "
        f"channel-adapter={adapter!r} for "
        f"(tenant_id={tenant_id!r}, company_id={company_id!r})"
    )
    assert chat == expected, (
        f"unexpected value: got {chat!r}, expected {expected!r} for "
        f"(tenant_id={tenant_id!r}, company_id={company_id!r})"
    )


# ---------------------------------------------------------------------------
# Single-tenant fallback (no-suffix env)
# ---------------------------------------------------------------------------


def test_no_envs_set_returns_none() -> None:
    """All three env vars unset → both resolvers return None."""
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=None,
    )


def test_only_no_suffix_env_set_returns_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-tenant deployment shape: only WORMBASE_WHATSAPP_BOT_PHONE set."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _GLOBAL_PHONE)
    # No tenant or company → still resolves via fallback.
    _assert_resolvers_agree(expected=_GLOBAL_PHONE)
    # Tenant given but tenant-suffix env unset → falls through to global.
    _assert_resolvers_agree(tenant_id=_TENANT, expected=_GLOBAL_PHONE)
    # Company given but company-suffix env unset → falls through to global.
    _assert_resolvers_agree(company_id=_COMPANY, expected=_GLOBAL_PHONE)
    # Both given but only no-suffix set → falls through to global.
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=_GLOBAL_PHONE,
    )


# ---------------------------------------------------------------------------
# Tenant-suffix takes precedence (path 1)
# ---------------------------------------------------------------------------


def test_tenant_suffix_wins_over_company_and_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant-suffix env present → wins over company-suffix and no-suffix."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _TENANT_PHONE,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}", _COMPANY_PHONE,
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _GLOBAL_PHONE)
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=_TENANT_PHONE,
    )


def test_tenant_suffix_only_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant-only multi-tenant deployment — only path (1) populated."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _TENANT_PHONE,
    )
    _assert_resolvers_agree(tenant_id=_TENANT, expected=_TENANT_PHONE)
    # Company alone → tenant-suffix not consulted, no other env set → None.
    _assert_resolvers_agree(company_id=_COMPANY, expected=None)


# ---------------------------------------------------------------------------
# Company-suffix middle slot (path 2)
# ---------------------------------------------------------------------------


def test_company_suffix_wins_over_global_when_no_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant unset, company set, global set → company-suffix wins."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}", _COMPANY_PHONE,
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _GLOBAL_PHONE)
    _assert_resolvers_agree(company_id=_COMPANY, expected=_COMPANY_PHONE)
    # Tenant + company both given, only company-suffix set → company wins
    # because tenant-suffix env-var is unset.
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=_COMPANY_PHONE,
    )


def test_company_suffix_preserves_dashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1 convention pin: UUID-suffix env var keeps dashes (not stripped).

    The existing predicate before F1 used ``str(company_id).upper()``,
    which preserves dashes. Tests like ``test_whatsapp_mention_e2e.py``
    set ``WORMBASE_WHATSAPP_BOT_PHONE_<UUID-WITH-DASHES-UPPER>``, and
    F1 must NOT silently rotate to a dashes-stripped convention.
    """
    dashes_key = f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}"
    assert "-" in dashes_key  # sanity: this is what the convention pins
    monkeypatch.setenv(dashes_key, _COMPANY_PHONE)
    # The dashes-stripped variant should NOT be consulted (back-compat).
    no_dashes_key = (
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper().replace('-', '')}"
    )
    assert "-" not in no_dashes_key
    monkeypatch.setenv(no_dashes_key, "wrongphone")
    _assert_resolvers_agree(company_id=_COMPANY, expected=_COMPANY_PHONE)


# ---------------------------------------------------------------------------
# Edge cases — leading '+' stripping, dual-set, and empty values
# ---------------------------------------------------------------------------


def test_plus_prefix_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators sometimes set the env with a leading '+'; resolver strips it."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", f"+{_GLOBAL_PHONE}")
    _assert_resolvers_agree(expected=_GLOBAL_PHONE)
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}",
        f"+{_TENANT_PHONE}",
    )
    _assert_resolvers_agree(tenant_id=_TENANT, expected=_TENANT_PHONE)


def test_whitespace_only_value_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env set to '   +  ' (or just whitespace) is treated as unset."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", "   +  ",
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _GLOBAL_PHONE)
    # Tenant value is whitespace-after-strip → falls through to global.
    _assert_resolvers_agree(tenant_id=_TENANT, expected=_GLOBAL_PHONE)


def test_dual_set_tenant_and_company_tenant_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing dual-set tests (B1.1 / E4) set BOTH conventions for the
    SAME tenant. Resolver must pick tenant-suffix per precedence —
    the dual-set is back-compat, not contradictory.

    When both refer to the same tenant, both env values are typically the
    same phone number. This test pins the case where they diverge so the
    precedence is unambiguous.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _TENANT_PHONE,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}", _COMPANY_PHONE,
    )
    # Tenant-suffix wins over company-suffix per precedence chain.
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=_TENANT_PHONE,
    )


def test_empty_string_envs_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty-string env vars fall through to the next precedence level."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", "",
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}", "",
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _GLOBAL_PHONE)
    _assert_resolvers_agree(
        tenant_id=_TENANT, company_id=_COMPANY, expected=_GLOBAL_PHONE,
    )


def test_company_id_accepts_string_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``company_id`` accepts either ``UUID`` or ``str``; both resolve same env."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_COMPANY).upper()}", _COMPANY_PHONE,
    )
    _assert_resolvers_agree(company_id=_COMPANY, expected=_COMPANY_PHONE)
    _assert_resolvers_agree(company_id=str(_COMPANY), expected=_COMPANY_PHONE)
