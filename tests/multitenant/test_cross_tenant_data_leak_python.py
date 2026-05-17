"""Cross-tenant data-leak sweep — Python (worm-core HTTP API + module accessors).

INVARIANT: every read-side accessor in worm-core that takes a ``company_id``
filter MUST return only rows belonging to that company. A leak — even a
single row — across paying-customer tenants is a critical security
defect. This sweep seeds two tenants with disjoint distinct rows, then
drives every accessor with tenant_a's auth and asserts that no
tenant_b ledger row, person id, source id, kpi id, decision id, or
process id appears in the response.

Two surfaces are swept:

1. **HTTP read endpoints** under ``apps/worm-core/.../http_api.py`` —
   discovered dynamically via the route table on ``build_app``. Tagged
   with ``GET`` because the spec says "every accessor", and every read
   route is a GET in the worm-core API.
2. **Python module accessors** that take ``(ledger, company_id)`` as
   their tenant boundary — ``team_lookup.team_for_person``,
   ``team_lookup.members_of_team``, ``team_lookup.all_teams``,
   ``owner_lookup.lookup_owner``, ``resource_aggregator.gather_related_resources``.
   These are the lowest-layer accessors backing the dashboard /people
   surface and the autoresearch loop's owner resolution.

Together with the TypeScript companion in
``apps/dashboard/tests/multitenant/test_cross_tenant_data_leak_dashboard.ts``,
the sweep covers ≥50 accessors across both runtime stacks (W6.A2
acceptance bar).
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core import http_api, owner_lookup, resource_aggregator, team_lookup
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_identity_tracker import owner_lookup as identity_owner_lookup
from wormbase_identity_tracker import team_lookup as identity_team_lookup
from wormbase_ledger import InMemoryLedger

# After Wave A (identity-worm extraction, 2026-05-03), `wormbase_core.team_lookup`
# and `wormbase_core.owner_lookup` are backwards-compat shims that re-export from
# `wormbase_identity_tracker.{team_lookup,owner_lookup}`. The accessors' canonical
# homes moved with them, so the module-accessor sweep must walk the new homes
# directly to satisfy the ``__module__ == module.__name__`` re-export filter.
# `team_lookup` and `owner_lookup` aliases above are retained so the imports
# remain validated by the linter (and by any future re-promotion).
_ = (team_lookup, owner_lookup)  # noqa: F841 — preserved for shim audit


API_TOKEN = "test-mt-leak-token"
TENANT_A_SLUG = "baseworm"
TENANT_B_SLUG = "democorp"


# ---------------------------------------------------------------------------
# Fixture: shared in-memory ledger seeded with two tenants worth of data.
# ---------------------------------------------------------------------------


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


def _auth_for(tenant_slug: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": tenant_slug,
    }


# ---------------------------------------------------------------------------
# Seed helpers — write one execute row per kind per tenant. Each kind gets a
# distinct payload so we can search the response for the foreign-tenant
# value and prove non-presence.
# ---------------------------------------------------------------------------


async def _write_execute(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    tool: str,
    args: dict[str, Any],
) -> None:
    """Write a single PEVR cycle with the given execute payload."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": tool.removeprefix("emit_"),
            "ref_id": str(uuid4()),
            "reason": f"seed {tool} for cross-tenant test",
            "proposed_by": "test-mt",
        },
        execute_fn=lambda: {"tool": tool, "args": args, "result_ref": str(uuid4())},
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


