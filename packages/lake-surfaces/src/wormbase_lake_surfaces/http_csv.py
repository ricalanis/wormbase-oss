"""HTTP CSV connector — discover/profile/sample via httpx.

For arbitrary HTTPS-served CSV endpoints (data portals, internal
file servers, S3 pre-signed URLs, etc.). The discover step is
trivial — one URL == one resource. The Profile and sample steps
both use Range requests so the connector never reads more than
64KB by default.

Auth bundle:
    {"url": "https://...", "auth_header": "Bearer ..." | null,
     "headers": {"X-Foo": "bar", ...} | null}
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import AsyncIterator
from io import StringIO
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

_PROFILE_HEAD_BYTES = 64 * 1024
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


def _request_headers(extra: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = dict(extra.get("headers") or {})
    auth_header = extra.get("auth_header")
    if isinstance(auth_header, str) and auth_header:
        headers["Authorization"] = auth_header
    return headers


@register_connector
class HttpCsvConnector(Connector):
    """HTTP CSV connector via httpx."""

    kind = "http_csv"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = ["url_pattern"]
    status: str = "production"
    status_note: str = (
        "Production-grade. One URL = one resource; profile + sample via Range-bounded GET."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        url = secrets.payload.get("url")
        if not url or not isinstance(url, str):
            raise ValueError("http_csv requires {url: str}")
        return AuthHandle(
            connector_kind="http_csv",
            handle_id=hashlib.sha256(url.encode()).hexdigest()[:16],
            extra={
                "url": url,
                "auth_header": secrets.payload.get("auth_header"),
                "headers": secrets.payload.get("headers") or {},
            },
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        url = handle.extra["url"]
        # Try to size the resource via HEAD; fall through to size=None
        # when HEAD is not supported.
        size: int | None = None
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.head(
                    url, headers=_request_headers(handle.extra),
                )
                if resp.status_code < 400:
                    cl = resp.headers.get("content-length")
                    if cl is not None and cl.isdigit():
                        size = int(cl)
        except httpx.HTTPError:
            pass
        return [
            ResourceProposal(
                resource_id=url,
                name=url.rsplit("/", 1)[-1] or url,
                kind="endpoint",
                classification_hint=None,
                metadata={
                    "url": url,
                    "size_bytes": size,
                    "mimetype": "text/csv",
                },
            )
        ]

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        headers = _request_headers(handle.extra)
        headers["Range"] = f"bytes=0-{_PROFILE_HEAD_BYTES - 1}"
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(resource_id, headers=headers)
            resp.raise_for_status()
            body = resp.content
        text = body.decode("utf-8", errors="replace")
        reader = csv.reader(StringIO(text))
        header = next(reader, [])
        rows = list(reader)
        if len(body) >= _PROFILE_HEAD_BYTES and rows:
            rows.pop()  # last row may be truncated
        columns = []
        for i, h in enumerate(header):
            col_values = [row[i] for row in rows if i < len(row)]
            columns.append(
                {
                    "name": h,
                    "dtype": _infer_dtype(col_values),
                    "sample_values": col_values[:3],
                }
            )
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=None,
            column_count=len(header),
            columns=columns,
            schema_hash=schema_hash,
            extra={"url": resource_id},
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        headers = _request_headers(handle.extra)
        headers["Range"] = f"bytes=0-{max(n - 1, 0)}"
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(resource_id, headers=headers)
            resp.raise_for_status()
            return resp.content

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        if False:
            yield  # type: ignore[unreachable]


def _infer_dtype(values: list[str]) -> str:
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return "str"
    if all(_is_int(v) for v in non_empty):
        return "int"
    if all(_is_float(v) for v in non_empty):
        return "float"
    return "str"


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except ValueError:
        return False


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


__all__ = ["HttpCsvConnector"]
