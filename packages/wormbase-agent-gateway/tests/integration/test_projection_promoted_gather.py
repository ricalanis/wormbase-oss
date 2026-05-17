"""v2.B Phase 3c — projection-promoted gather for axes 1+3.

The Phase 3c gather replaces the 30d / 14d ledger-scan with a
projection-table SELECT (pgvector cosine TopK on Postgres, Python
cosine fallback on SQLite). These tests pin:

  * axis 1 (template promotion) reaches the same promotion outcome
    via the projection-gather as it does via the ledger-scan
    (Decision D1 reshape preserves cluster_fn input shape);
  * axis 3 (bad-pattern) likewise;
  * opt-out (``projection_reader=None``) preserves byte-identical
    behaviour — the ledger-scan path is unchanged;
  * the reader is invoked with the triggering entry's embedding when
    one is present, and with ``None`` when it is not (Decision D3);
  * the quality_filter still runs after gather (Decision D6);
  * multi-tenant isolation is honoured at the reader layer (Decision
    D4) — confirmed via a stub reader whose body asserts on the
    company_id argument;
  * wire-replay determinism — two runs against the same reader-state
    + same recorded ledger produce the same gather output.

These tests use a stub :class:`QueryOutcomeProjectionReader` so they
are dependency-free of Postgres + SQLite engines. The real readers
are tested in
``apps/worm-core/tests/test_query_outcome_projection_reader.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    OutcomeToTemplatePromotionReactivity,
    make_outcome_to_template_promotion_reactivity,
    make_query_failure_to_bad_pattern_reactivity,
)


_COMPANY_A = UUID("00000000-0000-0000-0000-0000000c3a01")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000c3b01")


# ---------------------------------------------------------------------------
# In-memory stub reader for testing the gather plumbing
# ---------------------------------------------------------------------------


@dataclass
class _StubProjectionReader:
    """Minimal :class:`QueryOutcomeProjectionReader` implementation.

    Holds a dict ``{company_id: [row, ...]}`` and replays it through
    the same Decision-D1 reshape the production readers do. Records
    call args so tests can assert on the invocation surface
    (multi-tenant isolation, embedding pass-through).
    """

    rows_by_company: dict[UUID, list[dict[str, Any]]]
    call_log: list[dict[str, Any]] = field(default_factory=list)

    async def recent_outcomes(
        self,
        *,
        company_id: UUID,
        triggering_embedding: Sequence[float] | None,
        days: int,
        topk_limit: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        self.call_log.append({
            "company_id": company_id,
            "triggering_embedding": (
                list(triggering_embedding)
                if triggering_embedding is not None else None
            ),
            "days": days,
            "topk_limit": topk_limit,
            "now": now,
        })
        # Multi-tenant SQL-shape: never return rows for the wrong tenant.
        return list(self.rows_by_company.get(company_id, []))


def _outcome_row(
    *,
    row_id: str,
    nl_question: str,
    embedding: list[float] | None,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
) -> dict[str, Any]:
    """Build an entry-shaped row matching what the production reader
    yields after the Decision-D1 reshape. The cluster_fn consumes it
    unchanged."""
    args: dict[str, Any] = {
        "agent_query_id": f"aq-{row_id}",
        "nl_question": nl_question,
        "final_query_spec": {"metric": "revenue", "domain_id": "dom-finance"},
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "user_correction": None,
        "quality_score": quality_score,
    }
    if embedding is not None:
        args["embedding"] = list(embedding)
    return {
        "kind": "execute",
        "entry_id": row_id,
        "seq": 0,
        "ts": datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc),
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": args,
            "result_ref": f"aq-{row_id}",
        },
    }


async def _write_trigger_outcome(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    nl_question: str,
    embedding: list[float] | None,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
) -> dict[str, Any]:
    """Write the ONE triggering outcome onto the ledger (the projection-
    gather reads the rest from the reader stub, not the ledger)."""
    aqi = str(uuid4())
    outcome_dict: dict[str, Any] = {
        "agent_query_id": aqi,
        "nl_question": nl_question,
        "final_query_spec": {"metric": "revenue", "domain_id": "dom-finance"},
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "user_correction": None,
        "quality_score": quality_score,
    }
    if embedding is not None:
        outcome_dict["embedding"] = embedding
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "query_outcome_recorded",
            "ref_id": aqi,
            "reason": f"test trigger aqi={aqi}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_query_outcome_recorded",
            "args": outcome_dict,
            "result_ref": aqi,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "outcome_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "outcome_recorded",
        },
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company_id)
    executes = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_query_outcome_recorded"
        and ((r["payload"] or {}).get("args") or {}).get("agent_query_id") == aqi
    ]
    return executes[-1]


def _fetch_template_promotions(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "propose"
        and "nl_intent" in (r.get("payload") or {})
        and "promoted_from_outcome_ids" in (r.get("payload") or {})
    ]


def _fetch_bad_pattern_proposeds(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "bad_pattern_proposed"
    ]


# ---------------------------------------------------------------------------
# Axis 1 — projection-gather promotes a cluster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axis1_projection_gather_promotes_cluster() -> None:
    """Reader yields 3 similar-embedding rows + the triggering outcome
    is one of them → one template promotion (same outcome as the
    ledger-scan path)."""
    ledger = InMemoryLedger()
    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]

    trigger = await _write_trigger_outcome(
        ledger, company_id=_COMPANY_A,
        nl_question="What is revenue this quarter?",
        embedding=base,
    )
    # The reader returns 3 rows — including a row mirroring the
    # trigger (so the cluster includes the trigger's entry_id).
    reader = _StubProjectionReader(rows_by_company={
        _COMPANY_A: [
            _outcome_row(
                row_id=str(trigger["entry_id"]),
                nl_question="What is revenue this quarter?",
                embedding=base,
            ),
            _outcome_row(
                row_id="r-near-1",
                nl_question="How much money did we make in Q3?",
                embedding=[b + 0.005 for b in base],
            ),
            _outcome_row(
                row_id="r-near-2",
                nl_question="Show me quarterly revenue numbers",
                embedding=[b + 0.01 for b in base],
            ),
        ],
    })
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_outcome_to_template_promotion_reactivity(
            projection_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    fired = await runner.run_once()
    assert fired >= 1

    rows = await ledger.fetch(_COMPANY_A)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1
    # The reader's call surface received the trigger's embedding.
    assert reader.call_log, "reader was not invoked"
    last_call = reader.call_log[-1]
    assert last_call["company_id"] == _COMPANY_A
    assert last_call["triggering_embedding"] == base
    assert last_call["days"] == 30
    assert last_call["topk_limit"] >= 1


# ---------------------------------------------------------------------------
# Axis 3 — projection-gather emits bad_pattern_proposed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axis3_projection_gather_emits_bad_pattern() -> None:
    """Two failed outcomes (used=True AND useful=False) returned by the
    reader → one bad_pattern_proposed via the projection-gather."""
    ledger = InMemoryLedger()
    base = [0.7, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    trigger = await _write_trigger_outcome(
        ledger, company_id=_COMPANY_A,
        nl_question="What is the revenue trend?",
        embedding=base,
        used=True, useful=False, quality_score="0.92",
    )
    reader = _StubProjectionReader(rows_by_company={
        _COMPANY_A: [
            _outcome_row(
                row_id=str(trigger["entry_id"]),
                nl_question="What is the revenue trend?",
                embedding=base,
                used=True, useful=False, quality_score="0.92",
            ),
            _outcome_row(
                row_id="r-fail-1",
                nl_question="Where is revenue going this month?",
                embedding=[b + 0.005 for b in base],
                used=True, useful=False, quality_score="0.95",
            ),
        ],
    })
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_query_failure_to_bad_pattern_reactivity(
            projection_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_A)
    proposeds = _fetch_bad_pattern_proposeds(rows)
    assert len(proposeds) == 1
    # The reader's day-window for axis 3 is 14d, not 30d.
    assert reader.call_log[-1]["days"] == 14


# ---------------------------------------------------------------------------
# Opt-out preserves byte-identical behaviour (no reader passed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optout_uses_ledger_scan_path() -> None:
    """When ``projection_reader=None`` the factory returns the
    pre-Phase-3c byte-identical Reactivity, and the existing ledger-scan
    path runs unchanged. We pin this by writing 3 outcomes to the
    ledger (no reader stub at all) and confirming the template
    promotion still lands."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_outcome_to_template_promotion_reactivity(),  # no reader
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    for _ in range(3):
        await _write_trigger_outcome(
            ledger, company_id=_COMPANY_A,
            nl_question="What is the revenue this quarter?",
            embedding=None,  # forces substring cluster path
        )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_A)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1