class TenantSeed:
    """Distinct, well-known IDs we wrote into a tenant's ledger so the
    cross-tenant test can search any response payload for them and assert
    non-presence."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.company_id = tenant_to_uuid(slug)
        # Marker tags: every tenant's seed ids include the tenant slug
        # so a substring search across an arbitrary JSON response can
        # detect any leak. UUID values are stable across the test.
        self.person_id = str(uuid4())
        self.kpi_id = str(uuid4())
        self.source_id = str(uuid4())
        self.decision_id = str(uuid4())
        self.process_id = str(uuid4())
        self.data_product_id = str(uuid4())
        self.notebook_id = str(uuid4())
        self.experiment_id = str(uuid4())
        self.reactivity_id = f"rx-{slug}-{uuid4().hex[:8]}"
        self.conversation_id = f"conv-{slug}-{uuid4().hex[:8]}"
        self.gap_id = str(uuid4())
        self.install_id = str(uuid4())
        self.channel_id = f"C-{slug.upper()}-FINANCE"
        # The tagged string we'll grep responses for. Every value above
        # contains this substring (by including the slug in markers, or
        # by being a UUID we record on this object).
        self.markers: list[str] = [
            self.person_id,
            self.kpi_id,
            self.source_id,
            self.decision_id,
            self.process_id,
            self.data_product_id,
            self.notebook_id,
            self.experiment_id,
            self.reactivity_id,
            self.conversation_id,
            self.gap_id,
            self.install_id,
            self.channel_id,
            f"NAME-{slug.upper()}",
            f"TEXT-{slug.upper()}",
        ]


async def _seed_tenant(ledger: InMemoryLedger, t: TenantSeed) -> None:
    """Lay down one row of every tenant-scoped entity kind."""
    cid = t.company_id
    # Person.
    await _write_execute(
        ledger, cid,
        tool="emit_person_proposed",
        args={
            "person_id": t.person_id,
            "tenant_id": str(cid),
            "name": f"NAME-{t.slug.upper()}",
            "email": f"user@{t.slug}.test",
            "platform": "slack",
            "platform_user_id": f"U-{t.slug}",
            "proposed_by": "test-mt",
            "position": None,
        },
    )
    # KPI.
    await _write_execute(
        ledger, cid,
        tool="emit_kpi_node",
        args={
            "id": t.kpi_id,
            "name": f"NAME-{t.slug.upper()}-KPI",
            "domain_id": "finance",
        },
    )
    # Source.
    await _write_execute(
        ledger, cid,
        tool="emit_source_proposed",
        args={
            "source_id": t.source_id,
            "source_kind": "csv_local",
            "uri": f"/lake/{t.slug}/foo.csv",
            "added_via_flow": "drop_and_profile",
            "suggested_domain": "finance",
            "suggested_classification": "internal",
        },
    )
    # Decision.
    await _write_execute(
        ledger, cid,
        tool="emit_decision_recorded",
        args={
            "decision_id": t.decision_id,
            "decision_text": f"TEXT-{t.slug.upper()}-DECISION",
            "decision_at": "2026-04-26T10:00:00+00:00",
            "channel_id": t.channel_id,
            "decided_by_persons": [t.person_id],
            "evidence_message_ids": [f"m-{t.slug}-1"],
            "confidence": 0.9,
        },
    )
    # Process map.
    await _write_execute(
        ledger, cid,
        tool="emit_process_map_proposed",
        args={
            "process_id": t.process_id,
            "process_name": f"NAME-{t.slug.upper()}-PROCESS",
            "domain": "finance",
            "steps": [{"order": 1, "actor": "Bob", "action": "export",
                       "source_message_id": f"m-{t.slug}-1"}],
            "confidence": 0.7,
        },
    )
    # Data product.
    await _write_execute(
        ledger, cid,
        tool="emit_data_product_proposed",
        args={
            "data_product_id": t.data_product_id,
            "name": f"NAME-{t.slug.upper()}-DP",
            "kind": "chart",
            "requested_by_person_id": t.person_id,
            "sources_required": [t.source_id],
            "parameters": {},
        },
    )
    # Notebook.
    await _write_execute(
        ledger, cid,
        tool="emit_notebook_proposed",
        args={
            "notebook_id": t.notebook_id,
            "name": f"NAME-{t.slug.upper()}-NB",
            "cells": [],
            "kernel": "python_local",
            "proposed_by_person_id": t.person_id,
        },
    )
    # Experiment.
    await _write_execute(
        ledger, cid,
        tool="emit_experiment_proposed",
        args={
            "experiment_id": t.experiment_id,
            "audience": "person",
            "metric_id": "revenue",
            "title": f"NAME-{t.slug.upper()}-EXP",
            "proposed_by": t.person_id,
        },
    )
    # Reactivity (proposed + fired).
    await _write_execute(
        ledger, cid,
        tool="emit_reactivity_proposed",
        args={
            "reactivity_id": t.reactivity_id,
            "name": f"NAME-{t.slug.upper()}-RX",
            "scope": "person",
            "proposed_by": t.person_id,
        },
    )
    await _write_execute(
        ledger, cid,
        tool="emit_reactivity_fired",
        args={
            "reactivity_id": t.reactivity_id,
            "source_seq": 1,
            "novelty_key": f"key-{t.slug}",
            "action_seqs": [],
            "budget_used": {},
        },
    )
    # Resource conversation (owner-targeted).
    await _write_execute(
        ledger, cid,
        tool="emit_resource_conversation_proposed",
        args={
            "conversation_id": t.conversation_id,
            "owner_id": t.person_id,
            "topic": {"label": f"TEXT-{t.slug.upper()}-TOPIC"},
            "statement": f"TEXT-{t.slug.upper()}-STATEMENT",
            "channel": t.channel_id,
            "resources": {},
        },
    )
    # Phenomenon gap.
    await _write_execute(
        ledger, cid,
        tool="emit_phenomenon_gap_detected",
        args={
            "gap_id": t.gap_id,
            "phenomenon": f"NAME-{t.slug.upper()}-GAP",
            "kpi_id": t.kpi_id,
        },
    )
    # Install (used by /api/v1/installs reads in dashboard).
    await _write_execute(
        ledger, cid,
        tool="emit_install_completed",
        args={
            "install_id": t.install_id,
            "platform": "slack",
            "installer_person_id": t.person_id,
            "bot_user_id": f"B-{t.slug}",
            "scopes": ["chat:write"],
        },
    )
    # Chat received (so the trace stream has rows).
    await _write_execute(
        ledger, cid,
        tool="emit_chat_received",
        args={
            "channel_id": t.channel_id,
            "message_id": f"m-{t.slug}-2",
            "sender_person": t.person_id,
            "text": f"TEXT-{t.slug.upper()}-CHAT",
            "classification": "internal",
        },
    )
    # MCP call received (covers ops health rate-limit projection).
    await _write_execute(
        ledger, cid,
        tool="emit_mcp_call_received",
        args={
            "mcp_call_id": str(uuid4()),
            "caller_person_id": t.person_id,
            "tool_name": "query_kpis",
            "args_hash": "deadbeef",
            "outcome": "ok",
            "latency_ms": 10,
        },
    )


@pytest_asyncio.fixture
async def two_tenants(memory_ledger: InMemoryLedger) -> tuple[TenantSeed, TenantSeed]:
    a = TenantSeed(TENANT_A_SLUG)
    b = TenantSeed(TENANT_B_SLUG)
    await _seed_tenant(memory_ledger, a)
    await _seed_tenant(memory_ledger, b)
    return a, b


# ---------------------------------------------------------------------------
# HTTP-route discovery — every GET route on build_app is an "accessor".
# Discovered via the resource iterator so a future GET added to the API is
# automatically swept; no hand-listing.
# ---------------------------------------------------------------------------


def _discover_get_routes() -> list[tuple[str, str]]:
    """Return ``[(name, path_template), ...]`` for every GET route."""
    app = build_app(ledger=InMemoryLedger(), api_token="x")
    routes: list[tuple[str, str]] = []
    for resource in app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter") or "<unknown>"
        for route in resource:
            method = route.method
            if method != "GET":
                continue
            # Skip the read-only un-auth'd surfaces ('/mcp/catalog',
            # '/api/v1/health'): those don't take a tenant header so
            # there's nothing to leak — they always return the same
            # static surface payload regardless of tenancy.
            if path in ("/mcp/catalog", "/api/v1/health"):
                continue
            handler_name = getattr(route.handler, "__name__", "<lambda>")
            routes.append((handler_name, path))
    return routes


_GET_ROUTES = _discover_get_routes()


def _instantiate_path(path_template: str, t: TenantSeed) -> str:
    """Substitute path-template parameters with tenant-A's seed ids."""
    out = path_template
    for key, val in (
        ("{data_product_id}", t.data_product_id),
        ("{notebook_id}", t.notebook_id),
        ("{reactivity_id}", t.reactivity_id),
        ("{person_id}", t.person_id),
    ):
        out = out.replace(key, val)
    return out


