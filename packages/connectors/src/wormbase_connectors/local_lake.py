"""Local lake connector — the default lake every tenant gets at install.

Every tenant gets a ``LocalLakeConnector`` auto-provisioned on install
(see ``wormbase_core.write_actions.provision_local_lake``). The lake
plays all three medallion layers from minute zero, backed by the
tenant's ledger projections plus a tenant-scoped local filesystem
under ``/var/lib/wormbase/{tenant_id}/local-lake/``.

Resources discovered:

* ``bronze.conversations`` — raw normalized chat stream
  (``chat_received`` entries from the ledger).
* ``bronze.files_dropped`` — file-drop bronze (``ingest_landed``).
* ``silver.persons`` — Person projection.
* ``silver.decisions`` — extracted decision records (memory-tagged).
* ``silver.processes`` — process maps the worm has extracted.
* ``gold.kpi_summary`` — KPI projection summary.
* ``gold.recurring_questions`` — recurring-question gold artifact.

The connector implements ``discover``, ``profile``, and ``sample``.
``watch`` is intentionally not advertised — the lake updates as the
worm runs, not via external polling.

Auth bundle:
    {"tenant_id": "<uuid>", "store_root": "<path>" (optional)}

The store_root defaults to ``/var/lib/wormbase/{tenant_id}/local-lake/``
and is created on authenticate when missing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Canonical resource catalog. Each entry pairs a stable ``resource_id``
# (used by profile/sample) with the canonical schema the worm-core
# projections expose for that layer + a short editorial description.
# ---------------------------------------------------------------------------


_BRONZE_CONVERSATIONS_COLUMNS: list[dict[str, Any]] = [
    {"name": "channel_id", "dtype": "str", "nullable": False, "ordinal": 1},
    {"name": "message_id", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "sender_person", "dtype": "uuid", "nullable": False, "ordinal": 3},
    {"name": "ts", "dtype": "timestamptz", "nullable": False, "ordinal": 4},
    {"name": "text", "dtype": "str", "nullable": False, "ordinal": 5},
    {"name": "classification", "dtype": "str", "nullable": False, "ordinal": 6},
]

_BRONZE_FILES_DROPPED_COLUMNS: list[dict[str, Any]] = [
    {"name": "source_id", "dtype": "uuid", "nullable": False, "ordinal": 1},
    {"name": "object_uri", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "bytes", "dtype": "int", "nullable": False, "ordinal": 3},
    {"name": "row_count", "dtype": "int", "nullable": False, "ordinal": 4},
    {"name": "ts", "dtype": "timestamptz", "nullable": False, "ordinal": 5},
]

_SILVER_PERSONS_COLUMNS: list[dict[str, Any]] = [
    {"name": "person_id", "dtype": "uuid", "nullable": False, "ordinal": 1},
    {"name": "tenant_id", "dtype": "uuid", "nullable": False, "ordinal": 2},
    {"name": "name", "dtype": "str", "nullable": False, "ordinal": 3},
    {"name": "email", "dtype": "str", "nullable": True, "ordinal": 4},
    {"name": "position", "dtype": "str", "nullable": True, "ordinal": 5},
    {"name": "status", "dtype": "str", "nullable": False, "ordinal": 6},
]

_SILVER_DECISIONS_COLUMNS: list[dict[str, Any]] = [
    {"name": "memory_id", "dtype": "uuid", "nullable": False, "ordinal": 1},
    {"name": "content", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "tags", "dtype": "json", "nullable": False, "ordinal": 3},
    {"name": "written_at", "dtype": "timestamptz", "nullable": False, "ordinal": 4},
]

_SILVER_PROCESSES_COLUMNS: list[dict[str, Any]] = [
    {"name": "process_id", "dtype": "uuid", "nullable": False, "ordinal": 1},
    {"name": "name", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "owner_person_id", "dtype": "uuid", "nullable": True, "ordinal": 3},
    {"name": "steps", "dtype": "json", "nullable": False, "ordinal": 4},
    {"name": "extracted_at", "dtype": "timestamptz", "nullable": False, "ordinal": 5},
]

_GOLD_KPI_SUMMARY_COLUMNS: list[dict[str, Any]] = [
    {"name": "node_id", "dtype": "str", "nullable": False, "ordinal": 1},
    {"name": "name", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "domain_id", "dtype": "uuid", "nullable": True, "ordinal": 3},
    {"name": "owner_person_id", "dtype": "uuid", "nullable": True, "ordinal": 4},
    {"name": "metric_type", "dtype": "str", "nullable": False, "ordinal": 5},
    {"name": "confidence", "dtype": "str", "nullable": False, "ordinal": 6},
]

_GOLD_RECURRING_QUESTIONS_COLUMNS: list[dict[str, Any]] = [
    {"name": "question_id", "dtype": "uuid", "nullable": False, "ordinal": 1},
    {"name": "canonical_text", "dtype": "str", "nullable": False, "ordinal": 2},
    {"name": "occurrence_count", "dtype": "int", "nullable": False, "ordinal": 3},
    {"name": "first_seen_at", "dtype": "timestamptz", "nullable": False, "ordinal": 4},
    {"name": "last_seen_at", "dtype": "timestamptz", "nullable": False, "ordinal": 5},
]


_RESOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "bronze.conversations": {
        "name": "bronze.conversations",
        "kind": "table",
        "description": (
            "Raw normalized chat stream from every connected channel — "
            "messages, threads, mentions, reactions. The conversation lake."
        ),
        "columns": _BRONZE_CONVERSATIONS_COLUMNS,
        "ledger_kind": "chat_received",
    },
    "bronze.files_dropped": {
        "name": "bronze.files_dropped",
        "kind": "table",
        "description": (
            "Bronze-tier landing for files dropped into channels — every "
            "ingest_landed entry the channel-adapter has captured."
        ),
        "columns": _BRONZE_FILES_DROPPED_COLUMNS,
        "ledger_kind": "ingest_landed",
    },
    "silver.persons": {
        "name": "silver.persons",
        "kind": "table",
        "description": (
            "Canonical Person projection — one row per real human or "
            "service account, status + position included."
        ),
        "columns": _SILVER_PERSONS_COLUMNS,
        "projection_table": "projection_persons",
    },
    "silver.decisions": {
        "name": "silver.decisions",
        "kind": "table",
        "description": (
            "Decision records extracted from conversation gold — what was "
            "decided, why, by whom."
        ),
        "columns": _SILVER_DECISIONS_COLUMNS,
        "projection_table": "projection_memory",
    },
    "silver.processes": {
        "name": "silver.processes",
        "kind": "table",
        "description": (
            "Process maps extracted from chatter — how decisions actually "
            "flow through the org."
        ),
        "columns": _SILVER_PROCESSES_COLUMNS,
        "projection_table": "projection_processes",
    },
    "gold.kpi_summary": {
        "name": "gold.kpi_summary",
        "kind": "table",
        "description": (
            "Gold-tier KPI summary — every confirmed KPI node with owner "
            "and confidence."
        ),
        "columns": _GOLD_KPI_SUMMARY_COLUMNS,
        "projection_table": "projection_kpi_nodes",
    },
    "gold.recurring_questions": {
        "name": "gold.recurring_questions",
        "kind": "table",
        "description": (
            "Recurring-question gold — canonical questions the org keeps "
            "asking, with occurrence counts."
        ),
        "columns": _GOLD_RECURRING_QUESTIONS_COLUMNS,
        "projection_table": "projection_recurring_questions",
    },
}


# Ordered list of resource ids — discover() returns proposals in this
# order so the dashboard's resource picker renders bronze → silver → gold.
LOCAL_LAKE_RESOURCE_IDS: tuple[str, ...] = (
    "bronze.conversations",
    "bronze.files_dropped",
    "silver.persons",
    "silver.decisions",
    "silver.processes",
    "gold.kpi_summary",
    "gold.recurring_questions",
)


def _default_store_root(tenant_id: str) -> Path:
    return Path("/var/lib/wormbase") / tenant_id / "local-lake"


def _schema_hash(columns: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
    ).hexdigest()[:16]


# Optional injection point for the row-count + sample query. Production
# wires this to an asyncpg-backed query layer; tests inject a fake.
RowCountQuery = Any  # callable: async (tenant_id, resource_id) -> int
SampleQuery = Any  # callable: async (tenant_id, resource_id, n) -> list[dict]


@register_connector
class LocalLakeConnector(Connector):
    """Default lake — every tenant gets one at install."""

    kind = "local_lake"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = []
    status: str = "production"
    status_note: str = (
        "Default lake — yours from minute zero. Plays all three medallion "
        "layers backed by your ledger projections + a tenant-scoped local "
        "filesystem."
    )

    def __init__(
        self,
        *,
        row_count_query: RowCountQuery | None = None,
        sample_query: SampleQuery | None = None,
    ) -> None:
        """Optional injection points for ledger-backed counts + samples.

        ``row_count_query`` is an async callable
        ``(tenant_id: str, resource_id: str) -> int``. When unset,
        :meth:`profile` returns 0 rows — safe for tests and for the
        provision-at-install path which writes a fresh empty lake.

        ``sample_query`` is an async callable
        ``(tenant_id: str, resource_id: str, n: int) -> list[dict]``.
        When unset, :meth:`sample` returns an empty bytes object.
        """
        self._row_count_query = row_count_query
        self._sample_query = sample_query

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        tenant_id = secrets.payload.get("tenant_id")
        if not tenant_id or not isinstance(tenant_id, str):
            raise ValueError(
                "local_lake requires {tenant_id: str} in secrets payload"
            )
        store_root_raw = secrets.payload.get("store_root")
        if store_root_raw:
            store_root = Path(str(store_root_raw))
        else:
            store_root = _default_store_root(tenant_id)
        # Best-effort directory creation. We don't fail authenticate when
        # the path can't be created (e.g. read-only test FS); discover /
        # profile / sample don't depend on the directory existing.
        try:
            store_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return AuthHandle(
            connector_kind="local_lake",
            handle_id=tenant_id,
            extra={
                "tenant_id": tenant_id,
                "store_root": str(store_root),
            },
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        proposals: list[ResourceProposal] = []
        for rid in LOCAL_LAKE_RESOURCE_IDS:
            entry = _RESOURCE_CATALOG[rid]
            proposals.append(
                ResourceProposal(
                    resource_id=rid,
                    name=entry["name"],
                    kind=entry["kind"],
                    classification_hint="internal",
                    metadata={
                        "description": entry["description"],
                        "tier": rid.split(".", 1)[0],
                    },
                )
            )
        return proposals

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        entry = _RESOURCE_CATALOG.get(resource_id)
        if entry is None:
            raise ValueError(
                f"local_lake: unknown resource_id {resource_id!r}; "
                f"valid: {list(LOCAL_LAKE_RESOURCE_IDS)}"
            )
        columns = list(entry["columns"])
        row_count = 0
        if self._row_count_query is not None:
            row_count = int(
                await self._row_count_query(
                    handle.extra["tenant_id"], resource_id,
                )
            )
        return Profile(
            row_count=row_count,
            column_count=len(columns),
            columns=columns,
            schema_hash=_schema_hash(columns),
            extra={
                "tenant_id": handle.extra["tenant_id"],
                "resource_id": resource_id,
                "tier": resource_id.split(".", 1)[0],
            },
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        entry = _RESOURCE_CATALOG.get(resource_id)
        if entry is None:
            raise ValueError(
                f"local_lake: unknown resource_id {resource_id!r}; "
                f"valid: {list(LOCAL_LAKE_RESOURCE_IDS)}"
            )
        if self._sample_query is None:
            return b""
        rows = await self._sample_query(
            handle.extra["tenant_id"], resource_id, n,
        )
        if not rows:
            return b""
        # Serialize as JSONL — one row per line, deterministic key order.
        lines = [json.dumps(r, sort_keys=True, default=str) for r in rows]
        return ("\n".join(lines) + "\n").encode()

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # Lake updates as the worm runs; no external watch.
        if False:
            yield  # type: ignore[unreachable]


__all__ = [
    "LOCAL_LAKE_RESOURCE_IDS",
    "LocalLakeConnector",
]
