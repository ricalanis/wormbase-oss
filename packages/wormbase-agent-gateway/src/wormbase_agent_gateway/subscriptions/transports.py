"""Outbound webhook delivery for agent event subscriptions.

The ``webhook`` transport choice writes events as signed HTTP POSTs to
the subscription's registered URL. Signing is HMAC-SHA256 over the
JSON-canonicalised body using a secret resolved through the
CredentialBroker — the raw secret never appears on the ledger, only the
reference (``vault://...`` or ``env://...``) stored on the
``agent_subscription_created`` payload.

Retry policy (D2 in the v2.A plan): exponential backoff
``base_backoff_s * 4 ** attempt`` up to ``max_retries`` attempts.
After exhaustion the dispatcher records ``delivery_status=failed`` on
the ledger and pauses the subscription. Admins/agents revive via the
dashboard or by writing a new ``agent_subscription_created`` entry.

Signature verification is constant-time (``hmac.compare_digest``) so a
malicious receiver cannot use timing-side-channel analysis to recover
the secret one byte at a time.

The transport is intentionally I/O-only — no ledger writes happen
here. The dispatcher Reactivity (Batch B) wraps each ``deliver()``
call inside a PEVR ``execute_fn`` so wire-replay can no-op the network
side-effect while still writing the ``agent_event_delivered`` entry.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Union

import aiohttp


# A secret resolver may be either synchronous (``secret_ref → str``) or
# asynchronous (``secret_ref → Awaitable[str]``). Production wiring (v1.4
# #3) uses an async resolver because the CredentialBroker is composed
# after the dispatcher is constructed, so the resolve call must defer to
# delivery time and read the broker through whatever lazy lookup the
# CLI threads in.
SecretResolver = Union[
    Callable[[str], str],
    Callable[[str], Awaitable[str]],
]


@dataclass
class WebhookDeliveryResult:
    """Outcome of a single ``WebhookTransport.deliver`` call.

    ``status`` is the dispatcher's view: ``delivered`` if the receiver
    returned 2xx within the retry budget, ``failed`` otherwise. The
    dispatcher folds this into the ``agent_event_delivered`` entry's
    ``delivery_status`` field. ``http_status`` and ``error`` are
    diagnostic only — useful for SOC-2 audit but not for routing
    decisions.
    """

    status: Literal["delivered", "failed"]
    duration_ms: int
    error: str | None = None
    http_status: int | None = None


def sign_body(body: bytes, secret: str) -> str:
    """HMAC-SHA256 hex digest over body using shared secret.

    The receiver verifies by recomputing the digest over the raw body
    and comparing with the ``X-WormBase-Signature`` header. JSON
    canonicalisation (sort_keys, no whitespace) happens in
    ``WebhookTransport.deliver`` before signing so the receiver can
    apply the same canonicalisation and compare safely.
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Constant-time signature comparison.

    Using ``hmac.compare_digest`` (instead of ``==``) prevents
    timing-side-channel attacks where a malicious receiver guesses the
    secret one byte at a time by measuring how long the comparison
    takes to short-circuit.
    """
    expected = sign_body(body, secret)
    return hmac.compare_digest(expected, signature)


class WebhookTransport:
    """Best-effort outbound POST with HMAC signing + exponential backoff.

    Each ``deliver()`` call opens a fresh ``ClientSession`` so the
    transport stays stateless and safe to share across subscriptions.
    Session-pool reuse is an optimisation deferred until the active
    subscription count justifies it.

    The retry loop sleeps ``base_backoff_s * 4 ** attempt`` between
    attempts and tries up to ``max_retries + 1`` times total. With the
    defaults (``base=1.0``, ``max_retries=3``) that's
    ``1s, 4s, 16s`` of total backoff across four attempts —
    well-aligned with the SLA defaults documented in the plan.
    """

    def __init__(
        self,
        *,
        secret_resolver: SecretResolver,
        max_retries: int = 3,
        base_backoff_s: float = 1.0,
        request_timeout_s: float = 10.0,
    ) -> None:
        self._resolve = secret_resolver
        # Cache the sync/async classification once. ``iscoroutinefunction``
        # returns False for callables that wrap coroutines without being
        # one themselves, so we additionally probe by awaiting the
        # initial call's return value if it's awaitable.
        self._resolve_is_async = inspect.iscoroutinefunction(secret_resolver)
        self._max_retries = max_retries
        self._base_backoff = base_backoff_s
        self._timeout = aiohttp.ClientTimeout(total=request_timeout_s)

    async def _resolve_secret(self, secret_ref: str) -> str:
        """Call the resolver, awaiting if it returned an awaitable.

        Supports both sync and async resolvers. Sync resolvers run
        synchronously (no event-loop hop); async resolvers (or sync
        resolvers that incidentally return an awaitable) are awaited.
        """
        result = self._resolve(secret_ref)
        if inspect.isawaitable(result):
            return await result
        return result  # type: ignore[return-value]

    async def deliver(
        self,
        *,
        url: str,
        secret_ref: str,
        payload: dict,
    ) -> WebhookDeliveryResult:
        """POST payload to url with HMAC signing + exponential backoff.

        The body is JSON-canonicalised (``sort_keys=True``, no
        whitespace) so the signature is reproducible by any receiver
        that applies the same canonicalisation. The
        ``X-WormBase-Delivery-Attempt`` header carries the 1-based
        attempt number so receivers can deduplicate idempotently.
        """
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        secret = await self._resolve_secret(secret_ref)
        sig = sign_body(body, secret)
        start = time.monotonic()
        last_error: str | None = None
        last_status: int | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(
                        url,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-WormBase-Signature": sig,
                            "X-WormBase-Delivery-Attempt": str(attempt + 1),
                        },
                    ) as resp:
                        last_status = resp.status
                        if 200 <= resp.status < 300:
                            return WebhookDeliveryResult(
                                status="delivered",
                                duration_ms=int((time.monotonic() - start) * 1000),
                                http_status=resp.status,
                            )
                        last_error = f"HTTP {resp.status}"
            except Exception as exc:  # noqa: BLE001
                last_error = type(exc).__name__ + ": " + str(exc)[:200]

            if attempt < self._max_retries:
                await asyncio.sleep(self._base_backoff * (4 ** attempt))

        return WebhookDeliveryResult(
            status="failed",
            duration_ms=int((time.monotonic() - start) * 1000),
            error=last_error,
            http_status=last_status,
        )
