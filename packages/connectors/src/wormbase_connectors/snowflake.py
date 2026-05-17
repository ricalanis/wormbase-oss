"""Snowflake connector — discover/profile/sample via snowflake-connector-python.

snowflake-connector-python is sync-only. We bridge to the async Connector
contract by running the blocking calls in a thread executor — Snowflake
discover/profile/sample are low-frequency operations (per-source, not
per-row) so the executor cost is negligible.

Auth bundle:
    {
        "account":   "abc12345.us-east-1" | "myorg-myaccount",
        "user":      str,
        "password":  str | None,
        "private_key": str | None,         # PEM contents (key-pair auth)
        "warehouse": str,
        "role":      str | None,
        "database":  str,
        "schema":    str | None,
    }

Either ``password`` or ``private_key`` is required. ``database`` is
required; ``schema`` defaults to PUBLIC. Discover lists tables via
``INFORMATION_SCHEMA.TABLES`` of the configured database.

**Governance passthrough (P7).** The connector advertises the
``governance_passthrough`` capability and, during ``profile``, queries
Snowflake's ``INFORMATION_SCHEMA.TAG_REFERENCES`` view to resolve any
``COLUMN.TAG`` set on the table's columns. Each Snowflake tag value is
mapped to a WormBase classification via :data:`SNOWFLAKE_TAG_MAPPINGS`
and surfaced on the returned :class:`Profile` as

    Profile.columns[i]["tags"] = [{"name": ..., "value": ..., "classification": ...}]
    Profile.extra["column_tags"] = {col_name: classification, ...}
    Profile.extra["resource_classification"] = highest classification across columns

Downstream, the source-builder reads these and emits
``emit_resource_classified`` so ``Resource.classification`` and
``column_tags`` propagate end-to-end into the WormBase ledger. The
masked-column refusal gate (see
:mod:`wormbase_governance.policies.masked_column_refusal`) consumes
``column_tags`` to refuse queries that touch a tagged column.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
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
# Snowflake COLUMN.TAG → WormBase classification mapping.
#
# Snowflake's governance-tag vocabulary is conventional, not standardized:
# customers create tags named PII / SENSITIVE / CONFIDENTIAL / REGULATED /
# MASKED / etc. and tag columns with values like 'EMAIL' / 'SSN' / 'PHONE'.
# We map both the tag name (e.g. ``PII``) and common tag values (e.g.
# ``EMAIL``, ``SSN``) into the WormBase Classification enum — see
# ``wormbase_governance.entities.Classification``. The mapping is the
# documented contract between Snowflake-native governance and the
# WormBase ledger; it is checked into ontology where it can be tuned
# per-tenant later.
#
# Lookup is case-insensitive. Anything not in this table is preserved
# in ``column_tags`` metadata but does NOT escalate the column's
# classification beyond ``internal``.
# ---------------------------------------------------------------------------

SNOWFLAKE_TAG_MAPPINGS: dict[str, str] = {
    # Tag NAMES (column-level governance categories)
    "pii": "pii",
    "personal_data": "pii",
    "personally_identifiable": "pii",
    "sensitive_pii": "pii",
    "regulated": "regulated",
    "regulatory": "regulated",
    "phi": "regulated",
    "pci": "regulated",
    "hipaa": "regulated",
    "confidential": "confidential",
    "highly_confidential": "confidential",
    "restricted": "confidential",
    "masked": "confidential",
    "internal": "internal",
    "public": "public",
    # Tag VALUES (often used directly as the classifier)
    "email": "pii",
    "phone": "pii",
    "ssn": "regulated",
    "credit_card": "regulated",
    "tax_id": "regulated",
}

# Classification escalation order — used by ``profile`` to compute the
# resource-level rollup from column tags (highest wins).
_CLASS_RANK: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3,
    "regulated": 4,
}


def _classify_tag(tag_name: str | None, tag_value: str | None) -> str | None:
    """Map a Snowflake (tag_name, tag_value) pair to a Classification.

    Returns the WormBase Classification literal or ``None`` if neither
    side of the tag matches the mapping table. The check is case-
    insensitive and tolerant of underscores vs spaces.
    """
    for raw in (tag_value, tag_name):
        if raw is None:
            continue
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        if not key:
            continue
        if key in SNOWFLAKE_TAG_MAPPINGS:
            return SNOWFLAKE_TAG_MAPPINGS[key]
    return None


def _escalate(current: str, candidate: str) -> str:
    """Pick the higher-rank classification between two values."""
    if _CLASS_RANK.get(candidate, 0) > _CLASS_RANK.get(current, 0):
        return candidate
    return current


def _connect_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("account", "user", "warehouse", "database")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValueError(
            "snowflake connector requires "
            + ", ".join(required)
            + f"; missing: {missing}"
        )
    if not payload.get("password") and not payload.get("private_key"):
        raise ValueError(
            "snowflake connector requires either {password} or {private_key}"
        )
    kwargs = {
        "account": payload["account"],
        "user": payload["user"],
        "warehouse": payload["warehouse"],
        "database": payload["database"],
    }
    for opt in ("password", "private_key", "role", "schema"):
        if payload.get(opt):
            kwargs[opt] = payload[opt]
    return kwargs


@register_connector
class SnowflakeConnector(Connector):
    """Snowflake connector via snowflake-connector-python (sync, executor-bridged)."""

    kind = "snowflake"
    capability: set[Capability] = {
        "discover", "profile", "sample", "governance_passthrough",
    }
    classification_hints: list[ClassificationHint] = []
    status: str = "production"
    status_note: str = (
        "Production-grade. Discover/profile/sample via "
        "snowflake-connector-python. Profile pulls COLUMN.TAG via "
        "TAG_REFERENCES (governance_passthrough)."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        kwargs = _connect_kwargs(secrets.payload)
        # Validate by opening + closing a quick connection.
        await asyncio.to_thread(self._test_connect, kwargs)
        return AuthHandle(
            connector_kind="snowflake",
            handle_id=hashlib.sha256(
                f"{kwargs['account']}/{kwargs['user']}/{kwargs['database']}".encode()
            ).hexdigest()[:16],
            extra={"connect_kwargs": kwargs},
        )

    @staticmethod
    def _test_connect(kwargs: dict[str, Any]) -> None:
        import snowflake.connector

        try:
            conn = snowflake.connector.connect(**kwargs)
        except Exception as exc:
            raise ValueError(f"snowflake authenticate failed: {exc}") from exc
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT CURRENT_VERSION()")
                cur.fetchone()
            finally:
                cur.close()
        finally:
            conn.close()

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        kwargs = handle.extra["connect_kwargs"]
        rows = await asyncio.to_thread(self._discover_sync, kwargs)
        return [
            ResourceProposal(
                resource_id=f"{schema}.{table}",
                name=f"{schema}.{table}",
                kind="table",
                classification_hint=None,
                metadata={
                    "schema": schema,
                    "table": table,
                    "row_count": row_count,
                    "table_type": table_type,
                },
            )
            for (schema, table, row_count, table_type) in rows
        ]

    @staticmethod
    def _discover_sync(kwargs: dict[str, Any]) -> list[tuple[str, str, int | None, str]]:
        import snowflake.connector

        conn = snowflake.connector.connect(**kwargs)
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT TABLE_SCHEMA, TABLE_NAME, ROW_COUNT, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA != 'INFORMATION_SCHEMA'
                    ORDER BY TABLE_SCHEMA, TABLE_NAME
                    """
                )
                return [
                    (r[0], r[1], r[2], r[3]) for r in cur.fetchall()
                ]
            finally:
                cur.close()
        finally:
            conn.close()

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        if "." not in resource_id:
            raise ValueError(
                f"snowflake resource_id must be schema.table: {resource_id!r}"
            )
        schema, table = resource_id.split(".", 1)
        kwargs = handle.extra["connect_kwargs"]
        cols, row_count, tag_rows = await asyncio.to_thread(
            self._profile_sync, kwargs, schema, table,
        )
        # Build per-column tag-list and the column->classification map.
        # ``tag_rows`` is a list of (column_name, tag_name, tag_value)
        # tuples — one row per (column, tag) pair returned by
        # INFORMATION_SCHEMA.TAG_REFERENCES.
        col_tags: dict[str, list[dict[str, str]]] = {}
        col_classification: dict[str, str] = {}
        for col_name, tag_name, tag_value in tag_rows:
            classification = _classify_tag(tag_name, tag_value)
            entry = {
                "name": tag_name or "",
                "value": tag_value or "",
                "classification": classification or "internal",
            }
            col_tags.setdefault(col_name, []).append(entry)
            if classification is not None:
                prev = col_classification.get(col_name, "internal")
                col_classification[col_name] = _escalate(prev, classification)

        columns = []
        for c in cols:
            name = c[0]
            tags = col_tags.get(name, [])
            classification = col_classification.get(name)
            columns.append({
                "name": name,
                "dtype": c[1],
                "nullable": c[2] == "Y" or c[2] is True,
                "default": c[3],
                "tags": tags,
                **(
                    {"classification": classification}
                    if classification is not None else {}
                ),
            })

        # Resource-level classification = highest column classification,
        # default ``internal`` if no column carries a tag.
        resource_classification = "internal"
        for cls in col_classification.values():
            resource_classification = _escalate(resource_classification, cls)

        # ``column_tags`` (plain col -> classification map) is the shape
        # the masked-column refusal gate consumes — keep it tight and
        # JSON-serializable so it can ride in the ledger payload.
        column_tags_map = dict(col_classification)

        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=row_count,
            column_count=len(columns),
            columns=columns,
            schema_hash=schema_hash,
            extra={
                "schema": schema,
                "table": table,
                "column_tags": column_tags_map,
                "resource_classification": resource_classification,
                "governance_passthrough": True,
            },
        )

    @staticmethod
    def _profile_sync(
        kwargs: dict[str, Any], schema: str, table: str,
    ) -> tuple[
        list[tuple[Any, ...]],
        int | None,
        list[tuple[str, str | None, str | None]],
    ]:
        import snowflake.connector

        conn = snowflake.connector.connect(**kwargs)
        try:
            cur = conn.cursor()
            try:
                cur.execute(f'DESCRIBE TABLE "{schema}"."{table}"')
                cols = cur.fetchall()
                cur.execute(
                    """
                    SELECT ROW_COUNT FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    """,
                    (schema, table),
                )
                row = cur.fetchone()
                row_count = row[0] if row else None
                # Pull column tags (governance_passthrough). Snowflake
                # exposes COLUMN.TAG via INFORMATION_SCHEMA.TAG_REFERENCES
                # — one row per (column, tag) assignment. We filter to
                # the configured table and to OBJECT_DOMAIN = 'COLUMN'.
                # If the lookup raises (e.g. role lacks privileges or
                # the view is unavailable), we degrade gracefully to
                # an empty tag list rather than failing the whole
                # profile call.
                tag_rows: list[tuple[str, str | None, str | None]] = []
                try:
                    cur.execute(
                        """
                        SELECT COLUMN_NAME, TAG_NAME, TAG_VALUE
                        FROM TABLE(
                            INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS(
                                %s, 'TABLE'
                            )
                        )
                        WHERE OBJECT_SCHEMA = %s
                        """,
                        (f'"{schema}"."{table}"', schema),
                    )
                    tag_rows = [
                        (r[0], r[1], r[2]) for r in cur.fetchall()
                    ]
                except Exception:
                    # Defensive: TAG_REFERENCES_ALL_COLUMNS requires
                    # ``APPLY TAG`` or higher on Snowflake. If absent,
                    # propagate empty tag list — the gate simply won't
                    # have anything to refuse on, which is correct.
                    tag_rows = []
                return cols, row_count, tag_rows
            finally:
                cur.close()
        finally:
            conn.close()

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        if "." not in resource_id:
            raise ValueError(
                f"snowflake resource_id must be schema.table: {resource_id!r}"
            )
        schema, table = resource_id.split(".", 1)
        kwargs = handle.extra["connect_kwargs"]
        rows, columns = await asyncio.to_thread(
            self._sample_sync, kwargs, schema, table, n,
        )
        if not rows:
            return b""
        header = "\t".join(columns)
        body_lines = [
            "\t".join("" if v is None else str(v) for v in row)
            for row in rows
        ]
        return ("\n".join([header, *body_lines]) + "\n").encode()

    @staticmethod
    def _sample_sync(
        kwargs: dict[str, Any], schema: str, table: str, n: int,
    ) -> tuple[list[tuple[Any, ...]], list[str]]:
        import snowflake.connector

        conn = snowflake.connector.connect(**kwargs)
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f'SELECT * FROM "{schema}"."{table}" LIMIT {int(n)}'
                )
                rows = cur.fetchall()
                columns = (
                    [d[0] for d in cur.description] if cur.description else []
                )
                return rows, columns
            finally:
                cur.close()
        finally:
            conn.close()

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # Snowflake Streams CDC is post-day-one work.
        if False:
            yield  # type: ignore[unreachable]


__all__ = [
    "SNOWFLAKE_TAG_MAPPINGS",
    "SnowflakeConnector",
]