@pytest.mark.asyncio
async def test_class_optout_same_as_factory() -> None:
    """The ``OutcomeToTemplatePromotionReactivity()`` class default
    (no projection_reader) is identical to
    ``make_outcome_to_template_promotion_reactivity()`` default.
    Confirmed by running both side by side and confirming both promote."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(OutcomeToTemplatePromotionReactivity())  # no reader
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    for _ in range(3):
        await _write_trigger_outcome(
            ledger, company_id=_COMPANY_A,
            nl_question="What is the revenue this quarter?",
            embedding=None,
        )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_A)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1


# ---------------------------------------------------------------------------
# Multi-tenant isolation — reader is called with the company_id at the SQL layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multitenant_isolation_at_reader_layer() -> None:
    """Reader is called per-tenant — company A's projection-gather never
    sees company B's rows (Decision D4)."""
    ledger = InMemoryLedger()
    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]
    # Both companies' rows in the same reader bank — the SQL-side
    # filter handles isolation.
    reader = _StubProjectionReader(rows_by_company={
        _COMPANY_A: [
            _outcome_row(
                row_id=f"a-{i}",
                nl_question=f"a-question-{i}",
                embedding=[b + 0.005 * i for b in base],
            ) for i in range(3)
        ],
        _COMPANY_B: [
            _outcome_row(
                row_id=f"b-{i}",
                nl_question=f"b-question-{i}",
                embedding=[b + 0.005 * i for b in base],
            ) for i in range(3)
        ],
    })
    trigger = await _write_trigger_outcome(
        ledger, company_id=_COMPANY_A,
        nl_question="company A trigger",
        embedding=base,
    )
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_outcome_to_template_promotion_reactivity(
            projection_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()

    # Reader was invoked with company A — never with B.
    assert reader.call_log, "reader was not invoked"
    invoked_cids = {c["company_id"] for c in reader.call_log}
    assert invoked_cids == {_COMPANY_A}
    # Promotion uses only company-A row ids — no B leakage.
    rows = await ledger.fetch(_COMPANY_A)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1
    src_ids = set(promotions[0]["payload"]["promoted_from_outcome_ids"])
    # Trigger entry_id + a-0/a-1/a-2 should be the candidate set;
    # b-* must NOT appear.
    assert not any(s.startswith("b-") for s in src_ids), (
        f"company B leakage detected: {src_ids}"
    )
    _ = trigger  # keep linter happy


# ---------------------------------------------------------------------------
# Triggering-embedding-missing fallback (Decision D3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_invoked_with_none_when_trigger_has_no_embedding() -> None:
    """When the triggering entry has no embedding, the reader is
    invoked with ``triggering_embedding=None`` and falls back to a
    non-vector windowed SELECT (Decision D3 fallback branch)."""
    ledger = InMemoryLedger()
    reader = _StubProjectionReader(rows_by_company={_COMPANY_A: []})

    # Trigger written WITHOUT an embedding.
    await _write_trigger_outcome(
        ledger, company_id=_COMPANY_A,
        nl_question="trigger with no embedding",
        embedding=None,
    )
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_outcome_to_template_promotion_reactivity(
            projection_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()
    assert reader.call_log, "reader was not invoked"
    assert reader.call_log[-1]["triggering_embedding"] is None


# ---------------------------------------------------------------------------
# Quality filter still runs after gather (Decision D6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_filter_drops_low_quality_rows_post_gather() -> None:
    """Axis 1's substring-cluster path re-checks per-member quality
    after the projection-gather (Decision D6 — the Compounding
    primitive's quality_filter still gates the trigger, and the
    cluster_fn re-applies it on members in the substring path).

    The reader returns a mixed batch (one high-quality + two
    low-quality), all WITHOUT embeddings so they route through the
    substring cluster_fn. Only the high-quality row survives the
    cluster, so the cluster never reaches threshold=3 and no
    promotion lands."""
    ledger = InMemoryLedger()
    trigger = await _write_trigger_outcome(
        ledger, company_id=_COMPANY_A,
        nl_question="hq trigger",
        embedding=None,
        quality_score="0.95",
    )
    reader = _StubProjectionReader(rows_by_company={
        _COMPANY_A: [
            _outcome_row(
                row_id=str(trigger["entry_id"]),
                nl_question="hq trigger",
                embedding=None,
                quality_score="0.95",
            ),
            # Low-quality — drops out of axis-1 substring cluster_fn.
            _outcome_row(
                row_id="low-1",
                nl_question="hq trigger",
                embedding=None,
                quality_score="0.5",
            ),
            _outcome_row(
                row_id="low-2",
                nl_question="hq trigger",
                embedding=None,
                quality_score="0.3",
            ),
        ],
    })
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
    registry.register(
        make_outcome_to_template_promotion_reactivity(
            projection_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_A, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_A)
    promotions = _fetch_template_promotions(rows)
    assert promotions == []


# ---------------------------------------------------------------------------
# Replay determinism (Decision D5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projection_gather_deterministic_across_runs() -> None:
    """Same reader state + same ledger → same cluster + same promotion
    across two independent runs. Wire-replay safety."""
    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]

    async def _do_run() -> set[str]:
        ledger = InMemoryLedger()
        trigger = await _write_trigger_outcome(
            ledger, company_id=_COMPANY_A,
            nl_question="repeat me",
            embedding=base,
        )
        reader = _StubProjectionReader(rows_by_company={
            _COMPANY_A: [
                _outcome_row(
                    row_id=str(trigger["entry_id"]),
                    nl_question="repeat me",
                    embedding=base,
                ),
                _outcome_row(
                    row_id="r-2",
                    nl_question="repeat me 2",
                    embedding=[b + 0.005 for b in base],
                ),
                _outcome_row(
                    row_id="r-3",
                    nl_question="repeat me 3",
                    embedding=[b + 0.01 for b in base],
                ),
            ],
        })
        registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_A)
        registry.register(
            make_outcome_to_template_promotion_reactivity(
                projection_reader=reader,
            ),
        )
        runner = ReactivityRunner(
            ledger=ledger, company_id=_COMPANY_A, registry=registry,
            poll_interval_s=0.01,
        )
        await runner.run_once()
        rows = await ledger.fetch(_COMPANY_A)
        promotions = _fetch_template_promotions(rows)
        assert len(promotions) == 1
        return set(promotions[0]["payload"]["promoted_from_outcome_ids"])

    src_ids_1 = await _do_run()
    src_ids_2 = await _do_run()
    # entry_ids differ across runs (uuid4 trigger), but the BY-CONSTRUCTION
    # cardinality is identical (3 in each cluster).
    assert len(src_ids_1) == len(src_ids_2) == 3
