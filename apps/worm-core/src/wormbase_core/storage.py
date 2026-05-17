"""Object storage abstraction for data-product / notebook artifacts.

PRD §16.4: artifact bytes live in object storage; the ledger carries the
``contents_uri`` + ``content_hash``, never the bytes. Backend selection
honours ``WORMBASE_OBJECT_STORE_URI``:

- ``s3://<bucket>/<prefix>``     → S3Backend (boto3-compatible). For dev
  pointing at LocalStack, set ``AWS_ENDPOINT_URL_S3=http://localstack:4566``.
- ``file:///path``               → LocalFsBackend rooted at the path.
- unset                          → LocalFsBackend rooted at
  ``/var/lib/wormbase/object-store`` (production default for sidecar
  filesystem, tmpdir-overridable in tests).

Layout (PRD §16.4):

  {root}/{tenant_id}/data-products/{artifact_id}/{run_id}.{ext}
  {root}/{tenant_id}/notebooks/{notebook_id}/{run_id}.html

The S3Backend uses the same path scheme under the configured bucket.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore(Protocol):
    """Storage backend for artifact bytes.

    ``put`` returns ``(uri, sha256_hex)`` so the caller can land both into
    the ledger entry. ``get`` returns the raw bytes.
    """

    async def put(
        self,
        *,
        tenant_id: str,
        artifact_kind: str,  # "data-products" | "notebooks"
        artifact_id: str,
        run_id: str,
        ext: str,
        data: bytes,
    ) -> tuple[str, str]:
        ...

    async def get(self, uri: str) -> bytes:
        ...


# ---------------------------------------------------------------------------
# Local filesystem backend (default for dev + tests)
# ---------------------------------------------------------------------------


class LocalFsBackend:
    """Local-filesystem object store rooted at ``root``.

    Paths follow the canonical layout:
        {root}/{tenant_id}/{artifact_kind}/{artifact_id}/{run_id}.{ext}

    URIs are ``file://`` absolute paths. The hash is computed over the
    bytes, byte-for-byte identical to what S3Backend computes.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(
        self,
        *,
        tenant_id: str,
        artifact_kind: str,
        artifact_id: str,
        run_id: str,
        ext: str,
        data: bytes,
    ) -> tuple[str, str]:
        directory = self.root / tenant_id / artifact_kind / artifact_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{run_id}.{ext}"
        path.write_bytes(data)
        return f"file://{path}", _sha256_hex(data)

    async def get(self, uri: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError(f"LocalFsBackend cannot read non-file URI {uri!r}")
        path = Path(uri[len("file://"):])
        return path.read_bytes()


# ---------------------------------------------------------------------------
# S3 backend (LocalStack in dev, real S3 in prod)
# ---------------------------------------------------------------------------


class S3Backend:
    """S3-compatible object store.

    Uses ``aioboto3`` lazily so the import only fires when an S3 store is
    requested (keeps tests + dev fast without the dep).

    The bucket must already exist; the backend only writes objects, not
    buckets. F6 ships a bucket-creation init step on the LocalStack
    docker-compose service.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        self.endpoint_url = endpoint_url

    def _key(
        self,
        *,
        tenant_id: str,
        artifact_kind: str,
        artifact_id: str,
        run_id: str,
        ext: str,
    ) -> str:
        parts = [self.prefix] if self.prefix else []
        parts.extend([tenant_id, artifact_kind, artifact_id, f"{run_id}.{ext}"])
        return "/".join(p for p in parts if p)

    def _session(self):  # noqa: ANN202 — late-imported aioboto3.Session
        import aioboto3  # type: ignore[import-untyped]

        return aioboto3.Session()

    async def put(
        self,
        *,
        tenant_id: str,
        artifact_kind: str,
        artifact_id: str,
        run_id: str,
        ext: str,
        data: bytes,
    ) -> tuple[str, str]:
        key = self._key(
            tenant_id=tenant_id,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            run_id=run_id,
            ext=ext,
        )
        session = self._session()
        async with session.client("s3", endpoint_url=self.endpoint_url) as s3:
            await s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}", _sha256_hex(data)

    async def get(self, uri: str) -> bytes:
        if not uri.startswith("s3://"):
            raise ValueError(f"S3Backend cannot read non-S3 URI {uri!r}")
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        session = self._session()
        async with session.client("s3", endpoint_url=self.endpoint_url) as s3:
            obj = await s3.get_object(Bucket=bucket, Key=key)
            async with obj["Body"] as stream:
                return await stream.read()


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def get_storage_backend() -> ObjectStore:
    """Pick a backend per env. See module docstring for the contract."""
    import tempfile

    raw = os.environ.get("WORMBASE_OBJECT_STORE_URI", "").strip()
    if raw.startswith("s3://"):
        parsed = urlparse(raw)
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/")
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL_S3") or None
        return S3Backend(bucket=bucket, prefix=prefix, endpoint_url=endpoint_url)
    if raw.startswith("file://"):
        path = raw[len("file://"):]
        return LocalFsBackend(path)
    if raw:
        # Treat any non-prefixed value as a filesystem path.
        return LocalFsBackend(raw)
    # Production default: /var/lib/wormbase/object-store. Fall back to a
    # tmpdir under the system temp root if the canonical path isn't
    # writable (dev / macOS without sudo). Both paths are dev-time
    # safe; production deployment must mount /var/lib/wormbase as a
    # writable volume.
    canonical = Path("/var/lib/wormbase/object-store")
    try:
        canonical.mkdir(parents=True, exist_ok=True)
        return LocalFsBackend(canonical)
    except (OSError, PermissionError):
        fallback = Path(tempfile.gettempdir()) / "wormbase-object-store"
        return LocalFsBackend(fallback)


__all__ = [
    "LocalFsBackend",
    "ObjectStore",
    "S3Backend",
    "get_storage_backend",
]
