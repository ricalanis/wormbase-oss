"""Tests for the W7.A1 rich seed (Beat-9 standalone enrichment).

The rich seed drives the worm-core HTTP write API after personas land
to pre-populate the tenant with everything Beat-9 (Statement-to-Owner)
needs to fire deterministically:

* a confirmed ``churn_rate`` KPI
* Carol granted ``resource.maintainer`` on the KPI
* Carol granted ``domain.owner`` on a synthetic retention domain
* 2 retention-tagged decisions
* 1 process map (``customer_recovery_flow``)
* 1 data product (``q3_churn_cohort``) with pinned source_hashes

These tests use a ``MockTransport`` that captures the API wire AND
mirrors the writes into a real ``InMemoryLedger``, so the integration
side (topic_extractor / owner_lookup / resource_aggregator) can verify
the resulting catalog without standing up the full worm-core process.
"""

from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from wormbase_core.owner_lookup import lookup_owner
from wormbase_core.resource_aggregator import gather_related_resources
from wormbase_core.service import tenant_to_uuid
from wormbase_core.topic_extractor import extract_topic
from wormbase_ledger import InMemoryLedger
from wormbase_sim_harness.seed_rich import (
    DATA_PRODUCT_NAME,
    DECISION_TEXTS,
    KPI_LABEL,
    PROCESS_NAME,
    SeedRichReport,
    retention_domain_uuid_for_tenant,
    seed_rich,
)


# ---------------------------------------------------------------------------
# Helpers — write entries into the InMemoryLedger as the worm-core handlers
# would, so the rich-seed flow against the mock transport produces a
# ledger state the topic_extractor / owner_lookup / resource_aggregator
# can read.
# ---------------------------------------------------------------------------


