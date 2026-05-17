"""Tests for the personas-as-Person-rows seed (E5)."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from wormbase_sim_harness.seed_personas import (
    CANONICAL_PERSONAS,
    seed_personas,
)


@pytest.mark.asyncio
async def test_seed_personas_posts_four_personas_via_worm_core_api() -> None:
    """seed_personas hits propose+confirm for each of the four canonical IDs."""
    requests_seen: list[tuple[str, dict | None]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            body = (
                __import__("json").loads(request.content.decode())
                if request.content
                else None
            )
        except Exception:
            body = None
        requests_seen.append((path, body))

        # Auth + tenant headers must arrive on every request.
        assert request.headers.get("Authorization") == "Bearer fake-token"
        assert request.headers.get("X-Tenant-Slug") == "baseworm"

        if path == "/api/v1/people":
            assert body and "name" in body
            return httpx.Response(
                200,
                json={
                    "person_id": str(uuid4()),
                    "entry_ids": [str(uuid4()) for _ in range(4)],
                },
            )
        if path.endswith("/confirm"):
            assert body and "confirmed_by" in body
            return httpx.Response(
                200,
                json={"entry_ids": [str(uuid4()) for _ in range(4)]},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await seed_personas(
            tenant="baseworm",
            dashboard_api_base="http://worm-core:8910",
            api_token="fake-token",
            http_client=client,
        )

    assert report.proposed == 4
    assert report.confirmed == 4
    assert len(report.person_ids) == 4
    # Every returned id is a real UUID.
    assert all(isinstance(pid, UUID) for pid in report.person_ids)

    # The wire saw 4 proposes + 4 confirms in order, with the right paths.
    propose_calls = [r for r in requests_seen if r[0] == "/api/v1/people"]
    confirm_calls = [r for r in requests_seen if r[0].endswith("/confirm")]
    assert len(propose_calls) == 4
    assert len(confirm_calls) == 4

    # Each propose body matches one of the canonical personas.
    proposed_names = {b["name"] for _, b in propose_calls if b}
    expected_names = {p.name for p in CANONICAL_PERSONAS}
    assert proposed_names == expected_names


@pytest.mark.asyncio
async def test_seed_personas_propagates_propose_failure() -> None:
    """A 4xx from worm-core surfaces as a RuntimeError with the body."""
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/people":
            return httpx.Response(422, json={"error": "validation_failed"})
        return httpx.Response(200, json={"entry_ids": []})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="HTTP 422"):
            await seed_personas(
                tenant="baseworm",
                dashboard_api_base="http://worm-core:8910",
                api_token="fake-token",
                http_client=client,
            )


@pytest.mark.asyncio
async def test_seed_personas_propagates_confirm_failure() -> None:
    """A 5xx on the confirm step surfaces as a RuntimeError."""
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/people":
            return httpx.Response(
                200, json={"person_id": str(uuid4()), "entry_ids": []},
            )
        if request.url.path.endswith("/confirm"):
            return httpx.Response(500, text="boom")
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await seed_personas(
                tenant="baseworm",
                dashboard_api_base="http://worm-core:8910",
                api_token="fake-token",
                http_client=client,
            )


@pytest.mark.asyncio
async def test_seed_personas_requires_token_and_base() -> None:
    """Missing required args fail fast with ValueError."""
    with pytest.raises(ValueError, match="api_token"):
        await seed_personas(
            tenant="baseworm",
            dashboard_api_base="http://worm-core:8910",
            api_token="",
        )
    with pytest.raises(ValueError, match="dashboard_api_base"):
        await seed_personas(
            tenant="baseworm",
            dashboard_api_base="",
            api_token="t",
        )
    with pytest.raises(ValueError, match="tenant"):
        await seed_personas(
            tenant="",
            dashboard_api_base="http://worm-core:8910",
            api_token="t",
        )


def test_canonical_personas_match_personas_yml_roster() -> None:
    """CANONICAL_PERSONAS covers exactly the four ids in personas.yml.

    Drift-detection: if someone adds a fifth bot persona in personas.yml
    without adding it to CANONICAL_PERSONAS, the ledger Person projection
    won't have a row for that bot — and the dashboard's /people surface
    will surface a stranger sending messages. Catch that here.
    """
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[2].parent
    personas_yml = repo_root / "apps/sim-harness/personas.yml"
    raw = yaml.safe_load(personas_yml.read_text(encoding="utf-8"))
    yml_ids = set(raw["personas"].keys())
    canonical_ids = {p.pid for p in CANONICAL_PERSONAS}
    assert yml_ids == canonical_ids, (
        f"personas.yml roster diverged from CANONICAL_PERSONAS: "
        f"missing_in_yml={canonical_ids - yml_ids} "
        f"missing_in_canonical={yml_ids - canonical_ids}"
    )
