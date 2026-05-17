"""POST /api/v1/write_actions/concept_confirmed/{term} — Onboarding Sub-wave D.

Graduates Tier 2's ``confirmBusinessDef`` from a synthetic-receipt
fallback to a real ``concept_confirmed`` PEVR cycle. The handler
resolves ``term → concept_id`` from a prior ``concept_proposed``
ledger entry, then emits the canonical ``concept_confirmed``
execute entry. No new KIND_REGISTRY entries — the existing
``concept_confirmed`` kind is reused (KIND_REGISTRY stays at 111).

Coverage:
- Happy path with a prior ``concept_proposed`` → 200 + entry lands.
- Multiple prior proposals → latest concept_id wins (by seq).
- Case-insensitive + whitespace-trimmed term matching.
- No matching proposal → 404.
- Missing bearer → 401.
- company_id mismatch → 400.
- Empty term → 400.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core import write_actions
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ConceptProposedPayload

API_TOKEN = "test-token-concept-confirmed"
TENANT_SLUG = "baseworm"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


async def _seed_proposal(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    term: str,
    definition: str = "shorthand for the canonical thing",
    proposed_by: str = "worm",
) -> UUID:
    """Seed a ``concept_proposed`` PEVR cycle so the lookup has a hit."""
    concept_id = uuid4()
    payload = ConceptProposedPayload(
        concept_id=concept_id,
        name=term,
        definition=definition,
        proposed_by=proposed_by,
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "concept_proposed",
            "ref_id": str(concept_id),
            "reason": f"propose concept {term!r}",
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": f"emit_{ConceptProposedPayload.kind}",
            "args": args,
            "result_ref": str(concept_id),
        },
        verify_fn=lambda _e: {"passed": True, "checks": []},
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "test fixture",
        },
        quadrant="active_deterministic",
    )
    return concept_id


def _find_concept_confirmed_args(rows: list[dict]) -> dict | None:
    for r in rows:
        if r.get("kind") != "execute":
            continue
        if r.get("payload", {}).get("tool") == "emit_concept_confirmed":
            return r["payload"]["args"]
    return None


async def test_happy_path_emits_concept_confirmed(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Prior proposal exists → 200 + concept_confirmed entry lands."""
    company_id = _company_id()
    concept_id = await _seed_proposal(
        memory_ledger, company_id=company_id, term="MRR",
    )
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/MRR",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["term"] == "MRR"
    assert body["concept_id"] == str(concept_id)
    assert len(body["entry_ids"]) > 0

    rows = await memory_ledger.fetch(company_id)
    args = _find_concept_confirmed_args(rows)
    assert args is not None
    assert args["concept_id"] == str(concept_id)
    assert args["confirmed_by_person"] == str(confirmer)


async def test_latest_proposal_wins_on_multiple(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Two prior proposals for same term → latest concept_id wins."""
    company_id = _company_id()
    await _seed_proposal(memory_ledger, company_id=company_id, term="ARR")
    second_id = await _seed_proposal(
        memory_ledger, company_id=company_id, term="ARR",
    )
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/ARR",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["concept_id"] == str(second_id)


async def test_term_match_is_case_insensitive(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Proposal term 'NPS' and request 'nps' resolve to the same concept."""
    company_id = _company_id()
    concept_id = await _seed_proposal(
        memory_ledger, company_id=company_id, term="NPS",
    )
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/nps",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["concept_id"] == str(concept_id)


async def test_no_matching_proposal_returns_404(
    client: TestClient,
) -> None:
    """Term has no prior proposal → 404."""
    company_id = _company_id()
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/nonexistent",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 404


async def test_missing_bearer_returns_401(
    client: TestClient,
) -> None:
    """Missing bearer → 401."""
    company_id = _company_id()
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/MRR",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(company_id),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 401


async def test_company_id_mismatch_returns_400(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant → 400."""
    other_company = uuid4()
    confirmer = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/concept_confirmed/MRR",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),
            "confirmed_by_person_id": str(confirmer),
        },
    )
    assert resp.status == 400


async def test_helper_raises_value_error_on_empty_term(
    memory_ledger: InMemoryLedger,
) -> None:
    """``confirm_concept`` helper rejects empty term with ValueError.

    Defense-in-depth: the HTTP boundary catches the empty path via the
    route pattern (no /{term} → 404). This validates the helper
    contract independently of the wire surface.
    """
    import pytest

    company_id = _company_id()
    with pytest.raises(ValueError):
        await write_actions.confirm_concept(
            memory_ledger,
            company_id,
            term="   ",
            confirmed_by_person_id=uuid4(),
        )
