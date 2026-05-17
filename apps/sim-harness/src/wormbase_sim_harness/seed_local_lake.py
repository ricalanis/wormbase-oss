"""Seed the default local lake via the worm-core write API (Block I7).

Companion to ``seed_install`` and ``seed_personas``: when the operator
has run ``wormbase demo seed --install-from-env`` and wants the default
lake row visible at /sources without going through the full OAuth flow,
this module POSTs to the worm-core
``/api/v1/installs/provision-local-lake`` endpoint to drive the same
``provision_local_lake`` orchestrator the production install path uses.

Production never calls this endpoint — ``complete_install`` auto-calls
``provision_local_lake`` inline. The CLI helper exists so a dev tenant
that already has an installer Person + Install row can be brought up to
"has the default lake" parity in one step.

Public API:

* ``seed_local_lake(*, tenant, installer_person_id, dashboard_api_base,
  api_token)`` — returns a ``SeedLocalLakeReport`` on success. Raises
  ``RuntimeError`` for any HTTP failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger("wormbase.sim.seed_local_lake")


@dataclass
class SeedLocalLakeReport:
    """Outcome of a ``seed_local_lake`` call."""

    source_id: UUID
    entry_count: int
    tenant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": str(self.source_id),
            "entry_count": self.entry_count,
            "tenant": self.tenant,
        }


async def seed_local_lake(
    *,
    tenant: str,
    tenant_id: UUID,
    installer_person_id: UUID,
    dashboard_api_base: str,
    api_token: str,
    http_client: httpx.AsyncClient | None = None,
    timeout_s: float = 10.0,
) -> SeedLocalLakeReport:
    """Provision the default lake for a tenant via the worm-core API.

    Parameters
    ----------
    tenant:
        Tenant slug; sent as ``X-Tenant-Slug`` header.
    tenant_id:
        Tenant uuid (same value as the ledger's company_id under
        ``tenant_to_uuid``). Recorded in the ledger entries.
    installer_person_id:
        Person who proposed/confirmed/maintains the lake. Typically the
        Person id returned by ``seed_install_from_env``.
    dashboard_api_base:
        Base URL for the worm-core write API.
    api_token:
        Bearer for the worm-core write API
        (``WORMBASE_LEDGER_API_TOKEN``).
    http_client:
        Optional pre-built ``httpx.AsyncClient`` (tests inject a
        ``MockTransport`` here).
    timeout_s:
        Per-request timeout.
    """
    if not api_token:
        raise ValueError("api_token is required (worm-core bearer auth)")
    if not dashboard_api_base:
        raise ValueError("dashboard_api_base is required")
    if not tenant:
        raise ValueError("tenant is required")

    base = dashboard_api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-Tenant-Slug": tenant,
        "Content-Type": "application/json",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_s)

    try:
        body = {
            "tenant_id": str(tenant_id),
            "installer_person_id": str(installer_person_id),
        }
        try:
            resp = await client.post(
                f"{base}/api/v1/installs/provision-local-lake",
                headers=headers,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"POST /api/v1/installs/provision-local-lake failed: {exc}",
            ) from exc

        if resp.status_code >= 400:
            raise RuntimeError(
                f"POST /api/v1/installs/provision-local-lake returned "
                f"HTTP {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        report = SeedLocalLakeReport(
            source_id=UUID(data["source_id"]),
            entry_count=len(data.get("entry_ids", [])),
            tenant=tenant,
        )
        logger.info(
            "seeded local lake: source_id=%s entries=%d tenant=%s",
            report.source_id, report.entry_count, tenant,
        )
        return report
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "SeedLocalLakeReport",
    "seed_local_lake",
]