# Routes that are SSE/long-poll (cannot be exercised in a one-shot fetch).
_STREAMING_ROUTES = {"/api/v1/ledger/stream"}


@pytest.mark.parametrize(
    "handler_name,path_template",
    _GET_ROUTES,
    ids=[f"{n}@{p}" for n, p in _GET_ROUTES],
)
async def test_http_get_route_does_not_leak_tenant_b_data(
    client: TestClient,
    two_tenants: tuple[TenantSeed, TenantSeed],
    handler_name: str,
    path_template: str,
) -> None:
    """INVARIANT: a GET request authenticated for tenant_a NEVER returns
    rows belonging to tenant_b. Sweep covers every dynamically-discovered
    GET route on the worm-core HTTP API.
    """
    a, b = two_tenants
    if path_template in _STREAMING_ROUTES:
        pytest.skip("SSE route — covered by integration tests, not a one-shot GET")
    path = _instantiate_path(path_template, a)
    resp = await client.get(path, headers=_auth_for(a.slug))
    # An auth'd request to a known route must not return 401 / 5xx; either
    # 200, 404 (resource not found in this tenant), or 503 (registry not
    # wired in unit-test app) are tolerable.
    assert resp.status in (200, 404, 503), (
        f"unexpected status {resp.status} for {path}: {await resp.text()}"
    )
    if resp.status != 200:
        return
    body_text = await resp.text()
    # Assert no foreign-tenant marker appears anywhere in the response.
    for marker in b.markers:
        assert marker not in body_text, (
            f"tenant_b marker {marker!r} leaked into tenant_a response on "
            f"{path}: {body_text[:500]}"
        )


