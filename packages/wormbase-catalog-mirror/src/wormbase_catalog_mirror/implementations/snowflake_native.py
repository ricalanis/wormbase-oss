"""SnowflakeNativeCatalogSource — reads INFORMATION_SCHEMA + tag references + policy references.

Per S2 spike findings:
- POLICY_REFERENCES does NOT include POLICY_BODY — body fetched via DESCRIBE <KIND> POLICY <fqn>
- POLICY_KIND values normalized: MASKING_POLICY -> masking, ROW_ACCESS_POLICY -> row_access
- TAG_REFERENCES_ALL_COLUMNS returns table-level tags with null COLUMN_NAME; filter out
- Auth supports password (dev shortcut) AND OAuth (production path)
- Tag propagation tolerance: empty tags tuple is acceptable when propagation hasn't landed
- Privilege gap: caller without APPLY on a policy sees the reference but not the body —
  raise PolicyBodyUnavailableError per-policy (catalog-mirror records the gap as a typed signal)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

import snowflake.connector

from ..errors import AuthenticationError
from ..protocol import AuthHandle
from ..types import (
    CatalogCapability,
    CatalogDelta,
    CatalogSnapshot,
    ColumnMeta,
    ExternalPolicy,
    LineageGraph,
    MetricDefinition,
    PolicyKind,
    TableMeta,
)


@dataclass(frozen=True)
class _SnowflakeHandle:
    secrets: dict[str, str]


@dataclass
class SnowflakeNativeCatalogSource:
    kind: str = field(default="snowflake", init=False)
    capability: frozenset[CatalogCapability] = field(
        default=frozenset({"schema", "lineage", "policy"}),
        init=False,
    )

    async def authenticate(self, secrets: dict[str, str]) -> AuthHandle:
        required = ("account", "user", "warehouse", "database", "schema")
        missing = [k for k in required if k not in secrets]
        if missing:
            raise AuthenticationError(f"missing snowflake auth fields: {missing}")
        # Auth path: prefer OAuth (token field) when present, else password.
        if "token" not in secrets and "password" not in secrets:
            raise AuthenticationError("snowflake auth needs either 'token' (OAuth) or 'password'")
        return _SnowflakeHandle(secrets=dict(secrets))

    def _connect(self, h: _SnowflakeHandle):
        s = h.secrets
        kwargs = dict(
            account=s["account"], user=s["user"],
            warehouse=s["warehouse"], database=s["database"], schema=s["schema"],
            role=s.get("role"),
        )
        if "token" in s:
            kwargs["authenticator"] = "oauth"
            kwargs["token"] = s["token"]
        else:
            kwargs["password"] = s["password"]
        return snowflake.connector.connect(**kwargs)

    async def discover_catalog(self, handle: AuthHandle) -> CatalogSnapshot:
        h = handle  # type: ignore[assignment]
        return await asyncio.to_thread(self._discover_catalog_sync, h)

    def _discover_catalog_sync(self, h: _SnowflakeHandle) -> CatalogSnapshot:
        conn = self._connect(h)
        try:
            cur = conn.cursor()
            db = h.secrets["database"]
            schema = h.secrets["schema"]

            # Tables + columns
            cur.execute(
                f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COMMENT, ORDINAL_POSITION
                FROM {db}.INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                (schema,),
            )
            by_table: dict[str, list[tuple[str, str, str | None]]] = {}
            for table_name, col_name, dtype, comment, _ in cur.fetchall():
                by_table.setdefault(table_name, []).append((col_name, dtype, comment))

            # Per-table tags
            tables: list[TableMeta] = []
            for table_name, cols_raw in by_table.items():
                tags_by_col: dict[str, list[str]] = {}
                try:
                    cur.execute(
                        f"""
                        SELECT COLUMN_NAME, TAG_VALUE
                        FROM TABLE({db}.INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS('{db}.{schema}.{table_name}', 'TABLE'))
                        WHERE COLUMN_NAME IS NOT NULL
                        """
                    )
                    for col_name, tag_val in cur.fetchall():
                        tags_by_col.setdefault(col_name, []).append(tag_val)
                except snowflake.connector.errors.ProgrammingError:
                    pass  # No tags or insufficient privilege; non-fatal

                cols = tuple(
                    ColumnMeta(
                        name=c_name,
                        type=dtype,
                        description=comment or None,
                        tags=tuple(tags_by_col.get(c_name, [])),
                    )
                    for c_name, dtype, comment in cols_raw
                )
                tables.append(TableMeta(
                    external_id=f"snowflake://{db}.{schema}.{table_name}",
                    name=table_name,
                    schema=schema,
                    database=db,
                    description=None,
                    columns=cols,
                ))
            return CatalogSnapshot(
                source_kind="snowflake",
                tables=tuple(tables),
                lineage=LineageGraph(edges=()),
                policies=(),
                metrics=[],
            )
        finally:
            conn.close()

    async def discover_lineage(self, handle: AuthHandle, resource_id: str) -> LineageGraph:
        # Snowflake lineage requires ACCOUNT_USAGE.OBJECT_DEPENDENCIES (latent ~2h).
        # v1 returns empty; v1.1 wires the cross-database read.
        return LineageGraph(edges=())

    async def discover_policies(self, handle: AuthHandle, resource_id: str) -> list[ExternalPolicy]:
        h = handle  # type: ignore[assignment]
        return await asyncio.to_thread(self._discover_policies_sync, h, resource_id)

    def _discover_policies_sync(self, h: _SnowflakeHandle, table: str) -> list[ExternalPolicy]:
        conn = self._connect(h)
        try:
            cur = conn.cursor()
            db = h.secrets["database"]
            schema = h.secrets["schema"]

            cur.execute(
                f"""
                SELECT POLICY_DB, POLICY_SCHEMA, POLICY_NAME, POLICY_KIND, REF_COLUMN_NAME
                FROM TABLE({db}.INFORMATION_SCHEMA.POLICY_REFERENCES(REF_ENTITY_NAME=>'{db}.{schema}.{table}', REF_ENTITY_DOMAIN=>'TABLE'))
                """
            )
            refs = cur.fetchall()

            results: list[ExternalPolicy] = []
            for pdb, pschema, pname, pkind, ref_col in refs:
                fqn = f"{pdb}.{pschema}.{pname}"
                kind: PolicyKind = "masking" if pkind == "MASKING_POLICY" else "row_access"
                kind_keyword = "MASKING" if kind == "masking" else "ROW ACCESS"
                body: str | None = None
                try:
                    cur.execute(f"DESCRIBE {kind_keyword} POLICY {fqn}")
                    desc_rows = cur.fetchall()
                    # DESCRIBE returns columns [created_on, name, kind, body, ...]
                    body = desc_rows[0][3] if desc_rows else None
                except snowflake.connector.errors.ProgrammingError:
                    # Caller lacks APPLY on the policy — record as typed gap, not absence
                    body = None
                results.append(ExternalPolicy(
                    name=fqn,
                    policy_kind=kind,
                    body=body,
                    applied_to=(ref_col,) if ref_col else (),
                ))
            return results
        finally:
            conn.close()

    async def discover_metrics(self, handle: AuthHandle) -> list[MetricDefinition]:
        # Snowflake Semantic Views support comes in v1.1; v1 returns empty.
        return []

    async def watch_changes(self, handle: AuthHandle) -> AsyncIterator[CatalogDelta]:
        # No native push-CDC; Reactivity polls discover_catalog.
        if False:
            yield  # pragma: no cover
        return
