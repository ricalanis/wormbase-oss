"""G.1 — verify ``projection_roles`` supports the resource facet (Wave B.5).

The Block-G ``emit_resource_role_proposed`` PEVR cycle (added in G.3) lands
a grant via the same projection_roles table the Wave-A-landing schema already
created. This test is the contractual seed: it asserts the ``projection_roles``
schema can hold a row with ``facet='resource'`` and ``scope_id=resource_id``
when an ``emit_resource_role_assigned`` execute envelope is folded.

Per the deferred-backlog plan G.1 step 2: this is verification-only because
the Wave-A landing of ``projection_roles`` already shipped the resource-facet
columns (``facet``, ``scope_id``, ``scope_type``). No migration needed.

When G.3 adds ``emit_resource_role_proposed``, the PEVR cycle resolves into
the same projection shape this test pins.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


@pytest.mark.asyncio
async def test_resource_role_grant_lands_in_projection_roles(
    test_database_url: str,
) -> None:
    """A resource-facet grant lands with facet='resource' and scope_id=resource_id.

    Drives the canonical PEVR cycle (propose → execute → verify → resolve(keep))
    for ``emit_resource_role_assigned``, which is the canonical landed grant
    for the resource facet. Asserts the projection_roles row carries the
    full resource-facet shape:

        facet         = 'resource'
        scope_id      = resource_id
        scope_type    = resource_type (e.g. 'kpi')
        role          = role
        revoked_at    = None
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    resource_id = uuid4()
    admin = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "resource_role_assigned",
                "ref_id": str(resource_id),
                "reason": "grant",
                "proposed_by": str(admin),
            },
            execute_fn=lambda: {
                "tool": "emit_resource_role_assigned",
                "args": {
                    "person_id": str(person_id),
                    "resource_id": str(resource_id),
                    "resource_type": "kpi",
                    "role": "maintainer",
                    "granted_by": str(admin),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Schema verification: the row landed with the resource-facet columns
    # populated. If this fails, the projection_roles table needs a migration
    # to add ``facet`` / ``scope_id`` / ``scope_type``.
    assert len(proj.roles) == 1
    g = proj.roles[0]
    assert g["facet"] == "resource"
    assert g["scope_id"] == resource_id
    assert g["scope_type"] == "kpi"
    assert g["role"] == "maintainer"
    assert g["person_id"] == person_id
    assert g["tenant_id"] == company_id
    assert g["granted_by"] == admin
    assert g["revoked_at"] is None
    assert g["granted_at"] is not None


@pytest.mark.asyncio
async def test_projection_roles_schema_columns_present(
    test_database_url: str,
) -> None:
    """The projection_roles table exposes facet / scope_id / scope_type columns.

    A direct schema introspection: confirms the table shape supports the
    resource facet without depending on any specific kind-fold.
    """
    from sqlalchemy import inspect

    engine = get_engine(test_database_url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("projection_roles")
            }
        )

    # The three columns that distinguish the multi-facet design.
    assert "facet" in cols
    assert "scope_id" in cols
    assert "scope_type" in cols
    # Audit / replay columns the resource-facet rows also rely on.
    assert "granted_by" in cols
    assert "granted_at" in cols
    assert "revoked_at" in cols
    assert "last_updated_seq" in cols
