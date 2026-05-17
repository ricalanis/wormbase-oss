"""Data-product + notebook payload validation tests (Block F of the PRD).

Eight new payload kinds — data_product_proposed / _generated / _consumed /
_archived, notebook_proposed / _run / _published / _archived — must each:

* construct from valid args,
* reject extras,
* round-trip via ``model_dump`` → ``model_validate``,
* enforce kind registration in ``KIND_REGISTRY``,
* enforce per-payload enum validators (kind, surface, kernel, status).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

DP_ID = UUID("0190a0a0-0000-7000-8000-0000000000f1")
NB_ID = UUID("0190a0a0-0000-7000-8000-0000000000f2")
PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000f3")
ADMIN_ID = UUID("0190a0a0-0000-7000-8000-0000000000f4")
DOMAIN_ID = UUID("0190a0a0-0000-7000-8000-0000000000f5")
RUN_ID = UUID("0190a0a0-0000-7000-8000-0000000000f6")
SOURCE_ID = UUID("0190a0a0-0000-7000-8000-0000000000f7")


DATA_PRODUCT_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.DataProductProposedPayload,
        {
            "data_product_id": DP_ID,
            "name": "Q3 Net Revenue",
            "kind": "report",
            "requested_by_person_id": PERSON_ID,
            "sources_required": [SOURCE_ID],
            "domain_id": DOMAIN_ID,
            "parameters": {"question": "Q3 net revenue?"},
        },
    ),
    (
        E.DataProductGeneratedPayload,
        {
            "data_product_id": DP_ID,
            "contents_uri": "s3://wb/tenant-x/data-products/dp1/run1.html",
            "content_hash": "deadbeef" * 8,
            "kind": "report",
            "source_hashes": ["abc123", "def456"],
            "generated_by": "worm",
            "duration_ms": 1250,
        },
    ),
    (
        E.DataProductConsumedPayload,
        {
            "data_product_id": DP_ID,
            "consumed_by_person_id": PERSON_ID,
            "surface": "dashboard",
        },
    ),
    (
        E.DataProductConsumedPayload,
        {
            "data_product_id": DP_ID,
            "consumed_by_person_id": PERSON_ID,
            "surface": "chat",
            "channel": "C-finance",
        },
    ),
    (
        # v1.1 Task 4: agent-driven consumption via MCP carries both
        # consumed_by_person_id (back-compat, required) and
        # consumed_by_agent_id (new, additive) plus surface="mcp".
        E.DataProductConsumedPayload,
        {
            "data_product_id": DP_ID,
            "consumed_by_person_id": PERSON_ID,
            "consumed_by_agent_id": "agent_cfo_briefing",
            "surface": "mcp",
        },
    ),
    (
        E.DataProductArchivedPayload,
        {
            "data_product_id": DP_ID,
            "archived_by": ADMIN_ID,
            "reason": "stale",
        },
    ),
    (
        E.NotebookProposedPayload,
        {
            "notebook_id": NB_ID,
            "name": "CFO autoresearch",
            "cells": [
                {"kind": "markdown", "source": "# Hypothesis"},
                {"kind": "code", "source": "x = 1"},
            ],
            "kernel": "python_local",
            "proposed_by_person_id": PERSON_ID,
            "domain_id": DOMAIN_ID,
        },
    ),
    (
        E.NotebookRunPayload,
        {
            "notebook_id": NB_ID,
            "run_id": RUN_ID,
            "cell_outputs": [{"stdout": ""}, {"value": 1}],
            "cell_hashes": ["h1", "h2"],
            "duration_ms": 850,
            "kernel_state_hash": "k" * 64,
            "status": "ok",
            "run_by": "worm",
        },
    ),
    (
        E.NotebookPublishedPayload,
        {
            "notebook_id": NB_ID,
            "run_id": RUN_ID,
            "owner_person_id": PERSON_ID,
            "domain_id": DOMAIN_ID,
            "version": "1",
            "published_by": ADMIN_ID,
        },
    ),
    (
        E.NotebookArchivedPayload,
        {
            "notebook_id": NB_ID,
            "archived_by": ADMIN_ID,
            "reason": "deprecated",
        },
    ),
]


@pytest.mark.parametrize("model,data", DATA_PRODUCT_CASES)
def test_data_product_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", DATA_PRODUCT_CASES)
def test_data_product_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", DATA_PRODUCT_CASES)
def test_data_product_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump(by_alias=True))
    assert again == obj


# ---------------------------------------------------------------------------
# Per-payload enum validators
# ---------------------------------------------------------------------------


def test_data_product_kind_validated() -> None:
    with pytest.raises(ValidationError):
        E.DataProductProposedPayload(
            data_product_id=DP_ID,
            name="x",
            kind="invalid",
            requested_by_person_id=PERSON_ID,
            sources_required=[],
        )


def test_data_product_proposed_payload_round_trips() -> None:
    p = E.DataProductProposedPayload(
        data_product_id=DP_ID,
        name="Q3 Net Revenue",
        kind="report",
        requested_by_person_id=PERSON_ID,
        sources_required=[SOURCE_ID],
    )
    again = E.DataProductProposedPayload.model_validate(p.model_dump(by_alias=True))
    assert again == p


def test_data_product_generated_kind_validated() -> None:
    with pytest.raises(ValidationError):
        E.DataProductGeneratedPayload(
            data_product_id=DP_ID,
            contents_uri="s3://x/y",
            content_hash="abc",
            kind="bogus",
            source_hashes=[],
            generated_by="worm",
            duration_ms=100,
        )


def test_data_product_consumed_surface_validated() -> None:
    with pytest.raises(ValidationError):
        E.DataProductConsumedPayload(
            data_product_id=DP_ID,
            consumed_by_person_id=PERSON_ID,
            surface="bogus",
        )


def test_data_product_consumed_agent_id_defaults_to_none() -> None:
    """v1.1 Task 4: ``consumed_by_agent_id`` is additive with default None.

    Pre-fix payloads omitted the field; per schema-evolution doctrine
    Rule 2, the new field must have a default so existing entries
    roundtrip unchanged.
    """
    p = E.DataProductConsumedPayload(
        data_product_id=DP_ID,
        consumed_by_person_id=PERSON_ID,
        surface="dashboard",
    )
    assert p.consumed_by_agent_id is None
    again = E.DataProductConsumedPayload.model_validate(p.model_dump(by_alias=True))
    assert again == p
    assert again.consumed_by_agent_id is None


def test_data_product_consumed_agent_id_roundtrips() -> None:
    """v1.1 Task 4: agent-driven consumption carries both fields."""
    p = E.DataProductConsumedPayload(
        data_product_id=DP_ID,
        consumed_by_person_id=PERSON_ID,
        consumed_by_agent_id="agent_cfo_briefing",
        surface="mcp",
    )
    again = E.DataProductConsumedPayload.model_validate(p.model_dump(by_alias=True))
    assert again == p
    assert again.consumed_by_agent_id == "agent_cfo_briefing"
    assert again.surface == "mcp"


def test_data_product_consumed_mcp_surface_accepted() -> None:
    """v1.1 Task 4: ``"mcp"`` is now a valid surface (additive enum extension)."""
    p = E.DataProductConsumedPayload(
        data_product_id=DP_ID,
        consumed_by_person_id=PERSON_ID,
        surface="mcp",
    )
    assert p.surface == "mcp"


def test_notebook_kernel_validated() -> None:
    with pytest.raises(ValidationError):
        E.NotebookProposedPayload(
            notebook_id=NB_ID,
            name="x",
            cells=[],
            kernel="invalid",
            proposed_by_person_id=PERSON_ID,
        )


def test_notebook_run_status_validated() -> None:
    with pytest.raises(ValidationError):
        E.NotebookRunPayload(
            notebook_id=NB_ID,
            run_id=RUN_ID,
            cell_outputs=[],
            cell_hashes=[],
            duration_ms=10,
            kernel_state_hash="x",
            status="invalid",
            run_by="worm",
        )


def test_notebook_published_carries_version() -> None:
    p = E.NotebookPublishedPayload(
        notebook_id=NB_ID,
        run_id=RUN_ID,
        owner_person_id=PERSON_ID,
        version="1",
        published_by=ADMIN_ID,
    )
    again = E.NotebookPublishedPayload.model_validate(p.model_dump(by_alias=True))
    assert again == p
    assert again.version == "1"


def test_data_product_kind_string() -> None:
    """Kind has no `emit_` prefix — that's applied by the write primitive."""
    assert E.DataProductProposedPayload.kind == "data_product_proposed"
    assert E.DataProductGeneratedPayload.kind == "data_product_generated"
    assert E.DataProductConsumedPayload.kind == "data_product_consumed"
    assert E.DataProductArchivedPayload.kind == "data_product_archived"
    assert E.NotebookProposedPayload.kind == "notebook_proposed"
    assert E.NotebookRunPayload.kind == "notebook_run"
    assert E.NotebookPublishedPayload.kind == "notebook_published"
    assert E.NotebookArchivedPayload.kind == "notebook_archived"


def test_data_product_negative_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        E.DataProductGeneratedPayload(
            data_product_id=DP_ID,
            contents_uri="s3://x/y",
            content_hash="h",
            kind="report",
            source_hashes=[],
            generated_by="worm",
            duration_ms=-1,
        )


def test_notebook_run_negative_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        E.NotebookRunPayload(
            notebook_id=NB_ID,
            run_id=RUN_ID,
            cell_outputs=[],
            cell_hashes=[],
            duration_ms=-5,
            kernel_state_hash="x",
            status="ok",
            run_by="worm",
        )
