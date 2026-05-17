"""Tests for ``seed_local_lake`` (Block I7).

Two paths exercised:

1. **Happy path** — POST to /api/v1/installs/provision-local-lake
   succeeds with a 201 carrying source_id + entry_ids. The helper
   parses the response into a SeedLocalLakeReport.
2. **Failure modes** — missing api_token / dashboard_api_base /
   tenant raise ValueError; HTTP 4xx/5xx raises RuntimeError.
"""

from __future__ import annotations

import json as _json
from uuid import uuid4

import httpx
import pytest

from wormbase_sim_harness.seed_local_lake import (
    SeedLocalLakeReport,
    seed_local_lake,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_local_lake_posts_to_worm_core() -> None:
    """End-to-end happy path: posts the orchestrator body to
    /api/v1/installs/provision-local-lake with the right shape."""

    tenant_id = uuid4()
    installer_person_id = uuid4()
    source_id = uuid4()
    entry_ids = [str(uuid4()) for _ in range(16)]
    requests_seen: list[tuple[str, dict | None, dict[str, str]]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        try:
            body = (
                _json.loads(request.content.decode())
                if request.content
                else None
            )
        except Exception:
            body = None
        requests_seen.append((str(request.url), body, dict(request.headers)))

        if request.url.path == "/api/v1/installs/provision-local-lake":
            assert request.headers.get("Authorization") == "Bearer test-bearer"
            assert request.headers.get("X-Tenant-Slug") == "baseworm"
            return httpx.Response(
                201,
                json={
                    "source_id": str(source_id),
                    "entry_ids": entry_ids,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await seed_local_lake(
            tenant="baseworm",
            tenant_id=tenant_id,
            installer_person_id=installer_person_id,
            dashboard_api_base="http://worm-core:8910",
            api_token="test-bearer",
            http_client=client,
        )

    # Result envelope.
    assert isinstance(report, SeedLocalLakeReport)
    assert report.source_id == source_id
    assert report.entry_count == 16
    assert report.tenant == "baseworm"

    # Wire shape.
    [(url, body, _headers)] = requests_seen
    assert url.endswith("/api/v1/installs/provision-local-lake")
    assert body == {
        "tenant_id": str(tenant_id),
        "installer_person_id": str(installer_person_id),
    }


@pytest.mark.asyncio
async def test_seed_local_lake_to_dict_round_trips() -> None:
    """SeedLocalLakeReport.to_dict serializes for the seed-table renderer."""
    sid = uuid4()
    report = SeedLocalLakeReport(source_id=sid, entry_count=16, tenant="baseworm")
    d = report.to_dict()
    assert d == {
        "source_id": str(sid),
        "entry_count": 16,
        "tenant": "baseworm",
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_local_lake_rejects_missing_api_token() -> None:
    with pytest.raises(ValueError, match="api_token"):
        await seed_local_lake(
            tenant="baseworm",
            tenant_id=uuid4(),
            installer_person_id=uuid4(),
            dashboard_api_base="http://worm-core:8910",
            api_token="",
        )


@pytest.mark.asyncio
async def test_seed_local_lake_rejects_missing_api_base() -> None:
    with pytest.raises(ValueError, match="dashboard_api_base"):
        await seed_local_lake(
            tenant="baseworm",
            tenant_id=uuid4(),
            installer_person_id=uuid4(),
            dashboard_api_base="",
            api_token="t",
        )


@pytest.mark.asyncio
async def test_seed_local_lake_rejects_missing_tenant() -> None:
    with pytest.raises(ValueError, match="tenant"):
        await seed_local_lake(
            tenant="",
            tenant_id=uuid4(),
            installer_person_id=uuid4(),
            dashboard_api_base="http://worm-core:8910",
            api_token="t",
        )


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_local_lake_raises_on_http_error() -> None:
    """HTTP 4xx / 5xx surfaces as a RuntimeError carrying the body."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="installer_person_id missing")

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="HTTP 422"):
            await seed_local_lake(
                tenant="baseworm",
                tenant_id=uuid4(),
                installer_person_id=uuid4(),
                dashboard_api_base="http://worm-core:8910",
                api_token="t",
                http_client=client,
            )
