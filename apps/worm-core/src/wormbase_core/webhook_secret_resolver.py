"""LazyWebhookSecretResolver — v1.4 #3 close-out of the v2.A webhook gap.

The agent-subscription dispatcher is composed at boot (early), but the
agent-gateway ``CredentialBroker`` is composed inside the build smoke
(late). v2.A wired a synchronous placeholder resolver that always
raised — blocking real webhook delivery. v1.4 #3 inverts the wiring:
the resolver is async and looks the broker up at delivery time through
a binder that the build smoke populates once the broker is in hand.

Reference grammar (matches the dashboard ``SubscriptionForm`` input):

* ``env://NAME`` — read ``os.environ[NAME]`` at delivery time. Works
  without a broker. Production-acceptable for shared-secret webhooks
  (secret stays in the host environment; never on the ledger).
* ``vault://kv/path/to/secret`` — read the ``secret`` key from the
  broker's KV path at delivery time. Both
  :class:`EnvCredentialBroker` (file-backed mirror) and
  :class:`VaultCredentialBroker` (hvac KV v2) accept the same
  ``put_secret(path, {"secret": ...})`` shape, so the read pattern
  is symmetric across impls.

Both schemes preserve the v2.A architectural commitment that the raw
secret never appears on the ledger — only the reference does.

Lives in its own module (rather than ``cli.py``) so the build smoke
(``agent_gateway_construction.py``) can import the class without a
circular import on cli.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger("wormbase_core.webhook_secret_resolver")


class LazyWebhookSecretResolver:
    """Async webhook-secret resolver with lazy broker binding.

    Concurrency: the bound broker is read via attribute access so a
    later ``bind_broker(...)`` call is observed by in-flight
    deliveries without locking; the broker objects are themselves
    async-safe.
    """

    def __init__(self) -> None:
        self._broker: Any | None = None
        # Captured for diagnostics — populated when bind_broker runs.
        self._broker_kind: str | None = None

    def bind_broker(self, broker: Any) -> None:
        """Bind a CredentialBroker after it has been composed.

        Idempotent — re-binding swaps the broker (used by tests).
        """
        self._broker = broker
        self._broker_kind = (
            getattr(broker, "kind", None) if broker is not None else None
        )
        logger.info(
            "lazy webhook resolver bound to broker kind=%r",
            self._broker_kind,
        )

    @property
    def is_bound(self) -> bool:
        """True iff ``bind_broker`` has been called with a non-None broker."""
        return self._broker is not None

    @property
    def broker_kind(self) -> str | None:
        """Diagnostic accessor — kind tag of the bound broker, or None."""
        return self._broker_kind

    async def __call__(self, secret_ref: str) -> str:
        """Resolve ``secret_ref`` to a raw secret string at delivery time."""
        if not secret_ref:
            raise RuntimeError("webhook secret_ref is empty")
        if secret_ref.startswith("env://"):
            name = secret_ref[len("env://"):]
            value = os.environ.get(name)
            if value is None:
                raise RuntimeError(
                    f"env:// webhook secret missing: env var {name!r} is unset",
                )
            return value
        if secret_ref.startswith("vault://"):
            if self._broker is None:
                raise RuntimeError(
                    f"webhook secret_ref={secret_ref!r} requires a "
                    f"CredentialBroker, but none is bound yet. Set "
                    f"WORMBASE_AGENT_GATEWAY_BUILD_SMOKE_ENABLED=1 (or "
                    f"WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED=1) so "
                    f"the broker is composed at boot.",
                )
            path = secret_ref[len("vault://"):]
            return await self._read_from_broker(path)
        raise RuntimeError(
            f"unsupported webhook secret_ref scheme: {secret_ref!r} "
            f"(expected env://NAME or vault://path)",
        )

    async def _read_from_broker(self, path: str) -> str:
        """Read the ``secret`` key from the bound broker's KV at ``path``.

        Both ``EnvCredentialBroker`` and ``VaultCredentialBroker``
        accept ``put_secret(path, {...})`` with the same payload
        shape, so the read pattern is symmetric. We read raw KV (not
        ``hold_data_account``) because webhook secrets aren't scoped
        per install — they live in a flat per-tenant KV namespace.
        """
        broker = self._broker
        broker_kind = self._broker_kind
        # EnvCredentialBroker — read the file at secrets_dir/path.
        if broker_kind == "env":
            secrets_dir = getattr(broker, "_secrets_dir", None)
            if secrets_dir is None:
                raise RuntimeError(
                    "env broker is bound but has no secrets_dir attribute",
                )
            full = Path(secrets_dir) / path
            if not full.exists():
                raise RuntimeError(
                    f"env broker has no secret at vault://{path} "
                    f"(looked up {full})",
                )
            data = json.loads(full.read_text())
            secret = data.get("secret")
            if not isinstance(secret, str) or not secret:
                raise RuntimeError(
                    f"env broker vault://{path} payload missing string "
                    f"'secret' key",
                )
            return secret
        # VaultCredentialBroker — read via hvac KV v2 at the same path.
        if broker_kind == "vault":
            client = getattr(broker, "_client", None)
            mount_point = getattr(broker, "_mount_point", None)
            if client is None or mount_point is None:
                raise RuntimeError(
                    "vault broker is bound but missing _client / "
                    "_mount_point — broker construction failed?",
                )
            result = await asyncio.to_thread(
                client.secrets.kv.v2.read_secret_version,
                path=path,
                mount_point=mount_point,
                raise_on_deleted_version=True,
            )
            data = result["data"]["data"]
            secret = data.get("secret")
            if not isinstance(secret, str) or not secret:
                raise RuntimeError(
                    f"vault://{path} payload missing string 'secret' key",
                )
            return secret
        raise RuntimeError(
            f"unsupported broker kind for vault:// resolution: "
            f"{broker_kind!r}",
        )


# Module-level singleton. The agent-gateway build smoke binds the
# broker into this resolver once it has constructed one; subscription
# deliveries pick it up automatically. Tests can replace the binding
# via ``bind_broker`` without re-composing the dispatcher.
_LAZY_WEBHOOK_RESOLVER: LazyWebhookSecretResolver | None = None


def get_or_create_lazy_webhook_resolver() -> LazyWebhookSecretResolver:
    """Singleton accessor for the process-wide lazy resolver."""
    global _LAZY_WEBHOOK_RESOLVER
    if _LAZY_WEBHOOK_RESOLVER is None:
        _LAZY_WEBHOOK_RESOLVER = LazyWebhookSecretResolver()
    return _LAZY_WEBHOOK_RESOLVER


def get_lazy_webhook_resolver() -> LazyWebhookSecretResolver | None:
    """Public accessor — returns the singleton if it has been created.

    Returns None if no dispatcher compose call has run yet
    (subscriptions disabled, or boot not yet reached the
    dispatcher-compose step). The agent-gateway build smoke calls
    this and binds the broker if one is available.
    """
    return _LAZY_WEBHOOK_RESOLVER


def reset_lazy_webhook_resolver_for_tests() -> None:
    """Test helper — drop the singleton so each test starts fresh."""
    global _LAZY_WEBHOOK_RESOLVER
    _LAZY_WEBHOOK_RESOLVER = None
