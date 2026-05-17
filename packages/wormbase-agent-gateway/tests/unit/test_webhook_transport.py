"""Unit tests for the v2.A ``WebhookTransport``.

Each test stands up a local aiohttp server via ``TestServer`` (the
``pytest-aiohttp`` plugin is not in dev deps; we use the underlying
``aiohttp.test_utils`` helpers directly so the suite stays
dependency-light). The server is bound to an ephemeral port so the
tests can run concurrently with anything else.

Coverage:

  * ``sign_body`` / ``verify_signature`` roundtrip — the canonical
    HMAC-SHA256 contract receivers can apply.
  * Tamper detection — modifying the body invalidates the signature.
  * Happy-path delivery — 200 OK on first attempt, signature
    verifiable by the receiver.
  * Retry-then-success — first two attempts return 500, third
    succeeds; retry budget is respected.
  * Retry exhaustion — all attempts return 500; transport returns
    ``status=failed`` with the last error.

Wire-replay determinism is exercised at the dispatcher integration
layer (Batch B), not here — this unit covers the transport
mechanics in isolation.
"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestServer

from wormbase_agent_gateway.subscriptions.transports import (
    WebhookTransport,
    sign_body,
    verify_signature,
)


async def _start_server(app: web.Application) -> TestServer:
    server = TestServer(app)
    await server.start_server()
    return server


async def test_sign_then_verify_roundtrip() -> None:
    """A signed body verifies; verification is symmetric to signing."""
    body = b'{"event": "test"}'
    secret = "shh"
    sig = sign_body(body, secret)
    assert verify_signature(body, sig, secret) is True


async def test_verify_signature_rejects_tampered() -> None:
    """Modifying the body invalidates the signature (no false acceptance)."""
    body = b'{"event": "test"}'
    secret = "shh"
    sig = sign_body(body, secret)
    assert verify_signature(body + b"tampered", sig, secret) is False


async def test_deliver_success() -> None:
    """Happy-path delivery: receiver returns 200, signature verifies."""
    received: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        received.append(
            {
                "body": await request.read(),
                "sig": request.headers.get("X-WormBase-Signature"),
            }
        )
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await _start_server(app)
    try:
        url = str(server.make_url("/hook"))

        t = WebhookTransport(
            secret_resolver=lambda ref: "shh",
            max_retries=0,
        )
        result = await t.deliver(
            url=url,
            secret_ref="env://test",
            payload={"event": "x"},
        )
        assert result.status == "delivered"
        assert result.http_status == 200
        assert len(received) == 1
        assert (
            verify_signature(received[0]["body"], received[0]["sig"], "shh")
            is True
        )
    finally:
        await server.close()


async def test_deliver_retries_then_succeeds() -> None:
    """Two 500s then a 200 → ``delivered`` after three attempts."""
    call_count = [0]

    async def handler(request: web.Request) -> web.Response:
        call_count[0] += 1
        if call_count[0] < 3:
            return web.Response(status=500)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await _start_server(app)
    try:
        url = str(server.make_url("/hook"))

        t = WebhookTransport(
            secret_resolver=lambda ref: "shh",
            max_retries=3,
            base_backoff_s=0.01,
        )
        result = await t.deliver(
            url=url,
            secret_ref="env://test",
            payload={"event": "x"},
        )
        assert result.status == "delivered"
        assert call_count[0] == 3
    finally:
        await server.close()


async def test_deliver_max_retries_exceeded() -> None:
    """Every attempt returns 500 → ``failed`` with last error reported."""

    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500)

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await _start_server(app)
    try:
        url = str(server.make_url("/hook"))

        t = WebhookTransport(
            secret_resolver=lambda ref: "shh",
            max_retries=2,
            base_backoff_s=0.01,
        )
        result = await t.deliver(
            url=url,
            secret_ref="env://test",
            payload={"event": "x"},
        )
        assert result.status == "failed"
        assert result.error is not None
        assert result.http_status == 500
    finally:
        await server.close()