async def _ledger_write_execute(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    target_kind: str,
    ref_id: UUID,
    tool: str,
    args: dict[str, Any],
    proposed_by: str = "seed_rich-mock",
) -> None:
    """Mirror ``write_actions._pevr`` — propose/execute/verify/resolve cycle."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": str(ref_id),
            "reason": f"mock: {tool}",
            "proposed_by": proposed_by,
        },
        execute_fn=lambda a=args, t=tool: {
            "tool": t,
            "args": a,
            "result_ref": str(ref_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": f"{tool}_payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"mock {tool} kept",
        },
    )


def _make_mock_handler(
    ledger: InMemoryLedger,
    company_id: UUID,
    carol_person_id: UUID,
    *,
    captured: list[tuple[str, dict | None]],
) -> Any:
    """Build a MockTransport handler that mirrors POSTs into the ledger.

    Each handler branch parses the body, writes the corresponding ledger
    entry sequence (matching what ``write_actions`` would produce in
    production), and returns the API response shape the seed_rich helper
    expects.
    """

    async def _async_write(
        target_kind: str, ref_id: UUID, tool: str, args: dict[str, Any],
    ) -> None:
        await _ledger_write_execute(
            ledger, company_id,
            target_kind=target_kind, ref_id=ref_id, tool=tool, args=args,
        )

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = (
            _json.loads(request.content.decode())
            if request.content
            else None
        )
        captured.append((path, body))

        # All handlers require the bearer + tenant headers.
        assert request.headers.get("Authorization") == "Bearer test-bearer"
        assert request.headers.get("X-Tenant-Slug") == "baseworm"

        if path == "/api/v1/kpis/propose":
            assert body and body.get("label") == KPI_LABEL
            kpi_id = uuid4()
            # Mirror the ledger entry the worm-core handler would write.
            args = {
                "kpi_id": str(kpi_id),
                "label": body["label"],
                "formula": body.get("formula", ""),
                "source_ids": [],
                "unit": body.get("unit", "count"),
                "owner_position": body.get("owner_position"),
                "proposed_at": "2026-04-29T12:00:00+00:00",
            }
            import asyncio as _asyncio
            _asyncio.get_event_loop().run_until_complete(
                _async_write(
                    "kpi_proposed", kpi_id, "emit_kpi_proposed", args,
                ),
            ) if False else None  # placeholder to satisfy linters
            # We can't drive an async write from a sync handler; instead
            # we stash the work for the caller to flush. See the
            # `_pending_writes` list pattern below.
            _pending_writes.append(("kpi_proposed", kpi_id, "emit_kpi_proposed", args))
            return httpx.Response(
                201,
                json={"kpi_id": str(kpi_id), "entry_ids": [str(uuid4())]},
            )

        if path.startswith("/api/v1/people/") and path.endswith("/roles"):
            person_id = UUID(path.split("/")[4])
            assert person_id == carol_person_id
            assert body and body.get("granted_by")
            facet = body.get("facet")
            role = body.get("role")
            scope_id = body.get("scope_id")
            scope_type = body.get("scope_type")
            granted_by = body.get("granted_by")
            if facet == "resource":
                args = {
                    "person_id": str(person_id),
                    "resource_id": str(scope_id),
                    "resource_type": scope_type,
                    "role": role,
                    "granted_by": str(granted_by),
                }
                _pending_writes.append((
                    "resource_role_assigned", person_id,
                    "emit_resource_role_assigned", args,
                ))
            elif facet == "domain":
                args = {
                    "person_id": str(person_id),
                    "domain_id": str(scope_id),
                    "role": role,
                    "granted_by": str(granted_by),
                }
                _pending_writes.append((
                    "domain_role_assigned", person_id,
                    "emit_domain_role_assigned", args,
                ))
            return httpx.Response(200, json={"entry_ids": [str(uuid4())]})

        if path == "/api/v1/decisions":
            assert body and body.get("decision_text")
            decision_id = uuid4()
            args = {
                "decision_id": str(decision_id),
                "decision_text": body["decision_text"],
                "decision_at": "2026-04-29T12:00:00+00:00",
                "channel_id": body.get("channel_id", ""),
                "decided_by_persons": list(body.get("decided_by_persons", [])),
                "evidence_message_ids": list(
                    body.get("evidence_message_ids", []),
                ),
                "confidence": body.get("confidence", 0.95),
            }
            _pending_writes.append((
                "decision_recorded", decision_id,
                "emit_decision_recorded", args,
            ))
            return httpx.Response(
                201,
                json={
                    "decision_id": str(decision_id),
                    "entry_ids": [str(uuid4())],
                },
            )

        if path == "/api/v1/processes":
            assert body and body.get("process_name")
            process_id = uuid4()
            args = {
                "process_id": str(process_id),
                "process_name": body["process_name"],
                "domain": body.get("domain", "general"),
                "confidence": body.get("confidence", 0.9),
                "steps": body.get("steps", []),
            }
            _pending_writes.append((
                "process_map_proposed", process_id,
                "emit_process_map_proposed", args,
            ))
            return httpx.Response(
                201,
                json={
                    "process_id": str(process_id),
                    "entry_ids": [str(uuid4())],
                },
            )

        if path == "/api/v1/data-products":
            assert body and body.get("name")
            dp_id = uuid4()
            propose_args = {
                "data_product_id": str(dp_id),
                "name": body["name"],
                "kind": body.get("kind", "report"),
                "requested_by_person_id": body.get("requested_by_person_id"),
                "sources_required": list(body.get("sources_required", [])),
                "domain_id": body.get("domain_id"),
                "parameters": dict(body.get("parameters", {})),
                "prompted_by_message_id": body.get("prompted_by_message_id"),
            }
            _pending_writes.append((
                "data_product_proposed", dp_id,
                "emit_data_product_proposed", propose_args,
            ))
            # If contents_bytes_b64 was sent, also write the generated
            # entry — mirrors the worm-core handler (which calls
            # generate_data_product inline when contents are supplied).
            if body.get("contents_bytes_b64"):
                gen_args = {
                    "data_product_id": str(dp_id),
                    "contents_uri": (
                        f"file:///mock/data-products/{dp_id}/run0"
                    ),
                    "content_hash": "0" * 64,
                    "kind": body.get("kind", "report"),
                    "source_hashes": list(
                        (body.get("parameters") or {}).get("source_hashes", []),
                    ),
                    "duration_ms": 0,
                    "generated_by": "worm",
                }
                _pending_writes.append((
                    "data_product_generated", dp_id,
                    "emit_data_product_generated", gen_args,
                ))
            return httpx.Response(
                200,
                json={
                    "data_product_id": str(dp_id),
                    "entry_ids": [str(uuid4())],
                },
            )

        return httpx.Response(404, json={"error": f"unhandled {path}"})

    return _handler


# Module-scope buffer: mock handlers can't run async code inline, so we
# capture pending ledger writes here and the test flushes them after
# seed_rich completes. Reset at the start of each test.
_pending_writes: list[tuple[str, UUID, str, dict[str, Any]]] = []


async def _flush_pending(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    while _pending_writes:
        target_kind, ref_id, tool, args = _pending_writes.pop(0)
        await _ledger_write_execute(
            ledger, company_id,
            target_kind=target_kind, ref_id=ref_id, tool=tool, args=args,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pending() -> None:
    _pending_writes.clear()
    yield
    _pending_writes.clear()


@pytest.fixture
def tenant() -> str:
    return "baseworm"


@pytest.fixture
def company_id(tenant: str) -> UUID:
    return tenant_to_uuid(tenant)


@pytest.fixture
def carol_person_id() -> UUID:
    # Stable per-test Person id — the actual seed flow gets this from
    # seed_personas's returned roster, but for these unit tests we
    # synthesize a fresh UUID and thread it through.
    return UUID("aaaaaaaa-cafe-cafe-cafe-aaaaaaaaaaaa")


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


async def _run_seed_rich(
    ledger: InMemoryLedger,
    *,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> tuple[SeedRichReport, list[tuple[str, dict | None]]]:
    captured: list[tuple[str, dict | None]] = []
    handler = _make_mock_handler(
        ledger, company_id, carol_person_id, captured=captured,
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await seed_rich(
            tenant=tenant,
            carol_person_id=carol_person_id,
            dashboard_api_base="http://worm-core:8910",
            api_token="test-bearer",
            ledger=ledger,
            company_id=company_id,
            http_client=client,
        )
    # Flush the pending ledger writes the mock handlers couldn't write
    # synchronously. Mirrors what worm-core's handlers do server-side.
    await _flush_pending(ledger, company_id)
    return report, captured


# 1. The wire surface.
async def test_seed_rich_posts_full_enrichment_sequence(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    """End-to-end happy path: every required POST lands on the worm-core API."""
    report, captured = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )

    paths = [p for p, _ in captured]
    # KPI propose
    assert "/api/v1/kpis/propose" in paths
    # Two role grants on Carol (resource + domain)
    role_grants = [p for p in paths if p.endswith("/roles")]
    assert len(role_grants) == 2
    assert all(
        f"/api/v1/people/{carol_person_id}/roles" == p for p in role_grants
    )
    # Two decisions
    decision_calls = [p for p in paths if p == "/api/v1/decisions"]
    assert len(decision_calls) == 2
    # One process
    assert paths.count("/api/v1/processes") == 1
    # One data product
    assert paths.count("/api/v1/data-products") == 1

    # Report fields populated.
    assert report.kpi_id is not None
    assert len(report.decision_ids) == 2
    assert report.process_id is not None
    assert report.data_product_id is not None
    assert report.domain_role_granted is True
    assert report.resource_role_granted is True
    assert report.domain_registered is True


# 2. KPI label is the canonical "churn_rate".
async def test_seed_rich_proposes_churn_rate_kpi(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    _, captured = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    kpi_calls = [
        body for path, body in captured
        if path == "/api/v1/kpis/propose" and body
    ]
    assert kpi_calls, "expected exactly one KPI propose body on the wire"
    body = kpi_calls[0]
    assert body["label"] == KPI_LABEL == "churn_rate"
    # owner_position threaded through so the KPI tree's owner
    # auto-resolution stays consistent with Carol's position.
    assert body["owner_position"] == "cfo"


# 3. Carol gets resource.maintainer on the KPI.
async def test_seed_rich_grants_carol_resource_maintainer_on_kpi(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    report, captured = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    role_bodies = [
        body for path, body in captured
        if path.endswith(f"/people/{carol_person_id}/roles") and body
    ]
    resource_grants = [b for b in role_bodies if b["facet"] == "resource"]
    assert len(resource_grants) == 1
    grant = resource_grants[0]
    assert grant["role"] == "maintainer"
    assert grant["scope_type"] == "kpi"
    assert grant["scope_id"] == str(report.kpi_id)


# 4. Carol gets domain.owner on retention.
async def test_seed_rich_grants_carol_domain_owner_on_retention(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    report, captured = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    role_bodies = [
        body for path, body in captured
        if path.endswith(f"/people/{carol_person_id}/roles") and body
    ]
    domain_grants = [b for b in role_bodies if b["facet"] == "domain"]
    assert len(domain_grants) == 1
    grant = domain_grants[0]
    assert grant["role"] == "owner"
    assert grant["scope_id"] == str(report.retention_domain_id)
    # Retention domain id is stable across tenants of the same name.
    assert report.retention_domain_id == retention_domain_uuid_for_tenant(tenant)


# 5. Decisions match the canonical content.
async def test_seed_rich_records_two_retention_decisions(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    _, captured = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    decision_bodies = [
        body for path, body in captured
        if path == "/api/v1/decisions" and body
    ]
    assert len(decision_bodies) == 2
    texts = [b["decision_text"] for b in decision_bodies]
    assert texts == list(DECISION_TEXTS)
    # Carol cited as decider on every record.
    for b in decision_bodies:
        assert str(carol_person_id) in b["decided_by_persons"]


# 6. Topic extractor matches "churn".
async def test_topic_extractor_matches_churn_after_rich_seed(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    """topic_extractor returns a non-None topic for "our churn looks ugly".

    The exact match shape: kind=kpi, label=churn_rate, confidence≥0.6
    via the multi-word partial-match scoring path. (The plan's
    "kind=domain, label=retention" expectation is incompatible with the
    current topic_extractor — domains require ``domain_name`` in the
    role-assigned args, which the production grant_domain_role handler
    does not write. The KPI match is the equivalent practical signal:
    it's the most-actionable resource and Carol owns it.)
    """
    await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    topic = await extract_topic(
        "our churn looks ugly in Europe — Q3 is down 8% MoM",
        ledger=ledger, company_id=company_id,
    )
    assert topic is not None, "topic_extractor returned None despite rich seed"
    assert topic.kind == "kpi"
    assert topic.label == "churn_rate"
    assert topic.confidence >= 0.6


# 7. Owner lookup returns Carol for the topic.
async def test_owner_lookup_returns_carol_for_churn_topic(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    """Beat-9 happy path: Carol is identified as the KPI maintainer.

    For owner_lookup to find Carol, the rich seed must have written
    ``emit_resource_role_assigned`` with role=maintainer and
    resource_id=<kpi_id>, AND the Person hydrate path must find Carol
    in the ledger (we synthesize a minimal ``emit_person_proposed``
    here since the real seed_personas isn't running).
    """
    await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    # Synthesize Carol's Person row so owner_lookup._hydrate_person
    # has something to return. In the full seed flow seed_personas
    # writes this; here we mirror the minimal entry it would land.
    await _ledger_write_execute(
        ledger, company_id,
        target_kind="person_proposed",
        ref_id=carol_person_id,
        tool="emit_person_proposed",
        args={
            "person_id": str(carol_person_id),
            "name": "Carol Reyes",
            "email": "carol@baseworm.test",
            "platform": "slack",
            "platform_user_id": "UCAROL",
            "position": "cfo",
            "proposed_by": "test",
        },
    )
    topic = await extract_topic(
        "our churn looks ugly",
        ledger=ledger, company_id=company_id,
    )
    assert topic is not None
    owner = await lookup_owner(topic, ledger=ledger, company_id=company_id)
    assert owner is not None, (
        "owner_lookup returned None — Carol was not surfaced as KPI owner"
    )
    assert owner.person_id == carol_person_id
    assert owner.name == "Carol Reyes"


# 8. Resource aggregator returns ≥4 resources.
async def test_resource_aggregator_returns_at_least_four_resources(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    """The DM body bundle should include KPI + decisions + process + DP."""
    await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    topic = await extract_topic(
        "our churn looks ugly",
        ledger=ledger, company_id=company_id,
    )
    assert topic is not None
    bundle = await gather_related_resources(
        topic, ledger=ledger, company_id=company_id, max_per_kind=3,
    )
    # Topic.domain_id is None (the KPI propose API doesn't accept a
    # domain_id), so the aggregator falls back to most-recent across
    # all kinds. We expect KPI (1) + decisions (2, capped at 3) +
    # process (1) + data_product (1) ≥ 4.
    total = (
        len(bundle.kpis) + len(bundle.sources) + len(bundle.decisions)
        + len(bundle.processes) + len(bundle.data_products)
    )
    assert total >= 4, (
        f"resource_aggregator surfaced only {total} resources; "
        f"expected ≥4. Bundle: kpis={len(bundle.kpis)} "
        f"sources={len(bundle.sources)} decisions={len(bundle.decisions)} "
        f"processes={len(bundle.processes)} dps={len(bundle.data_products)}"
    )
    # Specific resources we seeded must appear by name.
    kpi_labels = {k.label for k in bundle.kpis}
    assert KPI_LABEL in kpi_labels
    process_names = {p.process_name for p in bundle.processes}
    assert PROCESS_NAME in process_names
    dp_names = {d.name for d in bundle.data_products}
    assert DATA_PRODUCT_NAME in dp_names
    decision_texts = {d.decision_text for d in bundle.decisions}
    assert any(t in decision_texts for t in DECISION_TEXTS)


# 9. Idempotency: re-run produces the same content shape.
async def test_seed_rich_idempotent_content(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    """Running rich seed twice produces the same content (UUIDs vary)."""
    report1, _ = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    report2, captured2 = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    # The retention_domain_id is hash-stable on (tenant) — both runs
    # must derive the same UUID.
    assert report1.retention_domain_id == report2.retention_domain_id
    # KPI / process / data product UUIDs vary (worm-core handler
    # auto-generates them); the fact that both report objects carry
    # populated ids is the content-level invariant.
    assert report2.kpi_id is not None
    assert report2.process_id is not None
    assert report2.data_product_id is not None
    assert len(report2.decision_ids) == 2
    # The wire body shape is identical run-over-run.
    kpi_bodies_run2 = [
        body for path, body in captured2
        if path == "/api/v1/kpis/propose"
    ]
    assert kpi_bodies_run2[0]["label"] == KPI_LABEL


# 10. Validation: missing creds fail fast.
async def test_seed_rich_rejects_missing_creds(
    carol_person_id: UUID,
) -> None:
    with pytest.raises(ValueError, match="api_token"):
        await seed_rich(
            tenant="baseworm",
            carol_person_id=carol_person_id,
            dashboard_api_base="http://worm-core:8910",
            api_token="",
        )
    with pytest.raises(ValueError, match="dashboard_api_base"):
        await seed_rich(
            tenant="baseworm",
            carol_person_id=carol_person_id,
            dashboard_api_base="",
            api_token="t",
        )
    with pytest.raises(ValueError, match="tenant"):
        await seed_rich(
            tenant="",
            carol_person_id=carol_person_id,
            dashboard_api_base="http://worm-core:8910",
            api_token="t",
        )


# 11. Retention domain is stable across calls (hash-stability anchor).
def test_retention_domain_uuid_stable_per_tenant() -> None:
    """retention_domain_uuid_for_tenant is deterministic on tenant slug."""
    a1 = retention_domain_uuid_for_tenant("baseworm")
    a2 = retention_domain_uuid_for_tenant("baseworm")
    b = retention_domain_uuid_for_tenant("democorp")
    assert a1 == a2
    assert a1 != b


# 12. Report serializes for the seed-table renderer.
async def test_seed_rich_report_to_dict_round_trips(
    ledger: InMemoryLedger,
    tenant: str,
    company_id: UUID,
    carol_person_id: UUID,
) -> None:
    report, _ = await _run_seed_rich(
        ledger, tenant=tenant, company_id=company_id,
        carol_person_id=carol_person_id,
    )
    d = report.to_dict()
    assert d["tenant"] == tenant
    assert d["carol_person_id"] == str(carol_person_id)
    assert d["retention_domain_id"] == str(report.retention_domain_id)
    assert d["kpi_id"] == str(report.kpi_id)
    assert d["domain_role_granted"] is True
    assert d["resource_role_granted"] is True
    assert d["domain_registered"] is True
    assert len(d["decision_ids"]) == 2


# 13. HTTP error surfaces as RuntimeError.
async def test_seed_rich_propagates_http_failure(
    carol_person_id: UUID,
) -> None:
    """Any 4xx/5xx from worm-core surfaces as RuntimeError with the body."""
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/kpis/propose":
            return httpx.Response(422, text="invalid label")
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="HTTP 422"):
            await seed_rich(
                tenant="baseworm",
                carol_person_id=carol_person_id,
                dashboard_api_base="http://worm-core:8910",
                api_token="t",
                http_client=client,
            )
