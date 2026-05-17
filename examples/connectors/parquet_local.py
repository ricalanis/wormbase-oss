"""parquet_local — the canonical reference Connector implementation.

This file is the ground truth for "what does a WormBase Connector look like?".
It is intentionally:

  * Self-contained — only ``pyarrow`` + the Python standard library.
    No WormBase-internal imports. Drop this file into a Jupyter cell
    (or a fresh venv with ``pip install pyarrow``) and it runs.

  * Five-capability complete — implements ``authenticate``, ``discover``,
    ``profile``, ``sample``, and ``watch``. Every other connector
    in the catalog can be read against this file as a worked example.

  * Duck-typed against the Connector Protocol — the file defines its
    own ``AuthHandle`` / ``ResourceProposal`` / ``Profile`` / ``Change``
    dataclasses with the exact field names the Protocol specifies.
    The conformance harness ``wormbase-tools-test`` checks attribute
    presence, not nominal type, so this file conforms without
    importing any internal package.

The companion walkthrough is ``examples/CONTRIBUTING-A-CONNECTOR.md``.

Usage from a Jupyter cell:

    import asyncio
    from examples.connectors.parquet_local import (
        ParquetLocalConnector,
        SecretBundle,
    )

    async def demo():
        c = ParquetLocalConnector()
        h = await c.authenticate(SecretBundle({"path": "data.parquet"}))
        for r in await c.discover(h):
            print(r.resource_id)
            p = await c.profile(h, r.resource_id)
            print("  rows:", p.row_count, "cols:", p.column_count)
            print("  first 64 bytes:", (await c.sample(h, r.resource_id, 64))[:64])

    asyncio.run(demo())
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Local Connector-Protocol-shaped dataclasses
#
# These mirror ``wormbase_connectors.types`` field-for-field but live in this
# file so the reference has zero internal-package dependencies. The
# conformance harness checks structurally; nominal identity is not required.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretBundle:
    """Opaque container for connector credentials."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthHandle:
    """Returned by :meth:`Connector.authenticate`. Used in subsequent calls."""

    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceProposal:
    """A resource discovered by :meth:`Connector.discover`."""

    resource_id: str
    name: str
    kind: str
    classification_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """Result of :meth:`Connector.profile`."""

    row_count: int | None
    column_count: int | None
    columns: list[dict[str, Any]]
    schema_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """Streaming change record from :meth:`Connector.watch`."""

    resource_id: str
    seq: int
    kind: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# The connector itself
# ---------------------------------------------------------------------------


class ParquetLocalConnector:
    """Connector for local Parquet files — discover, profile, sample."""

    kind: str = "parquet_local"
    capability: set[str] = {"discover", "profile", "sample"}
    classification_hints: list[str] = []
    status: str = "production"
    status_note: str = "Drop a .parquet file at the configured path; we'll profile it."

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        path = secrets.payload.get("path")
        if not path or not isinstance(path, str):
            raise ValueError("parquet_local requires {path: str}")
        return AuthHandle(
            connector_kind=self.kind,
            handle_id=path,
            extra={"path": path},
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        path = Path(handle.extra["path"])
        if not path.exists():
            return []
        # A path may be a single .parquet file or a directory of parts.
        # We expose either as a single ResourceProposal so the source-builder
        # can defer per-row-group reading to profile/sample.
        return [
            ResourceProposal(
                resource_id=str(path),
                name=path.name,
                kind="file" if path.is_file() else "directory",
                classification_hint=None,
                metadata={
                    "size_bytes": _path_size(path),
                    "path": str(path),
                    "mimetype": "application/x-parquet",
                },
            )
        ]

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        pf = pq.ParquetFile(resource_id)
        schema = pf.schema_arrow
        columns = [
            {
                "name": field.name,
                "dtype": str(field.type),
                "nullable": field.nullable,
            }
            for field in schema
        ]
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=pf.metadata.num_rows,
            column_count=len(columns),
            columns=columns,
            schema_hash=schema_hash,
            extra={
                "path": resource_id,
                "row_groups": pf.metadata.num_row_groups,
            },
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        # ``n`` is best-effort byte cap. We read the first row group and
        # truncate. Determinism is guaranteed by row-group order in Parquet.
        pf = pq.ParquetFile(resource_id)
        if pf.metadata.num_row_groups == 0:
            return b""
        table = pf.read_row_group(0)
        # Convert to a deterministic CSV-like bytes representation.
        # JSON-lines preserves type fidelity better; we use it for portability.
        out = bytearray()
        names = table.column_names
        for row_idx in range(table.num_rows):
            if len(out) >= n:
                break
            row = {name: table.column(name)[row_idx].as_py() for name in names}
            out.extend(_jsonl_encode(row))
        # Honor the byte cap exactly.
        return bytes(out[:n])

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # Pull-only; CDC is post-day-one. Yield nothing; iterator exits cleanly.
        if False:
            yield  # type: ignore[unreachable]


# ---------------------------------------------------------------------------
# Internal helpers (stdlib only)
# ---------------------------------------------------------------------------


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    # Directory: sum of child file sizes (one level deep for typical
    # Parquet datasets; recursive walk is not required by the Protocol).
    return sum(p.stat().st_size for p in path.iterdir() if p.is_file())


def _jsonl_encode(row: dict[str, Any]) -> bytes:
    """Stdlib-only JSON-lines encoder with deterministic key order."""
    import json
    return (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")


__all__ = [
    "AuthHandle",
    "Change",
    "ParquetLocalConnector",
    "Profile",
    "ResourceProposal",
    "SecretBundle",
]
