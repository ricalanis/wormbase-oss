"""Parametrized matrix exercising every payload kind: construct, reject extras,
roundtrip via model_dump → model_validate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

UID = UUID("0190a0a0-0000-7000-8000-000000000010")
PID = UUID("0190a0a0-0000-7000-8000-000000000011")
DOMAIN_ID = UUID("0190a0a0-0000-7000-8000-000000000012")
TS = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)

CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.ProposePayload,
        {
            "target_kind": "source_proposed",
            "ref_id": UID,
            "reason": "drop",
            "proposed_by": "worm",
        },
    ),
    (
        E.ExecutePayload,
        {
            "propose_entry_id": UID,
            "tool": "profile_csv",
            "args": {"uri": "s3://x.csv"},
            "result_ref": "run-1",
        },
    ),
    (
        E.VerifyPayload,
        {
            "execute_entry_id": UID,
            "checks": [{"name": "row_count", "passed": True}],
            "passed": True,
        },
    ),
    (
        E.ResolvePayload,
        {"verify_entry_id": UID, "outcome": "keep", "rationale": "ok"},
    ),
    (
        E.SourceProposedPayload,
        {
            "source_id": UID,
            "source_kind": "file",
            "uri": "s3://b/x.csv",
            "added_via_flow": "drop_and_profile",
            "suggested_domain": "finance",
            "suggested_classification": "internal",
        },
    ),
    (
        E.SourceConfirmedPayload,
        {
            "source_id": UID,
            "confirmed_by_person": PID,
            "domain_id": DOMAIN_ID,
            "classification": "internal",
        },
    ),
    (
        E.SourceConnectedPayload,
        {"source_id": UID, "connection_ref": "conn-1", "connected_at": TS},
    ),
    (
        E.SourceProfiledPayload,
        {
            "source_id": UID,
            "row_count": 1234,
            "column_count": 5,
            "schema_hash": "ab" * 32,
            "profile_ref": "p-1",
        },
    ),
    (
        E.IngestLandedPayload,
        {
            "source_id": UID,
            "object_uri": "s3://bronze/x.parquet",
            "bytes": 1024,
            "row_count": 1234,
        },
    ),
    (
        E.IngestProfiledPayload,
        {
            "source_id": UID,
            "profile_ref": "p-2",
            "columns": [{"name": "mrr", "dtype": "float64"}],
        },
    ),
    (
        E.MemoryWrittenPayload,
        {
            "memory_id": UID,
            "content": "annual = 12 month commit",
            "tags": ["concept", "pricing"],
        },
    ),
    (
        E.ConceptProposedPayload,
        {
            "concept_id": UID,
            "name": "annual_plan",
            "definition": "12-month commit",
            "proposed_by": "worm",
        },
    ),
    (
        E.ConceptConfirmedPayload,
        {"concept_id": UID, "confirmed_by_person": PID},
    ),
    (
        E.ChatReceivedPayload,
        {
            "channel_id": "C01",
            "message_id": "m1",
            "sender_person": PID,
            "text": "hi",
            "classification": "internal",
        },
    ),
    (
        E.ChatSentPayload,
        {
            "channel_id": "C01",
            "message_id": "m2",
            "text": "hello",
            "in_reply_to": "m1",
            "attribution": {"owner": "ricardo", "classification": "internal"},
            "speech_act": "answer",
        },
    ),
    (
        E.GateFiredPayload,
        {
            "gate": "pii_redaction",
            "outcome": "blocked",
            "subject_ref": "m1",
            "reason": "email detected",
        },
    ),
    (
        E.KpiAnsweredPayload,
        {
            "question": "churn?",
            "answer": "4.2%",
            "sql_ref": "sql-1",
            "answer_hash": "c" * 64,
            "sources": [UID],
        },
    ),
    (
        E.HeuristicExperimentPayload,
        {
            "experiment_id": UID,
            "metric": "classifier_precision_on_seed_bank",
            "before": "0.80",
            "after": "0.82",
            "kept": True,
        },
    ),
    (
        E.PolicyAppliedPayload,
        {"policy_id": UID, "applied_to_ref": "m1", "outcome": "masked"},
    ),
    (
        E.InferenceServedPayload,
        {
            "request_id": UID,
            "served_by": "kimi",
            "is_fallback": True,
            "cache_key": "k-1",
            "latency_ms": 250,
        },
    ),
    (
        E.InferenceCacheRefreshedPayload,
        {
            "cache_path": "/tmp/x.sqlite",
            "entries_invalidated": 7,
            "reason": "model upgrade",
            "refreshed_by": "make refresh-inference-cache",
        },
    ),
    (
        E.SourceBronzedPayload,
        {
            "source_id": UID,
            "byte_count": 4096,
            "row_count": 100,
            "col_count": 5,
            "schema_hash": "ab" * 32,
            "mime": "text/csv",
            "raw_uri": "s3://bronze/x.csv",
            "profiled_at": TS,
        },
    ),
    (
        E.SourceSilveredPayload,
        {
            "source_id": UID,
            "inferred_columns": [
                {
                    "name": "id",
                    "type": "int",
                    "nullable": False,
                    "distinct_count": 100,
                    "classification": "internal",
                }
            ],
            "join_candidates": [PID],
            "silvered_at": TS,
        },
    ),
    (
        E.SourceGoldedPayload,
        {
            "source_id": UID,
            "gold_artifact_id": PID,
            "artifact_kind": "aggregate",
            "value": {"sum_revenue": 1234.5},
            "computed_at": TS,
        },
    ),
    (
        E.KpiProposedPayload,
        {
            "kpi_id": UID,
            "label": "monthly total revenue",
            "formula": "SUM(revenue)",
            "source_ids": [PID],
            "unit": "USD",
            "owner_position": "CFO",
            "proposed_at": TS,
        },
    ),
    (
        E.LakeDiscoveryPayload,
        {
            "lake_kind": "snowflake",
            "root_uri": "snowflake://demo/wh/analytics",
            "tables_seen": 8,
            "sources_proposed": 6,
            "classified_at": TS,
        },
    ),
]


@pytest.mark.parametrize("model,data", CASES)
def test_payload_constructs(model: type[E.EntryPayload], data: dict[str, Any]) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY


@pytest.mark.parametrize("model,data", CASES)
def test_payload_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", CASES)
def test_payload_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_chat_sent_speech_act_defaults_to_answer() -> None:
    payload = E.ChatSentPayload(
        channel_id="C", message_id="m", text="hi", attribution={}
    )
    assert payload.speech_act == "answer"


def test_chat_sent_rejects_unknown_speech_act() -> None:
    with pytest.raises(ValidationError):
        E.ChatSentPayload(
            channel_id="C",
            message_id="m",
            text="hi",
            attribution={},
            speech_act="invalid",  # type: ignore[arg-type]
        )


def test_inference_served_records_provenance() -> None:
    p = E.InferenceServedPayload(
        request_id=UID,
        served_by="gemma",
        is_fallback=False,
        cache_key="k",
        latency_ms=42,
    )
    assert p.served_by == "gemma" and p.is_fallback is False


def test_inference_cache_refreshed_records_provenance() -> None:
    """Wave-H Phase 1 Task 1A — cache-rotation audit payload."""
    p = E.InferenceCacheRefreshedPayload(
        cache_path="/var/wormbase/inference-cache.sqlite",
        entries_invalidated=128,
        reason="model upgrade kimi-k2.6 → kimi-k2.7",
        refreshed_by="ops:ricardo",
    )
    assert p.entries_invalidated == 128
    assert p.reason.startswith("model upgrade")
    assert p.kind == "inference_cache_refreshed"


def test_inference_cache_refreshed_rejects_negative_count() -> None:
    with pytest.raises(ValidationError):
        E.InferenceCacheRefreshedPayload(
            cache_path="/tmp/x.sqlite",
            entries_invalidated=-1,
            reason="r",
            refreshed_by="r",
        )


def test_inference_cache_refreshed_kind_registered() -> None:
    assert "inference_cache_refreshed" in E.KIND_REGISTRY
    assert (
        E.KIND_REGISTRY["inference_cache_refreshed"]
        is E.InferenceCacheRefreshedPayload
    )


def test_inference_cache_refreshed_roundtrips() -> None:
    p = E.InferenceCacheRefreshedPayload(
        cache_path="/tmp/y.sqlite",
        entries_invalidated=0,
        reason="initial baseline",
        refreshed_by="make refresh-inference-cache",
    )
    again = E.InferenceCacheRefreshedPayload.model_validate(p.model_dump())
    assert again == p
