"""S3 CSV connector — discover/profile/sample via aioboto3.

Auth bundle:
    {
        "aws_access_key_id":    str,
        "aws_secret_access_key": str,
        "aws_session_token":    str | None,
        "region_name":          str | None,    # default us-east-1
        "bucket":               str,
        "prefix":               str | None,    # default ""
        "endpoint_url":         str | None,    # for moto / minio
    }

discover lists the prefix via list_objects_v2 (only `*.csv`/`*.csv.gz`
keys are surfaced as ResourceProposals). profile fetches the first
64KB via Range request, parses as CSV, infers column dtypes from the
peek. sample fetches first n bytes via Range header.

watch is not supported (S3 EventBridge wiring is post-day-one).
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import AsyncIterator
from io import StringIO
from typing import Any

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


def _client_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "region_name",
        "endpoint_url",
    ):
        if key in payload and payload[key] is not None:
            kwargs[key] = payload[key]
    kwargs.setdefault("region_name", "us-east-1")
    return kwargs


@register_connector
class S3CsvConnector(Connector):
    """S3 CSV connector via aioboto3."""

    kind = "s3_csv"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = ["bucket_name"]
    status: str = "production"
    status_note: str = (
        "Production-grade. Discover lists CSV/CSV.gz keys via list_objects_v2; "
        "profile + sample via Range-bounded GetObject."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        bucket = secrets.payload.get("bucket")
        if not bucket or not isinstance(bucket, str):
            raise ValueError("s3_csv requires {bucket: str}")
        prefix = secrets.payload.get("prefix") or ""
        client_kwargs = _client_kwargs(secrets.payload)
        return AuthHandle(
            connector_kind="s3_csv",
            handle_id=hashlib.sha256(
                f"{bucket}/{prefix}".encode()
            ).hexdigest()[:16],
            extra={
                "bucket": bucket,
                "prefix": prefix,
                "client_kwargs": client_kwargs,
            },
        )

    async def _session(self, handle: AuthHandle) -> Any:
        import aioboto3

        return aioboto3.Session()

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        bucket = handle.extra["bucket"]
        prefix = handle.extra["prefix"]
        kwargs = handle.extra["client_kwargs"]
        session = await self._session(handle)
        proposals: list[ResourceProposal] = []
        async with session.client("s3", **kwargs) as s3:
            # We use a single list_objects_v2 page; for >1000 objects
            # the source-builder can re-discover with a deeper prefix.
            resp = await s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            for obj in resp.get("Contents", []):
                key = obj.get("Key")
                if not isinstance(key, str):
                    continue
                if not (key.endswith(".csv") or key.endswith(".csv.gz")):
                    continue
                proposals.append(
                    ResourceProposal(
                        resource_id=key,
                        name=key.rsplit("/", 1)[-1],
                        kind="file",
                        classification_hint=None,
                        metadata={
                            "bucket": bucket,
                            "key": key,
                            "size_bytes": obj.get("Size"),
                            "last_modified": (
                                obj["LastModified"].isoformat()
                                if obj.get("LastModified")
                                else None
                            ),
                            "etag": obj.get("ETag"),
                        },
                    )
                )
        return proposals

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        bucket = handle.extra["bucket"]
        kwargs = handle.extra["client_kwargs"]
        session = await self._session(handle)
        async with session.client("s3", **kwargs) as s3:
            head_resp = await s3.get_object(
                Bucket=bucket,
                Key=resource_id,
                Range=f"bytes=0-{_PROFILE_HEAD_BYTES - 1}",
            )
            body = await head_resp["Body"].read()
        text = body.decode("utf-8", errors="replace")
        reader = csv.reader(StringIO(text))
        header = next(reader, [])
        rows = list(reader)
        # Drop the last (likely truncated) row when we hit the byte cap.
        if len(body) >= _PROFILE_HEAD_BYTES and rows:
            rows.pop()
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
            row_count=None,  # head-bytes profile cannot count whole file
            column_count=len(header),
            columns=columns,
            schema_hash=schema_hash,
            extra={"bucket": bucket, "key": resource_id},
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        bucket = handle.extra["bucket"]
        kwargs = handle.extra["client_kwargs"]
        session = await self._session(handle)
        async with session.client("s3", **kwargs) as s3:
            resp = await s3.get_object(
                Bucket=bucket,
                Key=resource_id,
                Range=f"bytes=0-{max(n - 1, 0)}",
            )
            body = await resp["Body"].read()
        return body

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


__all__ = ["S3CsvConnector"]
