"""Stripe connector — discover/profile/sample via the Stripe REST API.

We talk to ``api.stripe.com`` directly via httpx instead of pulling
``stripe-python`` because the surface we need (list endpoints, capped
record peeks) is a thin slice and the connector should not load a
fat sync SDK into the agent's hot path.

Stripe API auth: HTTP Basic with the API key as the username and an
empty password — same as the official SDK does internally. We send
the header explicitly to avoid a depends-on-Authorization-helper trap.

Auth bundle:
    {"api_key": "sk_test_..." | "sk_live_...",
     "api_version": "2024-04-10" | None}

Discoverable resources are the canonical Stripe object types:
    - charges
    - customers
    - payouts
    - subscriptions
    - invoices
    - balance_transactions

Profile per object: ``GET /v1/<object>?limit=1`` then introspect the
keys of ``data[0]``. Sample per object: ``GET /v1/<object>?limit=n``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import Connector
from .registry import register_connector
from .types import (
    AuthHandle,
    Capability,
    Change,
    ClassificationHint,
    Profile,
    ResourceProposal,
    SecretBundle,
)

_BASE_URL = "https://api.stripe.com/v1"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Top-level resource types we surface as discoverable. Each is a
# ``GET /v1/<name>`` list endpoint. The order is the dashboard sort
# order — the demo-critical ones first.
STRIPE_OBJECTS: tuple[str, ...] = (
    "charges",
    "customers",
    "payouts",
    "subscriptions",
    "invoices",
    "balance_transactions",
)


def _basic_auth_header(api_key: str) -> str:
    """Stripe's HTTP Basic auth — api_key as user, empty password."""
    raw = f"{api_key}:".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


@register_connector
class StripeConnector(Connector):
    """Stripe REST connector via httpx."""

    kind = "stripe"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = ["pii", "regulated"]
    status: str = "production"
    status_note: str = (
        "Production-grade. Discover enumerates Stripe object types; "
        "profile + sample via the canonical /v1/<object> list endpoints."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        api_key = secrets.payload.get("api_key")
        if not api_key or not isinstance(api_key, str):
            raise ValueError("stripe requires {api_key: str}")
        api_version = secrets.payload.get("api_version")
        return AuthHandle(
            connector_kind="stripe",
            handle_id=hashlib.sha256(api_key.encode()).hexdigest()[:16],
            extra={
                "api_key": api_key,
                "api_version": api_version,
                "auth_header": _basic_auth_header(api_key),
            },
        )

    def _headers(self, handle: AuthHandle) -> dict[str, str]:
        h = {"Authorization": handle.extra["auth_header"]}
        api_version = handle.extra.get("api_version")
        if api_version:
            h["Stripe-Version"] = api_version
        return h

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        # Discover does not call the API — Stripe's object catalog is a
        # known, finite set. Returning the catalog directly avoids
        # unnecessary calls (and unnecessary API-key load) at discover
        # time. Profile + sample do hit the network.
        return [
            ResourceProposal(
                resource_id=name,
                name=name,
                kind="endpoint",
                classification_hint=(
                    "pii"
                    if name in {"customers", "charges", "invoices"}
                    else None
                ),
                metadata={"object_type": name, "list_url": f"{_BASE_URL}/{name}"},
            )
            for name in STRIPE_OBJECTS
        ]

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        if resource_id not in STRIPE_OBJECTS:
            raise ValueError(
                f"unknown stripe object {resource_id!r}; "
                f"valid: {', '.join(STRIPE_OBJECTS)}"
            )
        url = f"{_BASE_URL}/{resource_id}"
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                url, params={"limit": 1}, headers=self._headers(handle),
            )
            resp.raise_for_status()
            data = resp.json()
        records = data.get("data") or []
        sample_record = records[0] if records else {}
        columns = [
            {
                "name": key,
                "dtype": _stripe_dtype(value),
                "sample_value": _truncate_repr(value),
            }
            for key, value in sample_record.items()
        ]
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=None,  # Stripe list endpoints don't surface counts.
            column_count=len(columns),
            columns=columns,
            schema_hash=schema_hash,
            extra={"object_type": resource_id, "has_more": data.get("has_more")},
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        if resource_id not in STRIPE_OBJECTS:
            raise ValueError(
                f"unknown stripe object {resource_id!r}; "
                f"valid: {', '.join(STRIPE_OBJECTS)}"
            )
        url = f"{_BASE_URL}/{resource_id}"
        # Stripe caps `limit` at 100. The connector contract is "best
        # effort", so we cap at 100 silently.
        capped = max(1, min(n, 100))
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                url, params={"limit": capped}, headers=self._headers(handle),
            )
            resp.raise_for_status()
            data = resp.json()
        records = data.get("data") or []
        # Return JSON Lines so the downstream bronze writer can stream
        # this as a flat record set.
        return ("\n".join(json.dumps(r) for r in records) + "\n").encode()

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # Stripe webhooks are post-day-one work. The signing-secret +
        # event-replay handling deserves its own gate.
        if False:
            yield  # type: ignore[unreachable]


def _stripe_dtype(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _truncate_repr(v: Any, max_len: int = 80) -> str:
    s = repr(v)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


__all__ = ["StripeConnector", "STRIPE_OBJECTS"]
