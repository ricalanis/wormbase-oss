"""Tests for the v1.3 Vault-first broker-kind default — Item #3.

The v1.2 default for ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` was ``env``
(deny-by-stub when ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` was also
unset). v1.3 inverts:

* explicit BROKER_KIND wins (back-compat for tests + ops that pin it)
* unset + VAULT_ADDR + VAULT_TOKEN → ``vault`` (production-default flip)
* unset + no Vault env → ``env`` with a loud warning
* unset + no Vault env + no secrets dir → louder warning + stub

The 4 parametrized cases below cover each branch of the resolution
table in ``_resolve_broker_kind_from_env``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

import pytest
from wormbase_core.agent_gateway_construction import (
    _NotYetProductionBrokerExecutor,
    _NotYetProductionFederateIssuer,
    _build_credential_broker_from_env,
    _resolve_broker_kind_from_env,
    compose_production_agent_gateway_deps,
)
from wormbase_ledger import InMemoryLedger

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


def _clear_broker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every env var the resolver reads — establish a clean baseline."""
    for name in (
        "WORMBASE_AGENT_GATEWAY_BROKER_KIND",
        "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR",
        "VAULT_ADDR",
        "VAULT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# _resolve_broker_kind_from_env — 4 branches
# ---------------------------------------------------------------------------


def test_explicit_broker_kind_vault_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``vault`` honored, even with no Vault env."""
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "vault")
    assert _resolve_broker_kind_from_env() == "vault"


def test_explicit_broker_kind_env_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``env`` honored, even with Vault env present."""
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "env")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.invalid")
    monkeypatch.setenv("VAULT_TOKEN", "s.fake")
    assert _resolve_broker_kind_from_env() == "env"


def test_unset_with_vault_env_defaults_to_vault(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unset + VAULT_ADDR + VAULT_TOKEN → ``vault`` (production-default flip)."""
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.invalid")
    monkeypatch.setenv("VAULT_TOKEN", "s.fake")

    caplog.set_level(logging.INFO)
    assert _resolve_broker_kind_from_env() == "vault"
    assert any(
        "defaulting to vault" in record.message for record in caplog.records
    )


def test_unset_without_vault_env_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unset + no Vault env → ``env`` + warning."""
    _clear_broker_env(monkeypatch)
    caplog.set_level(logging.WARNING)
    assert _resolve_broker_kind_from_env() == "env"
    assert any(
        "falling back to 'env'" in record.message for record in caplog.records
    )


def test_unset_with_partial_vault_env_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only one of VAULT_ADDR / VAULT_TOKEN set is not enough → ``env``."""
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("VAULT_ADDR", "https://vault.example.invalid")
    # VAULT_TOKEN absent
    assert _resolve_broker_kind_from_env() == "env"


# ---------------------------------------------------------------------------
# _build_credential_broker_from_env — end-to-end resolution
# ---------------------------------------------------------------------------


def test_build_broker_env_explicit_with_secrets_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Explicit ``env`` + secrets dir → real ``EnvCredentialBroker``."""
    _clear_broker_env(monkeypatch)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "env")
    monkeypatch.setenv(
        "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", str(secrets),
    )

    broker, install_id = _build_credential_broker_from_env()
    assert broker is not None
    assert install_id is None
    # The broker is the file-backed EnvCredentialBroker
    from wormbase_agent_gateway.credential_broker.env import (
        EnvCredentialBroker,
    )
    assert isinstance(broker, EnvCredentialBroker)


def test_build_broker_env_implicit_logs_louder_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unset BROKER_KIND, no Vault env, no secrets dir → louder warning
    PLUS stub fallback.
    """
    _clear_broker_env(monkeypatch)
    caplog.set_level(logging.WARNING)

    broker, install_id = _build_credential_broker_from_env()
    assert broker is None
    # First warning: BROKER_KIND unset + no Vault env.
    # Second warning: 'env' + secrets dir unset.
    messages = [r.message for r in caplog.records]
    assert any("falling back to 'env'" in m for m in messages)
    assert any(
        "no CredentialBroker wired" in m for m in messages
    )


def test_build_broker_vault_explicit_without_env_logs_and_stubs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Explicit ``vault`` but no Vault env → warning + stub."""
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "vault")
    caplog.set_level(logging.WARNING)

    broker, _ = _build_credential_broker_from_env()
    assert broker is None
    assert any(
        "VAULT_ADDR or VAULT_TOKEN is unset" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Integration: compose_production_agent_gateway_deps under each path
# ---------------------------------------------------------------------------


def test_compose_under_default_unset_ships_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env at all → broker stubs + grant-lookup wired anyway.

    The grant lookup is independent of broker resolution (v1.3 Item #1
    vs Item #3), so it's wired even when the broker falls back.
    """
    _clear_broker_env(monkeypatch)
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )
    assert isinstance(deps.broker_executor, _NotYetProductionBrokerExecutor)
    assert isinstance(deps.federate_issuer, _NotYetProductionFederateIssuer)
    # grant_lookup is the v1.3 closure, NOT _empty_grant_lookup
    from wormbase_core.agent_gateway_construction import (
        _empty_grant_lookup,
    )
    assert deps.grant_lookup is not _empty_grant_lookup
