"""LazyWebhookSecretResolver — v1.4 #3 close-out of the v2.A webhook gap.

These tests pin the lazy-resolve contract: ``env://`` refs work without
a broker, ``vault://`` refs require a broker bound after the dispatcher
has been composed, the binding is observable on the same singleton the
dispatcher holds (so deliveries pick the broker up at call time), and
the v2.A placeholder behavior is gone (the resolver no longer always
raises on construction).

Additionally pins the integration contract: when the CLI composes
SubscriptionDispatcherDeps, the resolved WebhookTransport's
secret_resolver IS the lazy resolver — not a placeholder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_core.webhook_secret_resolver import (
    LazyWebhookSecretResolver,
    get_or_create_lazy_webhook_resolver,
    reset_lazy_webhook_resolver_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Each test starts with a fresh singleton."""
    reset_lazy_webhook_resolver_for_tests()
    yield
    reset_lazy_webhook_resolver_for_tests()


# ---------------------------------------------------------------------------
# env:// scheme — works without a broker.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_scheme_resolves_without_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_TEST_WEBHOOK_SECRET", "shh-it-is-a-secret")
    resolver = LazyWebhookSecretResolver()
    assert not resolver.is_bound
    secret = await resolver("env://WORMBASE_TEST_WEBHOOK_SECRET")
    assert secret == "shh-it-is-a-secret"


@pytest.mark.asyncio
async def test_env_scheme_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_TEST_NONEXISTENT", raising=False)
    resolver = LazyWebhookSecretResolver()
    with pytest.raises(RuntimeError, match="env://.* missing"):
        await resolver("env://WORMBASE_TEST_NONEXISTENT")


# ---------------------------------------------------------------------------
# vault:// scheme — requires a bound broker; resolves through the broker.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vault_scheme_without_broker_raises_clear_error() -> None:
    resolver = LazyWebhookSecretResolver()
    with pytest.raises(RuntimeError, match="vault://.* requires a CredentialBroker"):
        await resolver("vault://wormbase/webhook-secret")


@pytest.mark.asyncio
async def test_vault_scheme_resolves_through_env_broker(tmp_path: Path) -> None:
    """Bind an EnvCredentialBroker; vault:// path reads from its file-store."""
    from wormbase_agent_gateway.credential_broker.env import EnvCredentialBroker

    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    await broker.put_secret(
        "wormbase/webhook-secret",
        {"secret": "the-shared-hmac-key"},
    )
    resolver = LazyWebhookSecretResolver()
    resolver.bind_broker(broker)
    assert resolver.is_bound
    assert resolver.broker_kind == "env"

    secret = await resolver("vault://wormbase/webhook-secret")
    assert secret == "the-shared-hmac-key"


@pytest.mark.asyncio
async def test_vault_scheme_missing_path_raises(tmp_path: Path) -> None:
    from wormbase_agent_gateway.credential_broker.env import EnvCredentialBroker

    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    resolver = LazyWebhookSecretResolver()
    resolver.bind_broker(broker)
    with pytest.raises(RuntimeError, match="no secret at vault://"):
        await resolver("vault://does/not/exist")


@pytest.mark.asyncio
async def test_vault_scheme_payload_missing_secret_key_raises(
    tmp_path: Path,
) -> None:
    from wormbase_agent_gateway.credential_broker.env import EnvCredentialBroker

    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    await broker.put_secret(
        "wormbase/wrong-shape",
        {"value": "not-under-secret-key"},
    )
    resolver = LazyWebhookSecretResolver()
    resolver.bind_broker(broker)
    with pytest.raises(RuntimeError, match="missing string 'secret' key"):
        await resolver("vault://wormbase/wrong-shape")


# ---------------------------------------------------------------------------
# Unsupported scheme rejected with intent-conveying error.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_scheme_raises() -> None:
    resolver = LazyWebhookSecretResolver()
    with pytest.raises(RuntimeError, match="unsupported webhook secret_ref scheme"):
        await resolver("kms://aws/some-key")


@pytest.mark.asyncio
async def test_empty_ref_raises() -> None:
    resolver = LazyWebhookSecretResolver()
    with pytest.raises(RuntimeError, match="empty"):
        await resolver("")


