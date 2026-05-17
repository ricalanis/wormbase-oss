"""W5.A2 — topic_extractor unit tests.

Verifies the deterministic semantic match against the org's ontology:
the catalog walk correctly assembles KPIs / sources / domains / processes
from the ledger, and the scoring picks the right topic for canonical
statement shapes.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_core.topic_extractor import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    _build_catalog,
    _CatalogEntry,
    extract_topic,
    match_against_catalog,
)


# ---------------------------------------------------------------------------
# Fixtures — write canonical KPI / source / process / domain entries
# ---------------------------------------------------------------------------


KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")
KPI_ARR = UUID("aaaaaaaa-0000-0000-0000-000000000002")
SOURCE_STRIPE = UUID("bbbbbbbb-0000-0000-0000-000000000001")
PROCESS_RECOVERY = UUID("cccccccc-0000-0000-0000-000000000001")
DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
DOMAIN_FINANCE = UUID("dddddddd-0000-0000-0000-000000000002")


async def _write_kpi(ledger, company_id, kpi_id: UUID, label: str,
                    domain_id: UUID | None = None) -> None:
    args = {
        "id": str(kpi_id),
        "label": label,
        "domain_id": str(domain_id) if domain_id else None,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "kpi_node", "ref_id": str(kpi_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_kpi_node", "args": a, "result_ref": str(kpi_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _write_source(ledger, company_id, source_id: UUID, name: str,
                       domain_id: UUID | None = None) -> None:
    args = {
        "source_id": str(source_id),
        "source_kind": "database",
        "uri": f"postgres://example/{name}",
        "added_via_flow": "dashboard_form",
        "suggested_domain": "ops",
        "suggested_classification": "internal",
        "name": name,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "source_proposed", "ref_id": str(source_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_source_proposed", "args": a,
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )
    if domain_id is not None:
        confirm_args = {
            "source_id": str(source_id),
            "domain_id": str(domain_id),
            "classification": "internal",
            "confirmed_by_person": "00000000-0000-0000-0000-000000000099",
        }
        await ledger.write(
            company_id=company_id,
            propose={"target_kind": "source_confirmed", "ref_id": str(source_id),
                     "reason": "test", "proposed_by": "test"},
            execute_fn=lambda a=confirm_args: {
                "tool": "emit_source_confirmed", "args": a,
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )


async def _write_process(ledger, company_id, process_id: UUID, name: str,
                        domain: str = "retention") -> None:
    args = {
        "process_id": str(process_id),
        "process_name": name,
        "steps": [{"order": 1, "actor": "Alice", "action": "x"}],
        "domain": domain,
        "confidence": 0.8,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "process_map_proposed",
                 "ref_id": str(process_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_process_map_proposed", "args": a,
            "result_ref": str(process_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _write_domain_grant(ledger, company_id, domain_id: UUID,
                              person_id: UUID, label: str) -> None:
    args = {
        "person_id": str(person_id),
        "domain_id": str(domain_id),
        "role": "owner",
        "granted_by": "00000000-0000-0000-0000-000000000099",
        "domain_name": label,  # extra arg for our catalog labelling
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "domain_role_assigned",
                 "ref_id": str(domain_id),
                 "reason": "test", "proposed_by": "test"},
        execute_fn=lambda a=args: {
            "tool": "emit_domain_role_assigned", "args": a,
            "result_ref": str(domain_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


@pytest.fixture
async def seeded_ledger(ledger, company_id):
    """Seed a tenant with a canonical org ontology for matching."""
    person = UUID("eeeeeeee-0000-0000-0000-000000000001")
    await _write_kpi(ledger, company_id, KPI_CHURN, "churn", DOMAIN_RETENTION)
    await _write_kpi(ledger, company_id, KPI_ARR, "ARR", DOMAIN_FINANCE)
    await _write_source(ledger, company_id, SOURCE_STRIPE, "stripe",
                        DOMAIN_FINANCE)
    await _write_process(ledger, company_id, PROCESS_RECOVERY,
                         "customer recovery flow", "retention")
    await _write_domain_grant(ledger, company_id, DOMAIN_RETENTION,
                              person, "retention")
    await _write_domain_grant(ledger, company_id, DOMAIN_FINANCE,
                              person, "finance")
    return ledger


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


async def test_catalog_includes_kpis(seeded_ledger, company_id):
    catalog = await _build_catalog(seeded_ledger, company_id)
    labels = {(c.kind, c.label) for c in catalog}
    assert ("kpi", "churn") in labels
    assert ("kpi", "ARR") in labels


async def test_catalog_includes_sources(seeded_ledger, company_id):
    catalog = await _build_catalog(seeded_ledger, company_id)
    labels = {(c.kind, c.label) for c in catalog}
    assert ("source", "stripe") in labels


async def test_catalog_includes_processes(seeded_ledger, company_id):
    catalog = await _build_catalog(seeded_ledger, company_id)
    labels = {(c.kind, c.label) for c in catalog}
    assert ("process", "customer recovery flow") in labels


async def test_catalog_includes_domains(seeded_ledger, company_id):
    catalog = await _build_catalog(seeded_ledger, company_id)
    labels = {(c.kind, c.label) for c in catalog}
    assert ("domain", "retention") in labels
    assert ("domain", "finance") in labels


async def test_catalog_attaches_kpi_domain(seeded_ledger, company_id):
    catalog = await _build_catalog(seeded_ledger, company_id)
    churn = next(c for c in catalog if c.kind == "kpi" and c.label == "churn")
    assert churn.domain_id == DOMAIN_RETENTION


# ---------------------------------------------------------------------------
# extract_topic — end to end
# ---------------------------------------------------------------------------


async def test_extract_topic_churn_matches_kpi(seeded_ledger, company_id):
    topic = await extract_topic(
        "our churn is up 8% MoM in Europe",
        ledger=seeded_ledger, company_id=company_id,
    )
    assert topic is not None
    assert topic.kind == "kpi"
    assert topic.label == "churn"
    assert topic.confidence >= DEFAULT_CONFIDENCE_THRESHOLD
    assert topic.domain_id == DOMAIN_RETENTION


async def test_extract_topic_arr_matches_kpi(seeded_ledger, company_id):
    topic = await extract_topic(
        "ARR is dropping again, weird",
        ledger=seeded_ledger, company_id=company_id,
    )
    assert topic is not None
    assert topic.kind == "kpi"
    assert topic.label == "ARR"


async def test_extract_topic_stripe_matches_source(seeded_ledger, company_id):
    topic = await extract_topic(
        "Stripe webhook is broken since this morning",
        ledger=seeded_ledger, company_id=company_id,
    )
    assert topic is not None
    assert topic.kind == "source"
    assert topic.label == "stripe"


async def test_extract_topic_irrelevant_chatter_returns_none(
    seeded_ledger, company_id,
):
    topic = await extract_topic(
        "lunch was great today thanks for the coffee",
        ledger=seeded_ledger, company_id=company_id,
    )
    assert topic is None


async def test_extract_topic_empty_message_returns_none(
    seeded_ledger, company_id,
):
    assert await extract_topic("", ledger=seeded_ledger,
                               company_id=company_id) is None
    assert await extract_topic("   ", ledger=seeded_ledger,
                               company_id=company_id) is None


async def test_extract_topic_no_catalog_returns_none(ledger, company_id):
    """Empty tenant: no KPIs, sources, processes — return None."""
    topic = await extract_topic(
        "our churn is up", ledger=ledger, company_id=company_id,
    )
    assert topic is None


async def test_extract_topic_kpi_beats_domain_on_tie(
    seeded_ledger, company_id,
):
    """Both 'retention' (domain) and 'customer recovery flow' (process) are
    in the catalog. A statement only naming retention should land on
    the domain — but if a more-specific KPI/process matches, that wins."""
    topic = await extract_topic(
        "the customer recovery flow needs an update",
        ledger=seeded_ledger, company_id=company_id,
    )
    assert topic is not None
    assert topic.kind == "process"
    assert topic.label == "customer recovery flow"


async def test_extract_topic_below_threshold_returns_none(
    seeded_ledger, company_id,
):
    """A custom high threshold suppresses partial matches."""
    topic = await extract_topic(
        "i think the recovery customer thing is fine",
        ledger=seeded_ledger, company_id=company_id,
        threshold=0.95,
    )
    # The text doesn't include "customer recovery flow" verbatim, only
    # rearranged tokens. Score = 0.85 (all tokens present, not contiguous)
    # which is below 0.95.
    assert topic is None


# ---------------------------------------------------------------------------
# Pure-function scoring (no ledger I/O)
# ---------------------------------------------------------------------------


def test_match_against_catalog_full_substring_scores_highest():
    catalog = [
        _CatalogEntry(kind="kpi", id=KPI_CHURN, label="churn",
                      domain_id=None),
    ]
    topic = match_against_catalog(
        "churn is rising", catalog, threshold=0.5,
    )
    assert topic is not None
    assert topic.confidence == 1.0


def test_match_against_catalog_exact_no_match_returns_none():
    catalog = [
        _CatalogEntry(kind="kpi", id=KPI_CHURN, label="churn",
                      domain_id=None),
    ]
    topic = match_against_catalog(
        "the team is happy", catalog, threshold=0.5,
    )
    assert topic is None