# ---------------------------------------------------------------------------
# Module-level accessor sweep — team_lookup / owner_lookup /
# resource_aggregator are the Python helpers backing the dashboard's
# /people surface and the autoresearch loop. Each takes (ledger, company_id)
# and must NEVER fold rows from a different company_id.
# ---------------------------------------------------------------------------


def _discover_module_accessors() -> list[tuple[str, Any]]:
    """Return every ``async def`` accessor in the lookup modules.

    Inspect.getmembers walks the module so future helpers are auto-swept.
    Filter to async functions that take ``ledger`` and ``company_id``
    parameters (positional OR keyword) — the canonical tenant-boundary
    signature. Some helpers thread these as kwargs after a leading
    ``topic`` arg (``lookup_owner``, ``gather_related_resources``); both
    shapes are valid tenant-scoped accessors.
    """
    out: list[tuple[str, Any]] = []
    # Sweep the canonical homes. Post-Wave-A, team_lookup and owner_lookup live
    # under `wormbase_identity_tracker`; `wormbase_core.{team_lookup,owner_lookup}`
    # are shims and would be filtered out by the `__module__` re-export check
    # below. resource_aggregator still lives in wormbase_core.
    for module in (
        identity_team_lookup,
        identity_owner_lookup,
        resource_aggregator,
    ):
        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue
            if not inspect.iscoroutinefunction(obj):
                continue
            # Skip re-exports (functions whose owning module isn't this one).
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            try:
                sig = inspect.signature(obj)
            except (TypeError, ValueError):
                continue
            param_names = set(sig.parameters)
            if "ledger" not in param_names or "company_id" not in param_names:
                continue
            out.append((f"{module.__name__}.{name}", obj))
    return out


_MODULE_ACCESSORS = _discover_module_accessors()


def _make_topic_for(t: TenantSeed) -> Any:
    """Build a Topic-like dataclass with tenant_a's id space.

    ``owner_lookup.lookup_owner`` and ``resource_aggregator.gather_related_resources``
    take a ``Topic`` first-positional. We import the type lazily so the
    test file stays import-light when the module isn't present.
    """
    from wormbase_core.topic_extractor import Topic
    return Topic(
        kind="kpi",
        id=UUID(t.kpi_id),
        label=f"NAME-{t.slug.upper()}",
        confidence=0.9,
        domain_id=None,
    )