# ---------------------------------------------------------------------------
# Lazy-binding contract — the dispatcher holds the same resolver instance
# that bind_broker mutates, so a late binding lights up in-flight deliveries.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_late_binding_observed_by_deliveries(tmp_path: Path) -> None:
    """The dispatcher captures the resolver before the broker exists.

    Once the build smoke runs and binds a broker, the SAME resolver
    object on the dispatcher's transport resolves vault:// refs. This
    is the v1.4 #3 invariant: no re-composition needed.
    """
    from wormbase_agent_gateway.credential_broker.env import EnvCredentialBroker

    resolver = get_or_create_lazy_webhook_resolver()
    # Singleton — second call returns the same object.
    assert resolver is get_or_create_lazy_webhook_resolver()

    # Before binding, vault:// fails.
    with pytest.raises(RuntimeError):
        await resolver("vault://wormbase/late")

    # Smoke binds the broker (simulating run_agent_gateway_build_smoke).
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    await broker.put_secret(
        "wormbase/late", {"secret": "bound-after-the-fact"},
    )
    resolver.bind_broker(broker)

    # Same resolver instance now resolves.
    secret = await resolver("vault://wormbase/late")
    assert secret == "bound-after-the-fact"


# ---------------------------------------------------------------------------
# Integration: composed dispatcher uses the lazy resolver (not a placeholder).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compose_dispatcher_wires_lazy_resolver_into_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dispatcher's WebhookTransport.secret_resolver IS the singleton.

    Before v1.4 #3, ``_compose_subscription_dispatcher_deps_if_enabled``
    constructed a ``_placeholder_resolver`` lambda that always raised.
    The fix wires the LazyWebhookSecretResolver singleton instead.
    """
    monkeypatch.setenv("WORMBASE_SUBSCRIPTIONS_ENABLED", "true")

    from wormbase_core.cli import (
        _compose_subscription_dispatcher_deps_if_enabled,
    )

    # Use an in-memory ledger; the resolver path doesn't need a real one.
    from wormbase_ledger import InMemoryLedger
    from uuid import uuid4
    deps = _compose_subscription_dispatcher_deps_if_enabled(
        ledger=InMemoryLedger(),
        company_id=uuid4(),
    )
    assert deps is not None
    transport = deps.webhook_transport
    # The resolver attached to the transport is the singleton.
    assert transport._resolve is get_or_create_lazy_webhook_resolver()
    # Confirm it's our LazyWebhookSecretResolver, not a placeholder lambda.
    assert isinstance(transport._resolve, LazyWebhookSecretResolver)


@pytest.mark.asyncio
async def test_webhook_transport_awaits_async_resolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """WebhookTransport.deliver awaits the async LazyWebhookSecretResolver.

    Pins the v1.4 #3 contract that ``WebhookTransport`` accepts async
    resolvers (via inspect.isawaitable on the call return). Without the
    fix, the deliver() call would TypeError on ``secret.encode()``
    because ``secret`` would be a coroutine.
    """
    from wormbase_agent_gateway.credential_broker.env import EnvCredentialBroker
    from wormbase_agent_gateway.subscriptions import WebhookTransport

    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    await broker.put_secret(
        "wormbase/async-test", {"secret": "async-resolved"},
    )
    resolver = LazyWebhookSecretResolver()
    resolver.bind_broker(broker)

    transport = WebhookTransport(
        secret_resolver=resolver,
        max_retries=0,  # one attempt — failure expected (no server)
        request_timeout_s=0.5,
    )
    # We assert deliver runs the resolver path without TypeError. The
    # HTTP POST will fail (no server), which is fine — we want the
    # delivery result to reflect a network failure, not a resolver crash.
    result = await transport.deliver(
        url="http://127.0.0.1:1/no-server",
        secret_ref="vault://wormbase/async-test",
        payload={"hello": "world"},
    )
    assert result.status == "failed"
    # Confirm we got past the resolve step: error mentions the network,
    # not the resolver internals.
    assert result.error is not None
    # No "coroutine" / "encode" complaints — those would indicate the
    # transport tried to use a coroutine as a string.
    assert "encode" not in result.error
    assert "coroutine" not in result.error