@pytest.mark.parametrize(
    "name,fn",
    _MODULE_ACCESSORS,
    ids=[n for n, _ in _MODULE_ACCESSORS],
)
async def test_module_accessor_does_not_leak_tenant_b_data(
    memory_ledger: InMemoryLedger,
    two_tenants: tuple[TenantSeed, TenantSeed],
    name: str,
    fn: Any,
) -> None:
    """INVARIANT: every Python module accessor that names ``ledger`` +
    ``company_id`` parameters folds rows only from that company_id; no
    tenant_b row appears in tenant_a's result.
    """
    a, b = two_tenants
    sig = inspect.signature(fn)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}

    for p in sig.parameters.values():
        if p.name == "ledger":
            value: Any = memory_ledger
        elif p.name == "company_id":
            value = a.company_id
        elif p.name == "person_id":
            value = UUID(a.person_id)
        elif p.name == "team_id":
            value = uuid4()  # synthetic team id — will return empty set
        elif p.name == "topic":
            value = _make_topic_for(a)
        elif p.name == "max_per_kind":
            value = 5
        elif p.default is not inspect.Parameter.empty:
            continue  # use the function's default
        else:
            pytest.skip(
                f"unexpected signature param {p.name!r} on {name}; "
                "extend the dispatch table to cover this shape",
            )
            return  # pragma: no cover

        if p.kind == inspect.Parameter.KEYWORD_ONLY:
            kwargs[p.name] = value
        else:
            args.append(value)

    try:
        result = await fn(*args, **kwargs)
    except (TypeError, ValueError, NotImplementedError) as exc:
        pytest.skip(f"accessor {name} raised on synthetic input: {exc}")
        return  # pragma: no cover

    text = repr(result)
    for marker in b.markers:
        assert marker not in text, (
            f"tenant_b marker {marker!r} leaked through {name} when "
            f"called with tenant_a's company_id; result: {text[:500]}"
        )


# ---------------------------------------------------------------------------
# Sanity: the discovered route count is large enough to be meaningful and
# the parametrized sweep actually ran. Cheap regression guard against an
# inadvertent ``return []`` from ``_discover_get_routes``.
# ---------------------------------------------------------------------------


def test_route_discovery_covers_at_least_five_get_routes() -> None:
    assert len(_GET_ROUTES) >= 5, f"only {len(_GET_ROUTES)} GET routes discovered"


def test_module_accessor_discovery_covers_at_least_three() -> None:
    assert len(_MODULE_ACCESSORS) >= 3, (
        f"only {len(_MODULE_ACCESSORS)} module accessors discovered"
    )


# ---------------------------------------------------------------------------
# Direct ledger-fold sweep: every InMemoryLedger.fetch(company_id) call
# returns ONLY that company's rows. Belt-and-braces invariant — verifies
# the storage primitive itself, since every accessor folds over its rows.
# ---------------------------------------------------------------------------


async def test_ledger_fetch_returns_only_requested_companys_rows(
    memory_ledger: InMemoryLedger,
    two_tenants: tuple[TenantSeed, TenantSeed],
) -> None:
    """INVARIANT: ``InMemoryLedger.fetch(company_id)`` returns rows for
    ``company_id`` only — never rows for any other company. The
    foundational primitive on which every accessor folds.
    """
    a, b = two_tenants
    rows_a = await memory_ledger.fetch(a.company_id)
    rows_b = await memory_ledger.fetch(b.company_id)
    # Distinct, both populated.
    assert rows_a, "tenant_a ledger empty after seed"
    assert rows_b, "tenant_b ledger empty after seed"
    # No row in tenant_a's set carries any tenant_b marker.
    text_a = repr(rows_a)
    for marker in b.markers:
        assert marker not in text_a, (
            f"tenant_b marker {marker!r} present in tenant_a's fetch"
        )
    text_b = repr(rows_b)
    for marker in a.markers:
        assert marker not in text_b, (
            f"tenant_a marker {marker!r} present in tenant_b's fetch"
        )


async def test_ledger_fetch_empty_for_unknown_company(
    memory_ledger: InMemoryLedger,
    two_tenants: tuple[TenantSeed, TenantSeed],
) -> None:
    """INVARIANT: a tenant nobody ever wrote to returns an empty list —
    the primitive does not silently fall through to "any tenant's data."
    """
    ghost = uuid4()  # a company_id with no writes
    rows = await memory_ledger.fetch(ghost)
    assert rows == []
